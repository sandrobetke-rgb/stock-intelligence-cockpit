from pathlib import Path
import json, math, sys
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "api"
IMPORTS = ROOT / "data" / "imports"
UNIVERSE = ROOT / "backend" / "config" / "universe.csv"

def num(x):
    try:
        if x is None or pd.isna(x): return None
        x = float(x)
        return round(x, 4) if math.isfinite(x) else None
    except Exception: return None

def read_import(name):
    p = IMPORTS / name
    if not p.exists(): return []
    try:
        df = pd.read_csv(p).fillna("")
        return df.to_dict(orient="records")
    except Exception as e:
        print(f"Could not read {p}: {e}")
        return []

def analyse(row):
    ticker, company, market = row["ticker"], row["company"], row["market"]
    result = {"ticker": ticker, "company": company, "market": market}
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1y", interval="1d", auto_adjust=True)
        info = t.info or {}
        if hist.empty: raise ValueError("No price history returned")
        close, high, low, vol = hist["Close"], hist["High"], hist["Low"], hist["Volume"]
        last = float(close.iloc[-1])
        ema10 = close.ewm(span=10).mean().iloc[-1]
        ema21 = close.ewm(span=21).mean().iloc[-1]
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        avgvol = vol.tail(50).mean()
        relvol = float(vol.iloc[-1] / avgvol) if avgvol and avgvol > 0 else None
        perf20 = (last / float(close.iloc[-21]) - 1) * 100 if len(close) > 21 else None
        perf63 = (last / float(close.iloc[-64]) - 1) * 100 if len(close) > 64 else None
        adr20 = ((high-low)/close).tail(20).mean()*100
        mcap = info.get("marketCap")
        rev_growth = info.get("revenueGrowth")
        debt_equity = info.get("debtToEquity")
        op_cash = info.get("operatingCashflow")
        checks = {
            "market_cap": bool(mcap and mcap >= 1_000_000_000),
            "trend": bool(last > ema10 > ema21 and (pd.isna(sma50) or ema21 > sma50)),
            "long_trend": bool(pd.isna(sma200) or last > sma200),
            "relative_volume": bool(relvol is not None and relvol >= 1.0),
            "revenue_growth": (rev_growth is None or rev_growth > 0),
            "debt_equity": (debt_equity is None or debt_equity <= 200),
            "operating_cashflow": (op_cash is None or op_cash > 0),
        }
        unknown = []
        if mcap is None: unknown.append("market_cap")
        if rev_growth is None: unknown.append("revenue_growth")
        if debt_equity is None: unknown.append("debt_equity")
        if op_cash is None: unknown.append("operating_cashflow")
        passed = sum(1 for v in checks.values() if v)
        score = round(passed / len(checks) * 100)
        failed = [k for k,v in checks.items() if not v]
        result.update({
            "price": num(last), "currency": info.get("currency", ""),
            "market_cap": mcap, "market_cap_label": (f"${mcap/1e9:.1f}B" if mcap else "n/a"),
            "sector": info.get("sector", "Unknown"),
            "perf_20d": num(perf20), "perf_3m": num(perf63), "adr20": num(adr20),
            "ema10": num(ema10), "ema21": num(ema21), "sma50": num(sma50), "sma200": num(sma200),
            "rel_volume": num(relvol), "quality_score": score,
            "quality": "Pass" if not failed and not unknown else ("Review" if score >= 60 else "Fail"),
            "checks": checks, "failed_filters": failed, "unknown_filters": unknown,
            "as_of": str(hist.index[-1].date()), "status": "ok"
        })
    except Exception as e:
        result.update({"status":"error", "error":str(e), "quality_score":0, "quality":"Unavailable",
                       "failed_filters":["price_data"], "unknown_filters":[]})
    return result

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    universe = pd.read_csv(UNIVERSE).fillna("")
    stocks = [analyse(r) for r in universe.to_dict(orient="records")]
    stocks.sort(key=lambda x: (x.get("quality_score",0), x.get("perf_3m") or -999), reverse=True)
    ok = [s for s in stocks if s.get("status") == "ok"]
    quality = [s for s in ok if s.get("quality") == "Pass"]
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(stocks), "priced": len(ok), "quality_count": len(quality),
        "avg_quality_score": round(sum(s.get("quality_score",0) for s in ok)/len(ok)) if ok else 0,
        "stocks": stocks
    }
    (OUT/"summary.json").write_text(json.dumps({k:v for k,v in payload.items() if k!="stocks"}, indent=2))
    (OUT/"stocks.json").write_text(json.dumps(payload, indent=2))
    (OUT/"social.json").write_text(json.dumps({"window":"24h","items":read_import("social.csv"),"mode":"csv_import"}, indent=2))
    (OUT/"politics.json").write_text(json.dumps({"items":read_import("politics.csv"),"mode":"csv_import"}, indent=2))
    (OUT/"fact-checks.json").write_text(json.dumps({"items":read_import("fact_checks.csv")}, indent=2))
    print(f"Published {len(stocks)} tickers; {len(quality)} strict passes.")

if __name__ == "__main__":
    main()
