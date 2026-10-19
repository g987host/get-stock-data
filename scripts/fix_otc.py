import os, time, requests, pandas as pd
from datetime import datetime

PATH = "data/tw_close_110d.parquet"
TOKEN = os.getenv("FINMIND_TOKEN")

def fetch_one(sid, start_date, end_date):
    url = "https://api.finmindtrade.com/api/v4/data"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    params = {"dataset":"TaiwanStockPrice","data_id":sid,"start_date":start_date,"end_date":end_date}
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            j = r.json()
            if j.get("status") == 402: # 限速
                print("  402 限速，睡70秒")
                time.sleep(70)
                continue
            if j.get("status") != 200:
                print(f"  {sid} 回 {j.get('msg')}")
                return pd.DataFrame()
            return pd.DataFrame(j.get("data", []))
        except Exception as e:
            print(f"  {sid} 例外 {e} 重試")
            time.sleep(10)
    return pd.DataFrame()

df_old = pd.read_parquet(PATH)
df_old["date"] = pd.to_datetime(df_old["date"])
start_date = df_old["date"].min().strftime("%Y-%m-%d")
end_date = df_old["date"].max().strftime("%Y-%m-%d")

# 上櫃清單
r = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", timeout=30)
otc_list = [x["SecuritiesCompanyCode"] for x in r.json()]
print(f"上櫃清單 {len(otc_list)} 檔")

# 已經有幾天資料的就跳過 (續跑用)
done = set(df_old["stock_id"].unique())
todo = [s for s in otc_list if s not in done]
print(f"已完成 {len(done)} 檔，還要 {len(todo)} 檔")

all_otc = []
for i, sid in enumerate(todo):
    # 只跑 300 檔就先存檔，避免一次跑太久被中斷
    if i>0 and i % 300 == 0:
        print(f"先存檔中繼 {i} 檔")
        if all_otc:
            df_mid = pd.concat(all_otc, ignore_index=True)
            df_mid["date"] = pd.to_datetime(df_mid["date"])
            df_old = pd.concat([df_old, df_mid], ignore_index=True).drop_duplicates(subset=["stock_id","date"], keep="last")
            df_old.to_parquet(PATH, index=False)
            all_otc = []
    
    df = fetch_one(sid, start_date, end_date)
    if not df.empty:
        all_otc.append(df[["stock_id","date","close"]])
        print(f"{i+1}/{len(todo)} {sid} OK")
    time.sleep(7)  # 關鍵：7秒一次，絕不觸發錯誤封鎖

if all_otc:
    df_otc = pd.concat(all_otc, ignore_index=True)
    df_otc["date"] = pd.to_datetime(df_otc["date"])
    df_final = pd.concat([df_old, df_otc], ignore_index=True).drop_duplicates(subset=["stock_id","date"], keep="last")
    df_final.to_parquet(PATH, index=False)
    print(f"完成 {len(df_final)} rows")
