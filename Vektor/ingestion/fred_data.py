import os
import requests
from datetime import datetime, timedelta

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

SERIES = {
    "CPIAUCSL":   ("CPI — Consumer Price Index",          "inflation"),
    "FEDFUNDS":   ("Federal Funds Rate",                  "interest rates"),
    "UNRATE":     ("Unemployment Rate",                   "labor market"),
    "DGS10":      ("10-Year Treasury Yield",              "bonds"),
    "T10YIE":     ("10-Year Breakeven Inflation Rate",    "inflation expectations"),
    "UMCSENT":    ("Consumer Sentiment (Univ. Michigan)", "consumer sentiment"),
    "DCOILWTICO": ("WTI Crude Oil Price",                 "commodities"),
    "M2SL":       ("M2 Money Supply",                     "monetary policy"),
}


def fetch_fred_data() -> list:
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        print("FRED_API_KEY not set — skipping FRED data")
        return []

    chunks = []
    today = datetime.now().strftime("%Y-%m-%d")
    since = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

    for series_id, (name, category) in SERIES.items():
        try:
            resp = requests.get(BASE_URL, params={
                "series_id":         series_id,
                "api_key":           api_key,
                "file_type":         "json",
                "observation_start": since,
                "sort_order":        "desc",
                "limit":             5,
            }, timeout=10)
            obs = [o for o in resp.json().get("observations", []) if o["value"] != "."]
            if not obs:
                continue

            latest = obs[0]
            change = ""
            if len(obs) > 1 and obs[1]["value"] != ".":
                delta = float(latest["value"]) - float(obs[1]["value"])
                direction = "up" if delta > 0 else "down"
                change = f" ({direction} {abs(delta):.3f} from {obs[1]['date']})"

            trend = ", ".join(f"{o['date']}: {o['value']}" for o in obs[:4])

            text = (
                f"FRED Economic Indicator — {name} ({series_id}):\n"
                f"Latest: {latest['value']} as of {latest['date']}{change}\n"
                f"Category: {category}\n"
                f"Recent: {trend}"
            )

            chunks.append({
                "text":       text,
                "source":     "FRED",
                "source_url": f"fred_{series_id}_{today}",
                "asset":      "general",
            })
        except Exception as e:
            print(f"FRED error [{series_id}]: {e}")

    print(f"FRED: fetched {len(chunks)} indicators")
    return chunks
