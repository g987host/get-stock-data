import os, requests, pandas as pd
from datetime import datetime, timedelta

TOKEN = os.getenv("FINMIND_TOKEN")
PARQUET_PATH = "data/tw_close_110d.parquet"

# 抓 180 天確保有 110 個交易日
START_DATE = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
END_DATE = datetime.now().strftime("%Y-%m-%d")

def fetch_all():
    url = "https://api.finmindtrade.com/api/v4/data"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    params = {
        "dataset": "TaiwanStockPrice",
        "start_date": START_DATE,
        "end_date": END_DATE,
        # 不給 data_id = 一次拿全市場，1個 request 搞定
    }
    r = requests.get(url, params=params, headers=headers, timeout=60)
    j = r.json()
    # FinMind 是用 json 裡的 status 報錯，不是 http status
    if j.get("status") != 200:
        raise RuntimeError(f"FinMind error: {j.get('msg')} | raw: {j}")
    df = pd.DataFrame(j["data"])
    if df.empty:
        raise RuntimeError("FinMind 回傳空資料，可能是假日或 token 額度用完")
    df = df[["stock_id", "date", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna()

df_new = fetch_all()

# 合併舊檔
if os.path.exists(PARQUET_PATH):
    df_old = pd.read_parquet(PARQUET_PATH)
    df_old["date"] = pd.to_datetime(df_old["date"])
    df_all = pd.concat([df_old, df_new]).drop_duplicates(
        subset=["stock_id","date"], keep="last"
    )
else:
    df_all = df_new

df_all = df_all.sort_values(["date","stock_id"])
last_110_dates = sorted(df_all["date"].unique())[-110:]
df_110 = df_all[df_all["date"].isin(last_110_dates)]

os.makedirs("data", exist_ok=True)
df_110.to_parquet(PARQUET_PATH, index=False)
print(f"OK: {len(last_110_dates)} 交易日, {len(df_110)} 筆 -> {PARQUET_PATH}")
