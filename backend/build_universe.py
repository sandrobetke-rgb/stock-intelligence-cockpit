from __future__ import annotations
import io, re, sys
from pathlib import Path
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "config" / "universe.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 StockIntelligenceCockpit/1.0"}

SOURCES = {
    "NASDAQ100": "https://raw.githubusercontent.com/Gary-Strauss/nasdaq100-scraper/master/data/nasdaq100_constituents.csv",
    "SP500": "https://dataset.aethereal.top/files/sp500-companies.csv",
    # Current iShares/IWM holdings-derived constituent CSV. Provider may change its schema.
    "RUSSELL2000": "https://equibles.com/indexes/russell-2000.csv",
}

DAX = [
("ADS.DE","adidas"),("AIR.DE","Airbus"),("ALV.DE","Allianz"),("BAS.DE","BASF"),
("BAYN.DE","Bayer"),("BEI.DE","Beiersdorf"),("BMW.DE","BMW"),("BNR.DE","Brenntag"),
("CBK.DE","Commerzbank"),("CON.DE","Continental"),("DTG.DE","Daimler Truck"),("DBK.DE","Deutsche Bank"),
("DB1.DE","Deutsche Boerse"),("DTE.DE","Deutsche Telekom"),("DHL.DE","DHL Group"),("EOAN.DE","E.ON"),
("FRE.DE","Fresenius"),("FME.DE","Fresenius Medical Care"),("G1A.DE","GEA Group"),("HNR1.DE","Hannover Rueck"),
("HEI.DE","Heidelberg Materials"),("HEN3.DE","Henkel"),("HOT.DE","HOCHTIEF"),("IFX.DE","Infineon"),
("MBG.DE","Mercedes-Benz Group"),("MRK.DE","Merck KGaA"),("MTX.DE","MTU Aero Engines"),("MUV2.DE","Munich Re"),
("QIA.DE","QIAGEN"),("RHM.DE","Rheinmetall"),("RWE.DE","RWE"),("SAP.DE","SAP"),
("G24.DE","Scout24"),("SIE.DE","Siemens"),("ENR.DE","Siemens Energy"),("SHL.DE","Siemens Healthineers"),
("SY1.DE","Symrise"),("VOW3.DE","Volkswagen Pref"),("VNA.DE","Vonovia"),("ZAL.DE","Zalando")
]

def download_csv(url: str) -> pd.DataFrame:
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    return pd.read_csv(io.BytesIO(r.content), dtype=str).fillna("")

def find_col(df, candidates):
    lookup = {str(c).strip().lower().replace("_"," ").replace("-"," "): c for c in df.columns}
    for candidate in candidates:
        key = candidate.lower().replace("_"," ").replace("-"," ")
        if key in lookup: return lookup[key]
    for key, original in lookup.items():
        if any(c.lower() in key for c in candidates): return original
    return None

def normalize_symbol(value):
    s = str(value or "").strip().upper()
    if not s or s in {"N/A","NA","NONE","CASH","XTSLA"}: return ""
    s = s.replace(".", "-")
    # Skip non-common-stock fund/cash instruments and malformed symbols.
    if not re.fullmatch(r"[A-Z0-9-]{1,12}", s): return ""
    return s

def extract(df, index_name):
    ticker_col = find_col(df, ["ticker","symbol","stock ticker","holding ticker"])
    name_col = find_col(df, ["company","name","security","issuer","holding name"])
    if ticker_col is None:
        raise ValueError(f"{index_name}: keine Ticker-Spalte in {list(df.columns)}")
    result=[]
    for _, row in df.iterrows():
        ticker=normalize_symbol(row.get(ticker_col))
        if not ticker: continue
        name=str(row.get(name_col) or ticker).strip() if name_col else ticker
        result.append((ticker,name,index_name))
    return result

def main():
    records={}
    errors=[]
    for index_name, url in SOURCES.items():
        try:
            rows=extract(download_csv(url), index_name)
            if len(rows) < (70 if index_name=="NASDAQ100" else 300):
                raise ValueError(f"unerwartet wenige Datensätze: {len(rows)}")
            for ticker,name,idx in rows:
                rec=records.setdefault(ticker, {"company":name,"market":"USA","indices":set()})
                if not rec["company"] or rec["company"]==ticker: rec["company"]=name
                rec["indices"].add(idx)
            print(f"{index_name}: {len(rows)} Zeilen übernommen")
        except Exception as exc:
            errors.append(f"{index_name}: {exc}")
            print(f"WARNUNG {index_name}: {exc}")
    for ticker,name in DAX:
        rec=records.setdefault(ticker, {"company":name,"market":"Europe","indices":set()})
        rec["company"]=name
        rec["market"]="Europe"
        rec["indices"].add("DAX")
    # Preserve prior 18-stock list if a feed fails; do not silently produce an empty or tiny universe.
    fallback=[
    ("AAPL","Apple","USA"),("MSFT","Microsoft","USA"),("NVDA","NVIDIA","USA"),("MU","Micron Technology","USA"),
    ("AMD","Advanced Micro Devices","USA"),("AMZN","Amazon","USA"),("META","Meta Platforms","USA"),("GOOGL","Alphabet","USA"),
    ("AVGO","Broadcom","USA"),("PLTR","Palantir","USA"),("APP","AppLovin","USA"),("CRWD","CrowdStrike","USA"),
    ("ANET","Arista Networks","USA"),("LLY","Eli Lilly","USA"),("NVO","Novo Nordisk","USA")]
    for t,n,m in fallback:
        records.setdefault(t, {"company":n,"market":m,"indices":set()})
    if len(records)<500:
        raise RuntimeError(f"Abbruch: nur {len(records)} eindeutige Aktien. Keine unvollständige Datei wird geschrieben. " + "; ".join(errors))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df=pd.DataFrame([
        {"ticker":t,"company":v["company"],"market":v["market"],"indices":";".join(sorted(v["indices"]))}
        for t,v in sorted(records.items())
    ])
    df.to_csv(OUT,index=False,encoding="utf-8-sig")
    print(f"Fertig: {len(df)} eindeutige Aktien -> {OUT}")
    if errors: print("Quellenhinweise: " + "; ".join(errors))

if __name__=="__main__":
    main()
