from pathlib import Path
import json, math
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "api"
IMPORTS = ROOT / "data" / "imports"
UNIVERSE = ROOT / "backend" / "config" / "universe.csv"
CRITERIA = ("market_cap", "trend", "long_trend", "relative_volume",
            "revenue_growth", "debt_equity", "operating_cashflow")

def num(value):
    try:
        if value is None or pd.isna(value): return None
        value = float(value)
        return round(value, 4) if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None

def read_import(name):
    path = IMPORTS / name
    if not path.exists(): return []
    try:
        return pd.read_csv(path).fillna("").to_dict(orient="records")
    except Exception as exc:
        print(f"Could not read {path}: {exc}")
        return []

def evaluate_checks(values):
    states = {k: ("unknown" if values.get(k) is None else
                  ("pass" if bool(values[k]) else "fail")) for k in CRITERIA}
    passed = sum(v == "pass" for v in states.values())
    failed = [k for k,v in states.items() if v == "fail"]
    unknown = [k for k,v in states.items() if v == "unknown"]
    # Missing data receives no points and can never be counted as a pass.
    score = round(passed / len(CRITERIA) * 100)
    critical = {"market_cap", "trend", "long_trend"}.intersection(failed)
    quality = "Pass" if not failed and not unknown else ("Fail" if critical else "Review")
    return {
        "quality_score": score, "quality": quality, "checks": states,
        "failed_filters": failed, "unknown_filters": unknown,
        "passed_filters": [k for k,v in states.items() if v == "pass"],
        "evaluated_filters": len(CRITERIA)-len(unknown),
        "total_filters": len(CRITERIA),
        "data_coverage": round((len(CRITERIA)-len(unknown))/len(CRITERIA)*100)
    }

def analyse(row):
    ticker = row["ticker"]
    result = {"ticker": ticker, "company": row.get("company", ticker),
              "market": row.get("market", "")}
    try:
        instrument = yf.Ticker(ticker)
        hist = instrument.history(period="1y", interval="1d", auto_adjust=True)
        info = instrument.info or {}
        if hist.empty or "Close" not in hist: raise ValueError("No price history returned")
        close = hist["Close"].dropna()
        high, low, volume = hist["High"], hist["Low"], hist["Volume"]
        if len(close) < 2: raise ValueError("Insufficient price history")
        last = float(close.iloc[-1])
        ema10 = close.ewm(span=10, adjust=False).mean().iloc[-1]
        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        avgvol = num(volume.tail(50).mean())
        relvol = float(volume.iloc[-1])/avgvol if avgvol and avgvol > 0 else None
        perf20 = (last/float(close.iloc[-21])-1)*100 if len(close)>21 else None
        perf63 = (last/float(close.iloc[-64])-1)*100 if len(close)>64 else None
        adr20 = num((((high-low)/close).tail(20)).mean()*100)
        mcap = info.get("marketCap")
        rev_growth = info.get("revenueGrowth")
        debt_equity = info.get("debtToEquity")
        op_cash = info.get("operatingCashflow")

        checks = {
            "market_cap": None if mcap is None else mcap >= 1_000_000_000,
            "trend": None if len(close)<50 else (last > ema10 > ema21 and last > float(sma50.iloc[-1])),
            "long_trend": None if len(close)<200 else (last > float(sma200.iloc[-1])),
            "relative_volume": None if relvol is None else relvol >= 1.0,
            "revenue_growth": None if rev_growth is None else rev_growth > 0,
            "debt_equity": None if debt_equity is None else debt_equity <= 200,
            "operating_cashflow": None if op_cash is None else op_cash > 0,
        }
        result.update({
            "price": num(last), "currency": info.get("currency", ""),
            "market_cap": mcap,
            "market_cap_label": f"${mcap/1e9:.1f}B" if mcap else "n/a",
            "sector": info.get("sector", "Unknown"),
            "perf_20d": num(perf20), "perf_3m": num(perf63), "adr20": adr20,
            "ema10": num(ema10), "ema21": num(ema21),
            "sma50": num(sma50.iloc[-1]), "sma200": num(sma200.iloc[-1]),
            "rel_volume": num(relvol), "as_of": str(hist.index[-1].date()),
            "status": "ok", **evaluate_checks(checks)
        })
    except Exception as exc:
        result.update({
            "status": "error", "error": str(exc), "quality_score": 0,
            "quality": "Unavailable", "checks": {k:"unknown" for k in CRITERIA},
            "failed_filters": [], "unknown_filters": list(CRITERIA),
            "passed_filters": [], "evaluated_filters": 0,
            "total_filters": len(CRITERIA), "data_coverage": 0
        })
    return result

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    universe = pd.read_csv(UNIVERSE).fillna("")
    stocks = [analyse(row) for row in universe.to_dict(orient="records")]
    stocks.sort(key=lambda x: (x.get("quality_score",0), x.get("perf_3m") or -999), reverse=True)
    priced = [s for s in stocks if s.get("status") == "ok"]
    passes = [s for s in priced if s.get("quality") == "Pass"]
    summary = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(stocks), "priced": len(priced), "quality_count": len(passes),
        "avg_quality_score": round(sum(s.get("quality_score",0) for s in priced)/len(priced)) if priced else 0
    }
    (OUT/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT/"stocks.json").write_text(json.dumps({**summary,"stocks":stocks}, indent=2), encoding="utf-8")
    (OUT/"social.json").write_text(json.dumps({"window":"24h","items":read_import("social.csv"),"mode":"csv_import"}, indent=2), encoding="utf-8")
    (OUT/"politics.json").write_text(json.dumps({"items":read_import("politics.csv"),"mode":"csv_import"}, indent=2), encoding="utf-8")
    (OUT/"fact-checks.json").write_text(json.dumps({"items":read_import("fact_checks.csv")}, indent=2), encoding="utf-8")
    print(f"Published {len(stocks)} tickers; {len(passes)} strict quality passes.")

if __name__ == "__main__":
    main()
