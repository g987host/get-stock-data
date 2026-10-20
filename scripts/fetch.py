import requests, pandas as pd
from datetime import datetime

PATH = "data/tw_close_110d.parquet"

def get_with_retry(url, **kwargs):
    import time
    for i in range(5):
        try:
            r = requests.get(url, timeout=60, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"重試 {i+1}/5 {e}")
            time.sleep(5)
    return None

def fetch_twse_day():
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
    print(f"TSE {len(df)} 筆 {df['date'].max().date() if not df.empty else ''}")
    return df

def fetch_tpex_openapi():
    url="https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
    headers={"accept":"application/json","If-Modified-Since":"Mon, 26 Jul 1997 05:00:00 GMT","Cache-Control":"no-cache","Pragma":"no-cache","User-Agent":"Mozilla/5.0"}
    r=get_with_retry(url, headers=headers)
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

df_old=pd.read_parquet(PATH)
df_old["date"]=pd.to_datetime(df_old["date"])

df_tse=fetch_twse_day()
df_otc=fetch_tpex_openapi()

# 分開合併，不要用 len(tse)+len(otc) 去判斷
df_merged = pd.concat([df_old, df_tse, df_otc], ignore_index=True).drop_duplicates(subset=["stock_id","date"], keep="last")
last_110=sorted(df_merged["date"].unique())[-110:]
df_merged=df_merged[df_merged["date"].isin(last_110)]
df_merged.to_parquet(PATH, index=False)
print(df_merged.groupby("date").size().tail(5))
print(f"最新檔: {df_merged['date'].max().date()} 全市場 {df_merged[df_merged['date']==df_merged['date'].max()].shape[0]} 筆")
print(f"TSE最新 {df_tse['date'].max().date() if not df_tse.empty else '無'} {len(df_tse)}筆")
print(f"TPEX最新 {df_otc['date'].max().date() if not df_otc.empty else '無'} {len(df_otc)}筆")
