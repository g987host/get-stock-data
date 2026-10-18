import requests, pandas as pd, io, re, os
from datetime import datetime
from requests.exceptions import TooManyRedirects

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/csv,*/*",
    "Referer": "https://www.tdcc.com.tw/",
}

# 1~15 級的對照，用來算張數
LEVEL_MAP = {
    1: (1, 999),
    2: (1000, 5000),
    3: (5001, 10000),
    4: (10001, 15000),
    5: (15001, 20000),
    6: (20001, 30000),
    7: (30001, 40000),
    8: (40001, 50000),
    9: (50001, 100000), # <=100張
    10: (100001, 200000),
    11: (200001, 400000),
    12: (400001, 600000),
    13: (600001, 800000),
    14: (800001, 1000000),
    15: (1000001, 999999999), # >=1000張
}

def get_valid_4digit_codes():
    """抓上市+上櫃普通股，拿來過濾ETF/DR/興櫃"""
    codes = set()
    twse_count, tpex_count = 0, 0

    # 1. 上市 - TWSE官方
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", timeout=15, headers=HEADERS).json()
        for row in r:
            c = str(row.get("公司代號") or "").strip()
            if re.match(r'^\d{4}$', c):
                codes.add(c)
        twse_count = len([c for c in codes])
        print(f"TWSE上市抓到 {twse_count} 檔")
    except Exception as e:
        print(f"TWSE上市失敗: {e}")

    # 2. 上櫃 - TPEX官方，試兩個網址
    for url in [
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03",
    ]:
        try:
            r = requests.get(url, timeout=15, headers=HEADERS).json()
            cnt_before = len(codes)
            for row in r:
                c = str(row.get("CompanyCode") or row.get("公司代號") or row.get("SecuritiesCompanyCode") or "").strip()
                if re.match(r'^\d{4}$', c):
                    codes.add(c)
            if len(codes) > cnt_before:
                print(f"TPEX上櫃從 {url} 抓到 {len(codes)-cnt_before} 檔")
                tpex_count = len(codes) - cnt_before
                break
        except Exception as e:
            print(f"TPEX {url} 失敗: {e}")
            continue

    # 3. 備援 - ISIN清單，最穩，一定有上櫃
    # strMode=2 上市, 4 上櫃
    def fetch_isin(mode):
        try:
            url = f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
            resp = requests.get(url, headers=HEADERS, timeout=15)
            text = resp.content.decode('big5', errors='ignore')
            # 抓 <td>1101</td> 這種
            found = set(re.findall(r'<td[^>]*>\s*(\d{4})\s*</td>', text))
            print(f"ISIN mode={mode} 抓到 {len(found)} 檔")
            return found
        except Exception as e:
            print(f"ISIN mode={mode} 失敗 {e}")
            return set()

    if len(codes) < 1500: # 少於1500代表上櫃沒抓到，啟用備援
        print("啟用ISIN備援...")
        codes |= fetch_isin(2) # 上市
        codes |= fetch_isin(4) # 上櫃

    print(f"最終有效上市櫃普通股: {len(codes)} 檔")
    return codes

def fetch_tdcc():
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        sess.get("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", timeout=10)
    except: pass

    urls = [
        "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
        "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5",
        "http://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
    ]
    for url in urls:
        try:
            print(f"抓: {url}")
            resp = sess.get(url, timeout=30)
            if resp.status_code!= 200 or len(resp.content) < 1000:
                continue
            try:
                df = pd.read_csv(io.BytesIO(resp.content), encoding="big5")
            except:
                df = pd.read_csv(io.BytesIO(resp.content), encoding="utf-8")
            if "證券代號" in "".join(map(str, df.columns)):
                return df
        except TooManyRedirects:
            continue
        except Exception as e:
            print(e)
            continue
    raise RuntimeError("TDCC抓取失敗")

def main():
    raw = fetch_tdcc()
    raw.columns = raw.columns.str.strip()
    raw = raw.rename(columns={
        "資料日期": "tdcc_date",
        "證券代號": "stock_id",
        "持股分級": "level",
        "人數": "holders",
        "股數": "shares",
        "占集保庫存數比例%": "pct",
        "占集保庫存數比例": "pct"
    })

    # --- 修正日期解析 ---
    def parse_tdcc_date(v):
        s = str(v).strip()
        try:
            # 114/05/16 或 2025/05/16 這種
            if "/" in s or "-" in s:
                return pd.to_datetime(s).date()
            digits = re.sub(r"\D", "", s)
            if len(digits) == 7: # 1140516 = 民國年
                y = int(digits[:3]) + 1911
                m = int(digits[3:5])
                d = int(digits[5:7])
                return datetime(y, m, d).date()
            if len(digits) == 8: # 20250516
                y = int(digits[:4])
                m = int(digits[4:6])
                d = int(digits[6:8])
                return datetime(y, m, d).date()
        except:
            pass
        return datetime.now().date()

    raw["stock_id"] = raw["stock_id"].astype(str).str.strip()
    raw["level"] = pd.to_numeric(raw["level"], errors="coerce")
    raw["pct"] = pd.to_numeric(raw["pct"], errors="coerce").fillna(0)
    raw = raw[raw["stock_id"].str.match(r'^\d{4}$', na=False)]
    raw = raw[raw["level"] <= 15]

    valid = get_valid_4digit_codes()
    if valid and len(valid) > 1000:
        raw = raw[raw["stock_id"].isin(valid)]
    raw = raw[~raw["stock_id"].str.startswith("00")]
    raw = raw[~raw["stock_id"].str.startswith("91")]
    raw = raw[~raw["stock_id"].str.startswith("92")]

    # 抓正確的資料日期
    snapshot_date = parse_tdcc_date(raw["tdcc_date"].iloc[0])
    print(f"本次資料日期: {snapshot_date} 共有 {raw['stock_id'].nunique()} 檔")

    result = []
    for sid, g in raw.groupby("stock_id"):
        under_100 = g[g["level"].between(1, 9)]["pct"].sum()
        over_400 = g[g["level"].between(10, 15)]["pct"].sum()
        over_1000 = g[g["level"] == 15]["pct"].sum()
        result.append({
            "stock_id": sid,
            "tdcc_date": snapshot_date,
            "pct_under_100": round(float(under_100), 4),
            "pct_over_400": round(float(over_400), 4),
            "pct_over_1000": round(float(over_1000), 4),
            "total_holders": int(g["holders"].sum()) if "holders" in g.columns else 0
        })

    new_df = pd.DataFrame(result)

    # 只留2週
    two_weeks_path = f"{DATA_DIR}/tdcc_2weeks.parquet"
    if os.path.exists(two_weeks_path):
        old = pd.read_parquet(two_weeks_path)
        old["tdcc_date"] = pd.to_datetime(old["tdcc_date"]).dt.date
        combined = pd.concat([old, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["stock_id", "tdcc_date"], keep="last")
    else:
        combined = new_df

    dates = sorted(combined["tdcc_date"].unique(), reverse=True)[:2]
    combined = combined[combined["tdcc_date"].isin(dates)]
    combined.to_parquet(two_weeks_path, index=False)

    latest = combined[combined["tdcc_date"] == dates[0]]
    latest.to_csv(f"{DATA_DIR}/tdcc_latest.csv", index=False, encoding="utf-8-sig")
    latest.to_parquet(f"{DATA_DIR}/tdcc_latest.parquet", index=False)

    print(f"已保留2週: {dates} 共 {len(combined)} 筆")

if __name__ == "__main__":
    main()