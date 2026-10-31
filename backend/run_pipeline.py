from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_FILE = ROOT / "backend" / "config" / "universe.csv"
WEIGHTS_FILE = ROOT / "backend" / "config" / "quality_weights.json"
IMPORT_DIR = ROOT / "data" / "imports"
OUTPUT_DIR = ROOT / "public" / "api"

LOG = logging.getLogger("stock_intelligence")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# These dimensions are deliberately kept separate from price momentum and news attention.
QUALITY_WEIGHTS = {
    "revenue_growth": 15,
    "profitability": 15,
    "financial_stability": 15,
    "cashflow": 10,
    "market_position": 15,
    "growth_potential": 20,
    "management": 10,
}

def safe_number(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        number = float(value)
        return round(number, 4) if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None

def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value

def read_csv_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        frame = pd.read_csv(path, dtype=str).fillna("")
        return frame.to_dict(orient="records")
    except Exception as exc:
        LOG.warning("CSV konnte nicht gelesen werden (%s): %s", path.name, exc)
        return []

def load_universe() -> list[dict[str, str]]:
    if not UNIVERSE_FILE.exists():
        raise FileNotFoundError(f"Universum fehlt: {UNIVERSE_FILE}")
    frame = pd.read_csv(UNIVERSE_FILE, dtype=str).fillna("")
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    required = {"ticker", "company", "market"}
    if not required.issubset(frame.columns):
        raise ValueError(
            "universe.csv benötigt exakt die Spalten ticker,company,market. "
            f"Gefunden: {list(frame.columns)}"
        )
    frame = frame[["ticker", "company", "market"]]
    frame["ticker"] = frame["ticker"].str.strip()
    frame["company"] = frame["company"].str.strip()
    frame["market"] = frame["market"].str.strip()
    frame = frame[frame["ticker"] != ""].drop_duplicates(subset=["ticker"], keep="first")
    if frame.empty:
        raise ValueError("universe.csv enthält keine Ticker.")
    return frame.to_dict(orient="records")

def load_weights() -> dict[str, float]:
    if WEIGHTS_FILE.exists():
        try:
            raw = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
            weights = {k: float(v) for k, v in raw.items() if k in QUALITY_WEIGHTS}
            if set(weights) == set(QUALITY_WEIGHTS) and abs(sum(weights.values()) - 100) < 0.01:
                return weights
            LOG.warning("Quality-Gewichte ungültig; Standardgewichte werden verwendet.")
        except Exception as exc:
            LOG.warning("Quality-Gewichte nicht lesbar: %s", exc)
    return QUALITY_WEIGHTS.copy()

def score_range(value: float | None, good: float, bad: float, higher_is_better: bool = True) -> float | None:
    if value is None:
        return None
    if higher_is_better:
        if value >= good:
            return 100.0
        if value <= bad:
            return 0.0
        return (value - bad) / (good - bad) * 100.0
    if value <= good:
        return 100.0
    if value >= bad:
        return 0.0
    return (bad - value) / (bad - good) * 100.0

def evaluate_quality(info: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    """Score only dimensions for which source data exists; missing data is not a failure."""
    revenue_growth = safe_number(info.get("revenueGrowth"))
    operating_margin = safe_number(info.get("operatingMargins"))
    debt_equity = safe_number(info.get("debtToEquity"))
    operating_cashflow = safe_number(info.get("operatingCashflow"))
    earnings_growth = safe_number(info.get("earningsGrowth"))

    dimensions: dict[str, dict[str, Any]] = {
        "revenue_growth": {
            "value": revenue_growth,
            "unit": "ratio",
            "score": score_range(revenue_growth, 0.15, -0.05),
            "source_field": "revenueGrowth",
        },
        "profitability": {
            "value": operating_margin,
            "unit": "ratio",
            "score": score_range(operating_margin, 0.20, 0.0),
            "source_field": "operatingMargins",
        },
        "financial_stability": {
            "value": debt_equity,
            "unit": "ratio",
            "score": score_range(debt_equity, 50.0, 250.0, higher_is_better=False),
            "source_field": "debtToEquity",
            "note": "Vereinfachter Verschuldungsindikator; branchenabhängig.",
        },
        "cashflow": {
            "value": operating_cashflow,
            "unit": "currency",
            "score": (100.0 if operating_cashflow > 0 else 0.0) if operating_cashflow is not None else None,
            "source_field": "operatingCashflow",
        },
        # These two dimensions require peer/longitudinal or qualitative data not reliably
        # supplied by the basic Yahoo Finance quote endpoint. They remain unknown for now.
        "market_position": {
            "value": None, "unit": "score", "score": None,
            "source_field": None, "note": "Benötigt Branchen- und Wettbewerbsvergleich.",
        },
        "growth_potential": {
            "value": earnings_growth,
            "unit": "ratio",
            "score": score_range(earnings_growth, 0.20, -0.10),
            "source_field": "earningsGrowth",
        },
        "management": {
            "value": None, "unit": "score", "score": None,
            "source_field": None, "note": "Benötigt qualitative Management-/Kapitalallokationsdaten.",
        },
    }

    weighted_points = 0.0
    available_weight = 0.0
    passed: list[str] = []
    failed: list[str] = []
    unknown: list[str] = []

    for key, item in dimensions.items():
        score = item["score"]
        if score is None:
            unknown.append(key)
            continue
        weight = weights[key]
        available_weight += weight
        weighted_points += float(score) * weight
        if score >= 60:
            passed.append(key)
        else:
            failed.append(key)

    coverage = round(available_weight, 1)
    score = round(weighted_points / available_weight) if available_weight else 0
    # A "Pass" requires a good score and at least 60% of the total model weight observed.
    if coverage < 60:
        label = "Unavailable"
    elif failed or unknown:
        label = "Review"
    elif score >= 70:
        label = "Pass"
    else:
        label = "Fail"

    return {
        "quality_score": score,
        "quality": label,
        "quality_coverage": coverage,
        "quality_dimensions": dimensions,
        "passed_filters": passed,
        "failed_filters": failed,
        "unknown_filters": unknown,
    }

def analyse_stock(row: dict[str, str], weights: dict[str, float]) -> dict[str, Any]:
    ticker = row["ticker"]
    result: dict[str, Any] = {
        "ticker": ticker,
        "company": row["company"],
        "market": row["market"],
        "status": "pending",
    }
    try:
        instrument = yf.Ticker(ticker)
        history = instrument.history(period="1y", interval="1d", auto_adjust=True, actions=False)
        if history is None or history.empty:
            raise ValueError("Keine historischen Kursdaten verfügbar.")

        close = history["Close"].dropna()
        high = history["High"].reindex(close.index)
        low = history["Low"].reindex(close.index)
        volume = history["Volume"].reindex(close.index).fillna(0)
        if len(close) < 2:
            raise ValueError("Zu wenige Kursdaten.")

        last = float(close.iloc[-1])
        ema10 = close.ewm(span=10, adjust=False).mean().iloc[-1]
        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        avg_volume = volume.tail(50).mean()
        rel_volume = float(volume.iloc[-1] / avg_volume) if avg_volume and avg_volume > 0 else None
        perf20 = (last / float(close.iloc[-21]) - 1) * 100 if len(close) >= 21 else None
        perf63 = (last / float(close.iloc[-64]) - 1) * 100 if len(close) >= 64 else None
        adr20 = (((high - low) / close).replace([float("inf"), -float("inf")], pd.NA)).tail(20).mean() * 100

        info: dict[str, Any] = {}
        try:
            info = instrument.get_info() or {}
        except Exception as exc:
            LOG.warning("%s: Fundamentaldaten nicht verfügbar: %s", ticker, exc)

        quality = evaluate_quality(info, weights)
        currency = str(info.get("currency") or "")
        market_cap = safe_number(info.get("marketCap"))
        market_cap_label = "—"
        if market_cap is not None:
            # Yahoo marketCap is not guaranteed to use the listing currency. Do not add
            # a currency symbol unless the provider explicitly gives us the currency.
            suffix = "B" if market_cap >= 1e9 else "M"
            amount = market_cap / (1e9 if suffix == "B" else 1e6)
            market_cap_label = f"{amount:,.1f} {suffix}".replace(",", "X").replace(".", ",").replace("X", ".")
            if currency:
                market_cap_label += f" {currency}"

        trend_ok = bool(last > ema10 > ema21) if pd.notna(ema10) and pd.notna(ema21) else None
        long_trend_ok = bool(last > sma200) if pd.notna(sma200) else None

        result.update({
            "price": safe_number(last),
            "currency": currency,
            "market_cap": market_cap,
            "market_cap_label": market_cap_label,
            "sector": info.get("sector") or info.get("industry") or "—",
            "perf_20d": safe_number(perf20),
            "perf_3m": safe_number(perf63),
            "adr20": safe_number(adr20),
            "ema10": safe_number(ema10),
            "ema21": safe_number(ema21),
            "sma50": safe_number(sma50),
            "sma200": safe_number(sma200),
            "rel_volume": safe_number(rel_volume),
            "market_context": {
                "trend_short": trend_ok,
                "trend_long": long_trend_ok,
                "above_sma50": bool(last > sma50) if pd.notna(sma50) else None,
                "above_sma200": long_trend_ok,
            },
            "fundamentals": {
                "revenue_growth": safe_number(info.get("revenueGrowth")),
                "operating_margin": safe_number(info.get("operatingMargins")),
                "debt_to_equity": safe_number(info.get("debtToEquity")),
                "operating_cashflow": safe_number(info.get("operatingCashflow")),
                "earnings_growth": safe_number(info.get("earningsGrowth")),
                "free_cashflow": safe_number(info.get("freeCashflow")),
                "return_on_equity": safe_number(info.get("returnOnEquity")),
                "profit_margin": safe_number(info.get("profitMargins")),
            },
            **quality,
            "as_of": str(close.index[-1].date()),
            "status": "ok",
            "data_source": "Yahoo Finance",
        })
    except Exception as exc:
        LOG.exception("%s: Analyse fehlgeschlagen", ticker)
        result.update({
            "status": "error",
            "error": str(exc)[:300],
            "quality_score": 0,
            "quality": "Unavailable",
            "quality_coverage": 0,
            "passed_filters": [],
            "failed_filters": [],
            "unknown_filters": list(QUALITY_WEIGHTS.keys()),
            "market_context": {},
        })
    return json_safe(result)

def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        stamp = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(stamp):
            return None
        return stamp.to_pydatetime()
    except Exception:
        return None

def normalize_signal(row: dict[str, Any]) -> dict[str, Any] | None:
    ticker = str(row.get("ticker", "")).strip().upper()
    category = str(row.get("category") or row.get("source_category") or "").strip().lower()
    if not ticker or not category:
        return None
    published = str(row.get("published_at") or row.get("date") or "").strip()
    return {
        "ticker": ticker,
        "category": category,
        "source": str(row.get("source") or row.get("platform") or category),
        "headline": str(row.get("headline") or row.get("claim") or row.get("summary") or ""),
        "url": str(row.get("url") or row.get("source_url") or row.get("disclosure_url") or ""),
        "published_at": published,
        "source_id": str(row.get("source_id") or row.get("id") or ""),
        "is_primary": str(row.get("is_primary", "")).strip().lower() in {"1", "true", "yes", "ja"},
        "signal_type": str(row.get("signal_type") or ""),
        "quote": str(row.get("quote") or ""),
        "verification": str(row.get("verification") or "unverified"),
    }

def build_intelligence(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate supplied/imported signals; does not scrape or invent news/social data."""
    now = datetime.now(timezone.utc)
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    normalized = [s for row in signals if (s := normalize_signal(row))]
    for signal in normalized:
        by_ticker[signal["ticker"]].append(signal)

    radar = []
    for ticker, items in by_ticker.items():
        dated = [(parse_datetime(x["published_at"]), x) for x in items]
        dated = [(dt, x) for dt, x in dated if dt is not None]
        windows = {}
        for label, days in (("24h", 1), ("7d", 7), ("30d", 30)):
            current = [x for dt, x in dated if now - timedelta(days=days) <= dt <= now + timedelta(hours=1)]
            # Count unique source categories and source IDs, not raw duplicate rows.
            categories = sorted({x["category"] for x in current})
            source_ids = {x["source_id"] for x in current if x["source_id"]}
            windows[label] = {
                "signal_count": len({(x["category"], x["source_id"] or x["url"] or x["headline"]) for x in current}),
                "source_categories": categories,
                "category_count": len(categories),
                "signals": current,
            }
        radar.append({
            "ticker": ticker,
            "signals_24h": windows["24h"]["signal_count"],
            "sources_24h": windows["24h"]["category_count"],
            "signals_7d": windows["7d"]["signal_count"],
            "sources_7d": windows["7d"]["category_count"],
            "signals_30d": windows["30d"]["signal_count"],
            "sources_30d": windows["30d"]["category_count"],
            "windows": windows,
        })
    radar.sort(key=lambda x: (x["sources_24h"], x["signals_24h"], x["sources_7d"]), reverse=True)
    return {
        "updated_at": now.isoformat(),
        "mode": "csv_import",
        "items": normalized,
        "radar": radar,
        "note": "Nur importierte Signale. Keine automatische Live-Abdeckung externer Plattformen.",
    }

def publish_json(filename: str, payload: Any) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / filename
    target.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    universe = load_universe()
    weights = load_weights()
    LOG.info("Starte Analyse für %s eindeutige Aktien.", len(universe))

    stocks = []
    for index, row in enumerate(universe, start=1):
        LOG.info("[%s/%s] %s", index, len(universe), row["ticker"])
        stocks.append(analyse_stock(row, weights))

    stocks.sort(
        key=lambda x: (
            x.get("quality") == "Pass",
            x.get("quality_score", 0),
            x.get("perf_3m") if x.get("perf_3m") is not None else -999,
        ),
        reverse=True,
    )

    successful = [s for s in stocks if s.get("status") == "ok"]
    passes = [s for s in successful if s.get("quality") == "Pass"]
    reviews = [s for s in successful if s.get("quality") == "Review"]
    priced_count = sum(1 for s in successful if s.get("price") is not None)
    avg_score = round(sum(s["quality_score"] for s in successful) / len(successful)) if successful else 0

    summary = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(stocks),
        "priced": priced_count,
        "quality_count": len(passes),
        "review_count": len(reviews),
        "unavailable_count": len(stocks) - len(successful),
        "avg_quality_score": avg_score,
        "data_source": "Yahoo Finance",
        "quality_model": "Fundamental only; technical and intelligence signals excluded.",
    }
    publish_json("summary.json", summary)
    publish_json("stocks.json", {**summary, "stocks": stocks})

    social = read_csv_records(IMPORT_DIR / "social.csv")
    politics = read_csv_records(IMPORT_DIR / "politics.csv")
    facts = read_csv_records(IMPORT_DIR / "fact_checks.csv")
    generic_signals = read_csv_records(IMPORT_DIR / "signals.csv")

    # Convert the existing import files into the common signal format.
    combined_signals = list(generic_signals)
    for row in social:
        combined_signals.append({
            **row, "category": row.get("category") or "social",
            "source": row.get("source") or row.get("platform") or "social",
            "published_at": row.get("published_at") or row.get("date"),
            "headline": row.get("headline") or row.get("claim"),
            "url": row.get("url") or row.get("source_url"),
        })
    for row in politics:
        combined_signals.append({
            **row, "category": row.get("category") or "politics",
            "source": row.get("source") or "political_disclosure",
            "published_at": row.get("published_at") or row.get("date"),
            "headline": row.get("headline") or row.get("transaction"),
            "url": row.get("url") or row.get("disclosure_url"),
        })

    intelligence = build_intelligence(combined_signals)
    trump_mentions = [
        s for s in intelligence["items"]
        if s["category"] in {"trump", "trump_mention", "politics_trump"}
        or "trump" in s["signal_type"].lower()
    ]

    publish_json("social.json", {"updated_at": summary["updated_at"], "items": social, "mode": "csv_import"})
    publish_json("politics.json", {"updated_at": summary["updated_at"], "items": politics, "mode": "csv_import"})
    publish_json("fact-checks.json", {"updated_at": summary["updated_at"], "items": facts, "mode": "csv_import"})
    publish_json("intelligence.json", intelligence)
    publish_json("trump-mentions.json", {
        "updated_at": summary["updated_at"],
        "mode": "csv_import",
        "items": trump_mentions,
        "note": "Nur verifizierte/importierte Hinweise; keine automatische Erkennung von Trump-Aussagen.",
    })

    LOG.info(
        "Fertig: %s Aktien | %s Kurse | %s Quality Pass | %s Review | %s nicht verfügbar.",
        len(stocks), priced_count, len(passes), len(reviews), len(stocks) - len(successful)
    )

if __name__ == "__main__":
    main()
