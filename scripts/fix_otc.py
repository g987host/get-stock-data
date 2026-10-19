import os, time, requests, pandas as pd
from datetime import datetime

PATH = "data/tw_close_110d.parquet"
TOKEN = os.getenv("FINMIND_TOKEN")

def fetch_one_otc(stock_id, start_date, end_date):
    url = "https://api.finmindtrade.com/api/v4/data"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        j = r.json()
        if j.get("status") != 200:
            # 402 就是被限速
            if "quota" in j.get("msg","").lower() or j.get("status")==402:
                print("限速了，睡60秒")
                time.sleep(60)
            return pd.DataFrame()
        return pd.DataFrame(j.get("data", []))
    except Exception as e:
        print(f"{stock_id} fail {e}")
        return pd.DataFrame()

# 1. 讀你現有的上市 110 天
df_old = pd.read_parquet(PATH)
df_old["date"] = pd.to_datetime(df_old["date"])
start_date = df_old["date"].min().strftime("%Y-%m-%d")
end_date = df_old["date"].max().strftime("%Y-%m-%d")
print(f"要補 {start_date} ~ {end_date}")

# 2. 拿上櫃清單 (用櫃買 OpenAPI 抓代號，這支不會擋)
r = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", timeout=30)
otc_list = [x["SecuritiesCompanyCode"] for x in r.json()]
print(f"上櫃清單 {len(otc_list)} 檔")

# 3. 一檔一檔抓 110 天
all_otc = []
for i, sid in enumerate(otc_list):
    df = fetch_one_otc(sid, start_date, end_date)
    if not df.empty:
        all_otc.append(df[["stock_id","date","close"]])
        print(f"{i+1}/{len(otc_list)} {sid} OK {len(df)}")
    time.sleep(6.5)  # 600次/小時 = 6秒一次，才不會 402

if all_otc:
    df_otc = pd.concat(all_otc, ignore_index=True)
    df_otc["date"] = pd.to_datetime(df_otc["date"])
    df_merged = pd.concat([df_old, df_otc], ignore_index=True).drop_duplicates(subset=["stock_id","date"], keep="last")
    df_merged.to_parquet(PATH, index=False)
    print(f"合併完成 {len(df_old)} -> {len(df_merged)}")
