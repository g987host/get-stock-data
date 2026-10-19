import time, requests, pandas as pd
from datetime import datetime, timedelta

PATH = "data/tw_close_110d.parquet"

def get_with_retry(url, **kwargs):
    for i in range(5):
        try:
            r = requests.get(url, timeout=60, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"  {url} 失敗 {e} 重試 {i+1}/5")
            time.sleep(10)
    return None

def fetch_twse_day(slash_date):
    # 上市 MI_INDEX
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={slash_date.replace('/','')}&type=ALL&response=json"
    r = get_with_retry(url)
    if not r: return pd.DataFrame()
    try:
        j = r.json()
        if j.get("stat")!="OK": return pd.DataFrame()
        rows=[]
        for table in j.get("tables",[]):
            if "每日收盤行情" not in table.get("title",""): continue
            for arr in table["data"]:
                try:
                    if len(arr[0].strip())!=4: continue
                    rows.append({"stock_id":arr[0].strip(),"date":slash_date.replace("/",""),"close":float(arr[2].replace(",",""))})
                except: continue
        return pd.DataFrame(rows)
    except: return pd.DataFrame()

def fetch_tpex_openapi():
    # 上櫃 OpenAPI 只有當天，一次回全部上櫃
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    r = get_with_retry(url, headers={"User-Agent":"Mozilla/5.0"})
    if not r: return pd.DataFrame()
    try:
        data = r.json()
        if not data: return pd.DataFrame()
        # Date 格式 113/10/16
        slash = data[0]["Date"]
        y,m,d = slash.split("/")
        iso = f"{int(y)+1911:04d}{int(m):02d}{int(d):02d}"
        rows=[]
        for x in data:
            sid = x["SecuritiesCompanyCode"]
            if len(sid)!=4 or not sid.isdigit(): continue
            try:
                rows.append({"stock_id":sid,"date":iso,"close":float(str(x["Close"]).replace(",",""))})
            except: continue
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"TPEX OpenAPI 解析失敗 {e}")
        return pd.DataFrame()

# 1. 讀舊檔
try:
    df_old = pd.read_parquet(PATH)
    df_old["date"] = pd.to_datetime(df_old["date"])
except:
    df_old = pd.DataFrame(columns=["stock_id","date","close"])

# 2. 抓近5個交易日，確保假日也有補到
dates = [(datetime.now()-timedelta(days=i)).strftime("%Y/%m/%d") for i in range(5)]

all_new=[]
for slash in dates:
    df_tse = fetch_twse_day(slash)
    print(f"{slash} TSE:{len(df_tse)}")
    if not df_tse.empty:
        all_new.append(df_tse)
    time.sleep(3)

# 上櫃只抓一次最新
df_otc = fetch_tpex_openapi()
print(f"TPEX OpenAPI:{len(df_otc)}")
if not df_otc.empty:
    all_new.append(df_otc)

if all_new:
    df_new = pd.concat(all_new, ignore_index=True)
    df_new["date"] = pd.to_datetime(df_new["date"], format="%Y%m%d")
    df_merged = pd.concat([df_old, df_new], ignore_index=True).drop_duplicates(subset=["stock_id","date"], keep="last")
    # 只留最近110個交易日
    last_110 = sorted(df_merged["date"].unique())[-110:]
    df_merged = df_merged[df_merged["date"].isin(last_110)]
    df_merged.to_parquet(PATH, index=False)
    print(f"完成 {len(df_merged)} rows, {df_merged['stock_id'].nunique()} 檔, 日期 {df_merged['date'].min().date()}~{df_merged['date'].max().date()}")
else:
    print("當天都沒抓到")
