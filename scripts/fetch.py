import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

PARQUET_PATH = "data/tw_close_110d.parquet"

def fetch_twse_mi_index(date_str):
    # date_str = YYYYMMDD
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=ALLBUT0999&response=json"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        if not r.text or not r.text.strip().startswith("{"):
            return pd.DataFrame()
        j = r.json()
        if j.get("stat") != "OK":
            return pd.DataFrame()
        table = None
        for t in j.get("tables", []):
            if "證券代號" in t.get("fields", []):
                table = t
                break
        if not table:
            return pd.DataFrame()
        fields = table["fields"]
        i_code = fields.index("證券代號")
        i_close = fields.index("收盤價")
        rows = []
        for row in table["data"]:
            try:
                code = row[i_code].strip()
                close = float(row[i_close].replace(",", ""))
                rows.append({"stock_id": code, "date": date_str, "close": close})
            except:
                continue
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"TWSE {date_str} fail: {e}")
        return pd.DataFrame()

def fetch_tpex_day(date_slash):
    # date_slash = YYYY/MM/DD 轉民國年
    try:
        y, m, d = date_slash.split("/")
        roc_y = int(y) - 1911
        roc_date = f"{roc_y}/{m}/{d}"
        url = f"https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_quote_result.php?l=zh-tw&o=json&se=AL&d={roc_date}&s=0,asc,0"
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.tpex.org.tw/"
        }, timeout=30)
        if not r.text or not r.text.strip().startswith("{"):
            return pd.DataFrame()
        j = r.json()
        rows = []
        for arr in j.get("aaData", []):
            try:
                code = arr[0].strip()
                close = float(arr[2].replace(",", ""))
                rows.append({"stock_id": code, "date": date_slash.replace("/", ""), "close": close})
            except:
                continue
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"TPEX {date_slash} fail: {e}")
        return pd.DataFrame()

def build_history(days_back=180):
    all_df = []
    today = datetime.now()
    for i in range(days_back):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        ymd = d.strftime("%Y%m%d")
        slash = d.strftime("%Y/%m/%d")
        df1 = fetch_twse_mi_index(ymd)
        df2 = fetch_tpex_day(slash)
        combined = pd.concat([df1, df2], ignore_index=True) if not df1.empty or not df2.empty else pd.DataFrame()
        if not combined.empty:
            all_df.append(combined)
            print(f"{ymd} TWSE:{len(df1)} TPEX:{len(df2)} total:{len(combined)}")
        time.sleep(1.2)
    if not all_df:
        return pd.DataFrame()
    df = pd.concat(all_df, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df

# --- 主流程 聰明版 ---
if os.path.exists(PARQUET_PATH):
    df_old = pd.read_parquet(PARQUET_PATH)
    df_old["date"] = pd.to_datetime(df_old["date"])
    last_date = df_old["date"].max()
    # 算從最後一天到今天差幾天，多抓3天保險
    days_diff = (datetime.now() - last_date).days + 3
    days_back = min(max(days_diff, 5), 10)  # 最少5天，最多10天
    print(f"已有資料到 {last_date.date()}，只補最近 {days_back} 天")
else:
    df_old = pd.DataFrame()
    days_back = 180
    print(f"第一次建檔，抓 {days_back} 天")
df_new = build_history(days_back)
if df_new.empty and df_old.empty:
    raise SystemExit("抓不到資料")
df_all = pd.concat([df_old, df_new], ignore_index=True).drop_duplicates(subset=["stock_id","date"], keep="last")
df_all = df_all.sort_values("date")
last_110 = sorted(df_all["date"].unique())[-110:]
df_110 = df_all[df_all["date"].isin(last_110)]
os.makedirs("data", exist_ok=True)
df_110.to_parquet(PARQUET_PATH, index=False)
print(f"saved {len(last_110)} days, {len(df_110)} rows")
