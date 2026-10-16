import requests, pandas as pd, re, os, argparse
from datetime import datetime

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
HEADERS = {"User-Agent":"Mozilla/5.0"}

def get_valid_4digit_codes():
    codes=set()
    try:
        r=requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L",timeout=15,headers=HEADERS).json()
        for row in r:
            c=str(row.get("公司代號") or "").strip()
            if re.match(r'^\d{4}$',c): codes.add(c)
    except: pass
    try:
        for mode in [2,4]:
            url=f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
            resp=requests.get(url,headers=HEADERS,timeout=15)
            text=resp.content.decode('big5',errors='ignore')
            codes|=set(re.findall(r'<td[^>]*>\s*(\d{4})\s*</td>',text))
    except: pass
    # 清掉ETF/DR
    codes={c for c in codes if not c.startswith("00") and not c.startswith("91") and not c.startswith("92")}
    print(f"網路有效清單抓到 {len(codes)} 檔")
    # 太少就不要用，回傳None改用寬鬆規則
    if len(codes) < 1500:
        print("清單太少，改用寬鬆規則 4位數+排除00/91/92")
        return None
    return codes

def publish_to_revenue_month(d):
    d=pd.to_datetime(d)
    y=d.year; m=d.month-1
    if m==0: m=12; y-=1
    return datetime(y,m,1).date()

def parse_yyyymm(v):
    s=re.sub(r"\D","",str(v))
    if len(s)==5: return datetime(int(s[:3])+1911,int(s[3:]),1).date()
    if len(s)==6: return datetime(int(s[:4]),int(s[4:]),1).date()
    return pd.to_datetime(v).date()

def fetch_twse():
    dfs=[]
    for url in [
        "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
    ]:
        try:
            r=requests.get(url,headers=HEADERS,timeout=15).json()
            dfs.append(pd.DataFrame(r))
        except Exception as e:
            print(f"{url} 失敗 {e}")
    if not dfs:
        return pd.DataFrame(columns=["stock_id","revenue_month","revenue","yoy"])
    df=pd.concat(dfs,ignore_index=True)
    df=df.rename(columns={
        "公司代號":"stock_id","資料年月":"yyyymm",
        "年度":"year","月份":"month",
        "營業收入-當月營收":"revenue",
        "營業收入-去年同月增減(%)":"yoy_raw"
    })
    if "yyyymm" not in df.columns and "year" in df.columns:
        df["yyyymm"]=df["year"].astype(str)+df["month"].astype(str).str.zfill(2)
    df["stock_id"]=df["stock_id"].astype(str).str.strip()
    df=df[df["stock_id"].str.match(r'^\d{4}$',na=False)]
    df=df[~df["stock_id"].str.startswith("00")]
    df=df[~df["stock_id"].str.startswith("91")]
    df=df[~df["stock_id"].str.startswith("92")]
    df["revenue_month"]=df["yyyymm"].apply(parse_yyyymm)
    df["revenue"]=pd.to_numeric(df["revenue"].astype(str).str.replace(",",""),errors="coerce")
    df["yoy"]=pd.to_numeric(df["yoy_raw"].astype(str).str.replace(",",""),errors="coerce")/100.0
    return df[["stock_id","revenue_month","revenue","yoy"]].dropna()

def normalize_finlab_wide(path, value_name):
    if not os.path.exists(path): return pd.DataFrame()
    df=pd.read_parquet(path)
    df.index=pd.to_datetime(df.index)
    date_col=df.index.name or "publish_date"
    df=df.reset_index()
    # 第一欄是公布日
    first_col=df.columns[0]
    long_df=df.melt(id_vars=[first_col], var_name="stock_id", value_name=value_name)
    long_df=long_df.rename(columns={first_col:"publish_date"})
    long_df["stock_id"]=long_df["stock_id"].astype(str).str.strip()
    # 寬鬆過濾，跟你要求一樣：只要4位數，排除ETF/DR
    long_df=long_df[long_df["stock_id"].str.match(r'^\d{4}$',na=False)]
    long_df=long_df[~long_df["stock_id"].str.startswith("00")]
    long_df=long_df[~long_df["stock_id"].str.startswith("91")]
    long_df=long_df[~long_df["stock_id"].str.startswith("92")]
    long_df["revenue_month"]=long_df["publish_date"].apply(publish_to_revenue_month)
    long_df=long_df.dropna(subset=[value_name])
    if value_name=="yoy":
        long_df[value_name]=long_df[value_name]/100.0
    return long_df[["stock_id","revenue_month",value_name]]

def main(init=False):
    import sys
    is_init = init or "--init" in sys.argv
    valid=get_valid_4digit_codes()

    new_df=fetch_twse()
    if not new_df.empty and valid is not None:
        new_df=new_df[new_df["stock_id"].isin(valid)]
    print(f"本月官方抓到 {len(new_df)} 筆")

    path13=f"{DATA_DIR}/revenue_13m.parquet"
    old=pd.DataFrame(columns=["stock_id","revenue_month","revenue","yoy"])
    if os.path.exists(path13):
        try:
            old=pd.read_parquet(path13)
            if not old.empty:
                old["revenue_month"]=pd.to_datetime(old["revenue_month"]).dt.date
        except:
            old=pd.DataFrame(columns=["stock_id","revenue_month","revenue","yoy"])

    if is_init:
        rev=normalize_finlab_wide(f"{DATA_DIR}/finlab_REV.parquet","revenue")
        yoy=normalize_finlab_wide(f"{DATA_DIR}/finlab_REV_YOY.parquet","yoy")
        if not rev.empty or not yoy.empty:
            fin=pd.merge(rev,yoy,on=["stock_id","revenue_month"],how="outer")
            if valid is not None and not fin.empty:
                fin=fin[fin["stock_id"].isin(valid)]
            old=pd.concat([old,fin],ignore_index=True)
            print(f"FINLAB合併 {len(fin)} 筆")

    combined=pd.concat([old,new_df],ignore_index=True)
    if combined.empty:
        print("沒有任何資料，可能是本月營收還沒公布，跳過")
        return

    combined=combined.drop_duplicates(subset=["stock_id","revenue_month"],keep="last")
    combined=combined.sort_values(["stock_id","revenue_month"])
    combined=combined.groupby("stock_id",group_keys=False).apply(lambda g: g.tail(13))

    combined.to_parquet(path13,index=False)
    
    if not combined.empty:
        latest_month=combined["revenue_month"].max()
        latest=combined[combined["revenue_month"]==latest_month]
        latest.to_csv(f"{DATA_DIR}/revenue_latest.csv",index=False,encoding="utf-8-sig")
        print(f"完成 13個月共 {len(combined)} 筆，最新月份 {latest_month} 有 {latest['stock_id'].nunique()} 檔")
    else:
        print("合併後還是空的")

if __name__=="__main__":
    main()