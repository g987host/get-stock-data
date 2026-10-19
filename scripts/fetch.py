import os, time, json, requests, pandas as pd
from datetime import datetime

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
            print(f"  重試 {i+1}/5 {e}")
            time.sleep(10)
    return None

def fetch_tpex_openapi():
    r = get_with_retry("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
                       headers={"User-Agent":"Mozilla/5.0"})
    if not r: return pd.DataFrame()
    try:
        data = r.json()
        rows=[]
        for x in data:
            sid = x["SecuritiesCompanyCode"]
            if len(sid)!=4 or not sid.isdigit(): continue
            rows.append({"stock_id":sid,"date":x["Date"],"close":float(str(x["Close"]).replace(",",""))})
        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except: return pd.DataFrame()

def fetch_finmind_onestock(sid, date_str):
    # date_str YYYY-MM-DD
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset":"TaiwanStockPrice","data_id":sid,"start_date":date_str,"end_date":date_str}
    headers = {"Authorization": f"Bearer {TOKEN}"}
    for _ in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            j = r.json()
            if j.get("status")==402:
                print("  402撞到600上限，存檔等下一小時再跑")
                return "LIMIT"
            return pd.DataFrame(j.get("data",[]))
        except: time.sleep(5)
    return pd.DataFrame()

# --- 主流程 ---
df_old = pd.read_parquet(PATH)
df_old["date"] = pd.to_datetime(df_old["date"])

df_otc = fetch_tpex_openapi()
print(f"TPEX OpenAPI 抓到 {len(df_otc)} 筆")

if len(df_otc) < 500 and TOKEN: # OpenAPI 失敗，改 FinMind 慢速
    print("OpenAPI 失敗，改 FinMind 一檔一檔補今天")
    today_str = datetime.now().strftime("%Y-%m-%d")
    # 拿上櫃清單
    r = get_with_retry("https://api.finmindtrade.com/api/v4/data",
                       params={"dataset":"TaiwanStockInfo"},
                       headers={"Authorization": f"Bearer {TOKEN}"})
    df_info = pd.DataFrame(r.json()["data"])
    col = "type" if "type" in df_info.columns else "stock_type"
    otc_list = [c for c in df_info[df_info[col].isin(["上櫃","otc"])]["stock_id"].tolist() if len(c)==4 and c.isdigit()]

    # 續跑進度
    done = []
    if os.path.exists(PROGRESS):
        try: done = json.load(open(PROGRESS))
        except: pass
    todo = [s for s in otc_list if s not in done]

    rows=[]
    for i,sid in enumerate(todo):
        if i>=550: # 一小時最多550，留安全量
            print(f"已跑550檔，先存檔，下次 Action 再續跑")
            break
        df = fetch_finmind_onestock(sid, today_str)
        if df=="LIMIT": break
        if not df.empty:
            rows.append({"stock_id":sid,"date":today_str,"close":float(df.iloc[0]["close"])})
            done.append(sid)
        print(f"{i+1}/{len(todo)} {sid} {'OK' if not df.empty else '無'}")
        time.sleep(7)

    json.dump(done, open(PROGRESS,"w"))
    if rows:
        df_otc = pd.DataFrame(rows)
        df_otc["date"] = pd.to_datetime(df_otc["date"])
else:
    # 成功就清掉進度檔
    if os.path.exists(PROGRESS): os.remove(PROGRESS)

print(f"最終 OTC {len(df_otc)} 筆")
# 剩下上市照舊... (你原本上市那段留著)
# 然後合併 df_old + df_otc + df_tse 再存 parquet
