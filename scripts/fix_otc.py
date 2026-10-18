import time, requests, pandas as pd
from datetime import datetime

PATH = "data/tw_close_110d.parquet"

def fetch_tpex_one(roc_date, slash_date):
    # 方法1: 舊版 otc_quotes_no1430 (要用民國年)
    urls = [
        f"https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_quote_result.php?l=zh-tw&o=json&se=AL&d={roc_date}&s=0,asc,0",
        f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&o=json&se=AL&d={roc_date}&s=0,asc,0",
    ]
    headers = {"User-Agent":"Mozilla/5.0", "Referer":"https://www.tpex.org.tw/"}
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if not r.text or not r.text.strip().startswith("{"):
                continue
            j = r.json()
            if "aaData" not in j or not j["aaData"]:
                continue
            rows = []
            for arr in j["aaData"]:
                try:
                    rows.append({"stock_id": arr[0].strip(), "date": slash_date.replace("/",""), "close": float(arr[2].replace(",",""))})
                except: continue
            if rows:
                return pd.DataFrame(rows)
        except Exception as e:
            print(f"  TPEX {roc_date} {url} fail {e}")
    return pd.DataFrame()

# 1. 讀你現有的 110 天 (只有上市)
df_old = pd.read_parquet(PATH)
df_old["date"] = pd.to_datetime(df_old["date"])
dates = sorted(df_old["date"].unique())

print(f"現有 {len(dates)} 天, 範例 {dates[-1].date()}")

# 2. 只補這些日期的上櫃
otc_all = []
for d in dates[-110:]:  # 就補你現有的 110 天
    slash = d.strftime("%Y/%m/%d")
    y,m,dd = slash.split("/")
    roc = f"{int(y)-1911}/{m}/{dd}"
    df_otc = fetch_tpex_one(roc, slash)
    print(f"{slash} -> {roc} TPEX:{len(df_otc)}")
    if not df_otc.empty:
        otc_all.append(df_otc)
    time.sleep(1.2)

if otc_all:
    df_otc_all = pd.concat(otc_all, ignore_index=True)
    df_otc_all["date"] = pd.to_datetime(df_otc_all["date"], format="%Y%m%d")
    
    df_merged = pd.concat([df_old, df_otc_all], ignore_index=True).drop_duplicates(subset=["stock_id","date"], keep="last")
    df_merged.to_parquet(PATH, index=False)
    print(f"合併完成 {len(df_old)} -> {len(df_merged)} rows")
    print(df_merged[df_merged["stock_id"]=="3706"].tail())
else:
    print("上櫃還是抓不到，把上面印的錯誤貼給我")
    # 最後備援: 用 OpenAPI 抓當天上櫃
    try:
        r = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", timeout=30)
        print("OpenAPI 回應", r.text[:300])
    except Exception as e:
        print("OpenAPI 也失敗", e)
