import requests, pandas as pd, io, csv, sys, time
from datetime import datetime, timezone, timedelta

PATH = "data/tw_close_110d.parquet"

def get_with_retry(url, **kwargs):
    for i in range(5):
        try:
            r = requests.get(url, timeout=60, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"重試 {i+1}/5 {e}")
            time.sleep(5)
    return None

# --- 新增：RWD 第1順位，現在回的是 CSV ---
def fetch_twse_rwd(target_yyyymmdd=None):
    if target_yyyymmdd is None:
        target_yyyymmdd = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    
    ts = int(time.time()*1000)
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?date={target_yyyymmdd}&response=json&_={ts}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.twse.com.tw/zh/afterTrading/STOCK_DAY_ALL.html",
        "Accept": "*/*",
    }
    # 先拿 cookie，不然會回空
    s = requests.Session()
    try:
        s.get("https://www.twse.com.tw/zh/afterTrading/STOCK_DAY_ALL.html", headers=headers, timeout=10)
    except: pass

    r = get_with_retry(url, headers=headers)
    if not r or not r.text.strip():
        print(f"RWD {target_yyyymmdd} 無資料")
        return pd.DataFrame()
    
    # 你剛剛印的就是這個格式
    # 日期,證券代號,證券名稱,成交股數,成交金額,開盤價,最高價,最低價,收盤價...
    # "1151020","2330","台積電",...
    rows = []
    try:
        # 現在是 CSV
        reader = csv.DictReader(io.StringIO(r.text))
        for row in reader:
            sid = str(row.get('證券代號','')).replace('"','').strip()
            if len(sid)!=4 or not sid.isdigit(): # 只留上市普通股，跟你原本邏輯一樣
                continue
            raw_date = str(row.get('日期','')).replace('"','').strip().zfill(7) # 1151020
            try:
                y,m,d = int(raw_date[:3])+1911, int(raw_date[3:5]), int(raw_date[5:7])
                date_str = f"{y:04d}{m:02d}{d:02d}"
                close = float(str(row.get('收盤價','')).replace('"','').replace(',',''))
                rows.append({"stock_id":sid,"date":date_str,"close":close})
            except: continue
    except Exception as e:
        print(f"RWD 解析失敗 {e}")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    print(f"TSE-RWD {len(df)} 筆 {df['date'].max().date() if not df.empty else ''}")
    return df

def fetch_twse_day(): # 你的舊的當備援
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_AVG_ALL"
    headers = {"accept":"application/json","User-Agent":"Mozilla/5.0","Cache-Control":"no-cache"}
    r = get_with_retry(url, headers=headers)
    if not r: return pd.DataFrame()
    data = r.json()
    rows=[]
    for x in data:
        sid=str(x.get("Code","")).strip()
        if len(sid)!=4 or not sid.isdigit(): continue
        raw=str(x.get("Date","")).strip()
        try:
            if "/" in raw:
                y,m,d = raw.split("/"); y=int(y)
                if y<1000: y+=1911
            else:
                raw=raw.zfill(7)
                if len(raw)==7: y,m,d=int(raw[:3]),int(raw[3:5]),int(raw[5:7])
                else: y,m,d=int(raw[:4]),int(raw[4:6]),int(raw[6:8])
                if y<1000: y+=1911
            date_str=f"{y:04d}{m:02d}{d:02d}"
            close=float(str(x.get("ClosingPrice","")).replace(",",""))
            rows.append({"stock_id":sid,"date":date_str,"close":close})
        except: continue
    df=pd.DataFrame(rows)
    if not df.empty: df["date"]=pd.to_datetime(df["date"], format="%Y%m%d")
    print(f"TSE-OpenAPI備援 {len(df)} 筆")
    return df

def fetch_tpex_openapi():
    url="https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
    headers={"accept":"application/json","If-Modified-Since":"Mon, 26 Jul 1997 05:00:00 GMT","Cache-Control":"no-cache","Pragma":"no-cache","User-Agent":"Mozilla/5.0"}
    r=get_with_retry(url, headers=headers)
    if not r: return pd.DataFrame()
    data=r.json()
    rows=[]
    for x in data:
        sid=str(x.get("SecuritiesCompanyCode","")).strip()
        if len(sid)!=4 or not sid.isdigit(): continue
        raw=str(x.get("Date","")).strip()
        try:
            raw=raw.zfill(7)
            y,m,d=int(raw[:3]),int(raw[3:5]),int(raw[5:7])
            if y<1000: y+=1911
            close=float(str(x.get("Close","")).replace(",",""))
            rows.append({"stock_id":sid,"date":f"{y:04d}{m:02d}{d:02d}","close":close})
        except: continue
    df=pd.DataFrame(rows)
    if not df.empty: df["date"]=pd.to_datetime(df["date"], format="%Y%m%d")
    print(f"TPEX {len(df)} 筆")
    return df

# ===== 主流程 =====
df_old=pd.read_parquet(PATH)
df_old["date"]=pd.to_datetime(df_old["date"])

# 1. 先檢查今天是不是已經超過1800檔
tw_now = datetime.now(timezone(timedelta(hours=8)))
today_str = tw_now.strftime("%Y%m%d")
if not df_old.empty:
    latest = df_old["date"].max()
    if latest.strftime("%Y%m%d") == today_str:
        cnt_today = (df_old["date"] == latest).sum()
        if cnt_today > 1800:
            print(f"今天 {today_str} 已有 {cnt_today} 筆 (>1800)，下午4點那次已跑過，跳過")
            sys.exit(0)

# 2. TSE 第1順位用 RWD
df_tse = fetch_twse_rwd(today_str)
if df_tse.empty:
    print("RWD 抓不到，fallback 到 OpenAPI AVG")
    df_tse = fetch_twse_day()

df_otc = fetch_tpex_openapi()

# 分開合併
df_merged = pd.concat([df_old, df_tse, df_otc], ignore_index=True).drop_duplicates(subset=["stock_id","date"], keep="last")
last_110=sorted(df_merged["date"].unique())[-110:]
df_merged=df_merged[df_merged["date"].isin(last_110)]
df_merged.to_parquet(PATH, index=False)

print(df_merged.groupby("date").size().tail(5))
print(f"最新檔: {df_merged['date'].max().date()} 全市場 {df_merged[df_merged['date']==df_merged['date'].max()].shape[0]} 筆")
