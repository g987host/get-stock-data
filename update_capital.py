import re
import requests
import pandas as pd
from pathlib import Path

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
HEADERS = {
    "accept": "application/json",
    "If-Modified-Since": "Mon, 26 Jul 1997 05:00:00 GMT",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": "Mozilla/5.0"
}
FOUR_DIGIT = re.compile(r'^\d{4}$')

def fetch_json(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def to_yi_1(value) -> float:
    """ NTD -> 億元, 1位小數 """
    try:
        if value is None or str(value).strip() in ('', '-', '－'):
            return 0.0
        v = int(str(value).replace(',', '').strip())
        return round(v / 1e8, 1)
    except:
        return 0.0

def parse_twse(data):
    rows = []
    for d in data:
        code = str(d.get('公司代號','')).strip()
        if not FOUR_DIGIT.match(code):
            continue
        rows.append({
            '公司代號': code,
            '公司簡稱': d.get('公司簡稱','').strip(),
            '公司名稱': d.get('公司名稱','').strip(),
            '市場別': 'TWSE',
            '實收資本額_元': d.get('實收資本額',''),
            '資本額_億元': to_yi_1(d.get('實收資本額')),
            '出表日期': d.get('出表日期','')
        })
    return pd.DataFrame(rows)

def parse_tpex(data):
    rows = []
    for d in data:
        code = str(d.get('SecuritiesCompanyCode','')).strip()
        if not FOUR_DIGIT.match(code):
            continue
        rows.append({
            '公司代號': code,
            '公司簡稱': d.get('CompanyAbbreviation','').strip(),
            '公司名稱': d.get('CompanyName','').strip(),
            '市場別': 'TPEx',
            '實收資本額_元': d.get('Paidin.Capital.NTDollars',''),
            '資本額_億元': to_yi_1(d.get('Paidin.Capital.NTDollars')),
            '出表日期': d.get('Date','')
        })
    return pd.DataFrame(rows)

def main():
    print("Fetching TWSE...")
    twse_data = fetch_json(TWSE_URL)
    df_twse = parse_twse(twse_data)
    print(f"TWSE: {len(df_twse)} 家")

    print("Fetching TPEx...")
    tpex_data = fetch_json(TPEX_URL)
    df_tpex = parse_tpex(tpex_data)
    print(f"TPEx: {len(df_tpex)} 家")

    df = pd.concat([df_twse, df_tpex], ignore_index=True)
    df = df.drop_duplicates(subset=['公司代號']).sort_values('公司代號')
    
    # 只保留需要的欄位，符合你要求: 單位億元 1位小數
    df_final = df[['公司代號', '公司簡稱', '市場別', '資本額_億元', '實收資本額_元', '出表日期']]

    out_path = Path("data/Capital.parquet")
    # 如果舊檔存在，你想保留歷史就用這個邏輯，否則直接覆蓋
    df_final.to_parquet(out_path, index=False)
    print(f"已儲存 {out_path} 共 {len(df_final)} 筆")
    print(df_final.head(10).to_string(index=False))

if __name__ == "__main__":
    main()
