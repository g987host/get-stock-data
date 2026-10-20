import requests, pandas as pd
from datetime import datetime, timedelta
import os, time

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

def fetch_twse_day(slash_date=None): # slash_date 已不用，留著避免呼叫處壞掉
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_AVG_ALL"
    headers = {
        "accept": "application/json",
        "If-Modified-Since": "Mon, 26 Jul 1997 05:00:00 GMT",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "Mozilla/5.0"
    }
    r = get_with_retry(url, headers=headers)
    if not r: return pd.DataFrame()
    try:
        data = r.json()
        rows=[]
        for x in data:
            sid = str(x.get("Code","")).strip()
            if len(sid)!=4 or not sid.isdigit(): continue

            raw = str(x.get("Date","")).strip() # 1151019
            try:
                if "/" in raw:
                    y,m,d = raw.split("/")
                    y=int(y)
                    if y<1000: y+=1911
                else:
                    raw = raw.zfill(7)
                    if len(raw)==7: # 1151019
                        y,m,d = int(raw[:3]), int(raw[3:5]), int(raw[5:7])
                    else: # 20251020
                        y,m,d = int(raw[:4]), int(raw[4:6]), int(raw[6:8])
                    if y<1000: y+=1911
                date_str = f"{y:04d}{m:02d}{d:02d}"
            except:
                continue

            close_str = str(x.get("ClosingPrice","")).replace(",","").strip()
            if close_str in ("","-","--"): continue
            try:
                close = float(close_str)
            except:
                continue

            rows.append({"stock_id":sid,"date":date_str,"close":close})

        df=pd.DataFrame(rows)
        if not df.empty:
            df["date"]=pd.to_datetime(df["date"], format="%Y%m%d")
        print(f"{df['date'].max().date() if not df.empty else 'N/A'} TSE {len(df)} (STOCK_DAY_AVG_ALL)")
        return df
    except Exception as e:
        print(f"TSE失敗 {e}")
        return pd.DataFrame()

def fetch_tpex_openapi():
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
    headers = {
        "accept": "application/json",
        "If-Modified-Since": "Mon, 26 Jul 1997 05:00:00 GMT",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "Mozilla/5.0"
    }
    r = requests.get(url, headers=headers, timeout=30)
    data = r.json()
    print(f"總共 {len(data)} 檔")

    rows=[]
    for x in data:
        sid = str(x.get("SecuritiesCompanyCode","")).strip()
        if len(sid)!=4 or not sid.isdigit():  # 濾掉 00411A 這種
            continue
        
        raw = str(x.get("Date","")).strip()  # 1151019
        try:
            if "/" in raw:
                y,m,d = raw.split("/")
                y=int(y)
            else:
                # 1151019 -> 115 10 19
                raw = raw.zfill(7)  # 補零
                y = int(raw[:3])
                m = int(raw[3:5])
                d = int(raw[5:7])
            if y < 1000:
                y += 1911
            date_str = f"{y:04d}/{m:02d}/{d:02d}"

            close = float(str(x.get("Close","")).replace(",",""))
            rows.append({"stock_id":sid,"date":date_str,"close":close})
        except:
            continue

    df=pd.DataFrame(rows)
    if not df.empty:
        df["date"]=pd.to_datetime(df["date"])
    print(f"TPEX {len(df)} 筆 (已篩4碼)")
    return df

# 讀舊檔
df_old = pd.read_parquet(PATH)
df_old["date"]=pd.to_datetime(df_old["date"])

all_new=[]
for i in range(3):
    slash=(datetime.now()-timedelta(days=i)).strftime("%Y/%m/%d")
    df=fetch_twse_day(slash)
    if not df.empty: all_new.append(df)

df_otc = fetch_tpex_openapi()
if not df_otc.empty: all_new.append(df_otc)

if all_new:
    df_new=pd.concat(all_new, ignore_index=True)
    today_cnt = df_new[df_new["date"]==df_new["date"].max()].shape[0]
    if today_cnt < 1500:
        print(f"今天只有 {today_cnt} 筆，等下一輪")
    else:
        df_merged=pd.concat([df_old, df_new], ignore_index=True).drop_duplicates(subset=["stock_id","date"], keep="last")
        last_110=sorted(df_merged["date"].unique())[-110:]
        df_merged=df_merged[df_merged["date"].isin(last_110)]
        df_merged.to_parquet(PATH, index=False)
        print(f"存檔 {len(df_merged)} rows, {df_merged['stock_id'].nunique()} 檔, 最新 {df_merged['date'].max().date()}")
