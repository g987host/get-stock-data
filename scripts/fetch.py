import os, time, json, requests, pandas as pd
from datetime import datetime, timedelta

PATH = "data/tw_close_110d.parquet"
TOKEN = os.getenv("FINMIND_TOKEN")
PROGRESS = "data/otc_progress.json"

def get_with_retry(url, **kwargs):
    for i in range(5):
        try:
            r = requests.get(url, timeout=60, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"重試 {i+1}/5 {e}")
            time.sleep(10)
    return None

def fetch_twse_day(slash_date):
    yyyymmdd = slash_date.replace("/","")
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={yyyymmdd}&type=ALL&response=json"
    r = get_with_retry(url)
    if not r: return pd.DataFrame()
    try:
        j = r.json()
        if j.get("stat")!="OK": return pd.DataFrame()
        rows=[]
        for t in j.get("tables",[]):
            if "每日收盤行情" not in t.get("title",""): continue
            for arr in t["data"]:
                sid = arr[0].strip()
                if len(sid)!=4 or not sid.isdigit(): continue
                try:
                    rows.append({"stock_id":sid,"date":yyyymmdd,"close":float(arr[2].replace(",",""))})
                except: continue
        df=pd.DataFrame(rows)
        if not df.empty:
            df["date"]=pd.to_datetime(df["date"], format="%Y%m%d")
        print(f"{slash_date} TSE {len(df)}")
        return df
    except Exception as e:
        print(f"TSE 解析失敗 {e}")
        return pd.DataFrame()

def fetch_tpex_openapi():
    r = get_with_retry("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
                       headers={"User-Agent":"Mozilla/5.0"})
    if not r: return pd.DataFrame()
    try:
        data=r.json()
        rows=[]
        for x in data:
            sid=x["SecuritiesCompanyCode"]
            if len(sid)!=4 or not sid.isdigit(): continue
            rows.append({"stock_id":sid,"date":x["Date"],"close":float(str(x["Close"]).replace(",",""))})
        df=pd.DataFrame(rows)
        if not df.empty:
            df["date"]=pd.to_datetime(df["date"])
        print(f"TPEX OpenAPI {len(df)}")
        return df
    except Exception as e:
        print(f"TPEX失敗 {e}")
        return pd.DataFrame()

def fetch_finmind_one(sid, date_str):
    url="https://api.finmindtrade.com/api/v4/data"
    params={"dataset":"TaiwanStockPrice","data_id":sid,"start_date":date_str,"end_date":date_str}
    headers={"Authorization": f"Bearer {TOKEN}"}
    try:
        r=requests.get(url, params=params, headers=headers, timeout=30)
        j=r.json()
        if j.get("status")==402: return "LIMIT"
        data=j.get("data",[])
        if not data: return pd.DataFrame()
        return pd.DataFrame([{"stock_id":sid,"date":date_str,"close":float(data[0]["close"])}])
    except: return pd.DataFrame()

# 1. 讀舊檔
df_old=pd.read_parquet(PATH)
df_old["date"]=pd.to_datetime(df_old["date"])

# 2. 上市抓近3天
all_new=[]
for i in range(3):
    slash=(datetime.now()-timedelta(days=i)).strftime("%Y/%m/%d")
    df=all_new.append(fetch_twse_day(slash)) if False else fetch_twse_day(slash)
    if not df.empty: all_new.append(df)
    time.sleep(3)

# 3. 上櫃先試 OpenAPI
df_otc=fetch_tpex_openapi()

# 4. OpenAPI <500 筆就用 FinMind 備援
if len(df_otc)<500 and TOKEN:
    print("OpenAPI 失敗，切 FinMind 備援")
    today=datetime.now().strftime("%Y-%m-%d")
    # 上櫃清單
    r=get_with_retry("https://api.finmindtrade.com/api/v4/data",
                     params={"dataset":"TaiwanStockInfo"},
                     headers={"Authorization": f"Bearer {TOKEN}"})
    info=pd.DataFrame(r.json()["data"])
    col="type" if "type" in info.columns else "stock_type"
    otc_list=[c for c in info[info[col].isin(["上櫃","otc","OTC"])]["stock_id"].tolist() if len(c)==4 and c.isdigit()]
    
    done=json.load(open(PROGRESS)) if os.path.exists(PROGRESS) else []
    todo=[s for s in otc_list if s not in done]
    
    rows=[]
    for i,sid in enumerate(todo):
        if i>=550: break
        df=fetch_finmind_one(sid, today)
        if df=="LIMIT":
            print("撞到600上限，存進度等下一輪")
            break
        if not df.empty: 
            rows.append(df.iloc[0].to_dict())
            done.append(sid)
        if i%20==0: print(f"{i}/{len(todo)} {sid}")
        time.sleep(7)
    
    json.dump(done, open(PROGRESS,"w"))
    if rows:
        df_otc=pd.DataFrame(rows)
        df_otc["date"]=pd.to_datetime(df_otc["date"])
else:
    if os.path.exists(PROGRESS): os.remove(PROGRESS)

if not df_otc.empty: all_new.append(df_otc)

# 5. 合併存檔
if all_new:
    df_new=pd.concat(all_new, ignore_index=True)
    df_merged=pd.concat([df_old, df_new], ignore_index=True).drop_duplicates(subset=["stock_id","date"], keep="last")
    last_110=sorted(df_merged["date"].unique())[-110:]
    df_merged=df_merged[df_merged["date"].isin(last_110)]
    df_merged.to_parquet(PATH, index=False)
    print(f"存檔 {len(df_merged)} rows, {df_merged['stock_id'].nunique()} 檔, 最新 {df_merged['date'].max().date()}")
