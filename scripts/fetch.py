import os, requests, pandas as pd
from datetime import datetime, timedelta

TOKEN = os.getenv("FINMIND_TOKEN")
PARQUET_PATH = "data/tw_close_110d.parquet"
# 多抓 30 天避免遇到連假，確保交易日夠 110 天
START_DATE = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

def fetch_finmind(start_date):
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockPrice",
        "start_date": start_date,
        "token": TOKEN
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()["data"]
    df = pd.DataFrame(data)
    # 只留你要的欄位
    df = df[["stock_id", "date", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna()

df_new = fetch_finmind(START_DATE)

# 合併舊檔
if os.path.exists(PARQUET_PATH):
    df_old = pd.read_parquet(PARQUET_PATH)
    df_old["date"] = pd.to_datetime(df_old["date"])
    df_all = pd.concat([df_old, df_new]).drop_duplicates(subset=["stock_id","date"], keep="last")
else:
    df_all = df_new

df_all = df_all.sort_values(["date","stock_id"])

# 只保留最近 110 個交易日
last_110_dates = sorted(df_all["date"].unique())[-110:]
df_110 = df_all[df_all["date"].isin(last_110_dates)]

os.makedirs("data", exist_ok=True)
df_110.to_parquet(PARQUET_PATH, index=False)
print(f"saved {len(last_110_dates)} trading days, {len(df_110)} rows to {PARQUET_PATH}")
