"""
Vektor Seeder — One-time historical trade backfill.

Pulls 2 years of daily OHLCV + technicals for each asset,
samples every N days, runs all 3 AI personas via Groq,
computes consensus + 5-day outcome, and inserts closed trades
into Supabase so the dashboard has meaningful data from day one.

Usage:
    pip install -r requirements.txt
    python seeder.py

Env vars required (same as the live trader):
    SUPABASE_URL
    SUPABASE_KEY
    GROQ_API_KEY
"""

import os
import sys
import json
import time

import yfinance as yf
import pandas as pd
import ta
from dotenv import load_dotenv
from groq import Groq
from supabase import create_client

load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────────────────────

WATCHLIST = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "AMD"]

SYMBOL_MAP = {
    "SPY": "SPY", "QQQ": "QQQ", "NVDA": "NVDA",
    "TSLA": "TSLA", "AAPL": "AAPL", "AMD": "AMD",
}

LOOKBACK_YEARS   = 2
SAMPLE_EVERY_N   = 5   # every 5 trading days (~weekly)
MAX_PER_TICKER   = 40
OUTCOME_DAYS     = 5   # evaluate outcome N trading days after signal
MODEL            = "llama-3.1-8b-instant"

# ── PERSONA PROMPTS ───────────────────────────────────────────────────────────

PERSONAS = {
    "taleb": (
        "You are a trader inspired by Nassim Taleb's philosophy. "
        "You focus on asymmetric risk, tail events, and antifragility. "
        "You take decisive positions when risk/reward is clearly asymmetric — small downside, large upside. "
        "You always set a specific stop loss and take profit when you BUY or SELL."
    ),
    "saliba": (
        "You are a trader inspired by Anthony Saliba's options philosophy. "
        "You focus on volatility, momentum, and defined risk/reward setups. "
        "You act when RSI, MACD, trend, and sentiment align. "
        "You always set a specific stop loss (1-2% below entry) and take profit (2-4% above entry)."
    ),
    "druckenmiller": (
        "You are a trader inspired by Stanley Druckenmiller's macro philosophy. "
        "You look at the big picture first — rates, dollar, earnings cycle, liquidity. "
        "When macro regime supports a trade and technicals confirm, you bet with conviction. "
        "You always set a specific stop loss and take profit — sizing is everything."
    ),
}

PROMPT_TEMPLATE = """{persona_style}

You are analysing {symbol} on {date}. Based ONLY on the technical data below, make a trading decision.

Price: ${price}
RSI: {rsi}
MACD: {macd} (signal: {macd_signal})
Bollinger: low=${bb_low}, high=${bb_high}
SMA20: ${sma_20} | SMA50: ${sma_50}
ATR: {atr}
Above SMA20: {above_sma20} | Above SMA50: {above_sma50}

Respond in this EXACT format:
DECISION: [BUY/SELL/HOLD]
CONFIDENCE: [0.0-1.0]
STOP_LOSS: [price or N/A]
TAKE_PROFIT: [price or N/A]
REASONING: [1-2 sentences citing the technicals above]"""

# ── CLIENTS ───────────────────────────────────────────────────────────────────

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
groq     = Groq(api_key=os.environ["GROQ_API_KEY"])


# ── DATA ──────────────────────────────────────────────────────────────────────

def fetch_history(ticker: str) -> pd.DataFrame:
    print(f"  Fetching {ticker}...")
    df = yf.download(ticker, period=f"{LOOKBACK_YEARS}y", interval="1d", progress=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df["rsi"]        = ta.momentum.RSIIndicator(df["Close"]).rsi()
    df["macd"]       = ta.trend.MACD(df["Close"]).macd()
    df["macd_signal"]= ta.trend.MACD(df["Close"]).macd_signal()
    df["bb_high"]    = ta.volatility.BollingerBands(df["Close"]).bollinger_hband()
    df["bb_low"]     = ta.volatility.BollingerBands(df["Close"]).bollinger_lband()
    df["sma_20"]     = ta.trend.SMAIndicator(df["Close"], window=20).sma_indicator()
    df["sma_50"]     = ta.trend.SMAIndicator(df["Close"], window=50).sma_indicator()
    df["atr"]        = ta.volatility.AverageTrueRange(df["High"], df["Low"], df["Close"]).average_true_range()
    df.dropna(inplace=True)
    return df


def sample_days(df: pd.DataFrame) -> pd.DataFrame:
    sampled = df.iloc[::SAMPLE_EVERY_N].copy()
    if len(sampled) > MAX_PER_TICKER:
        sampled = sampled.tail(MAX_PER_TICKER)
    return sampled


# ── AI ────────────────────────────────────────────────────────────────────────

def ask_persona(name: str, style: str, symbol: str, row: pd.Series) -> dict:
    close = float(row["Close"])
    prompt = PROMPT_TEMPLATE.format(
        persona_style=style,
        symbol=symbol,
        date=str(row.name.date()),
        price=round(close, 2),
        rsi=round(float(row["rsi"]), 1),
        macd=round(float(row["macd"]), 4),
        macd_signal=round(float(row["macd_signal"]), 4),
        bb_high=round(float(row["bb_high"]), 2),
        bb_low=round(float(row["bb_low"]), 2),
        sma_20=round(float(row["sma_20"]), 2),
        sma_50=round(float(row["sma_50"]), 2),
        atr=round(float(row["atr"]), 4),
        above_sma20=close > float(row["sma_20"]),
        above_sma50=close > float(row["sma_50"]),
    )

    try:
        resp = groq.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.2,
        )
        return parse_response(resp.choices[0].message.content)
    except Exception as e:
        print(f"      Groq error ({name}): {e}")
        return {"decision": "HOLD", "confidence": 0.5, "stop_loss": None, "take_profit": None, "reasoning": "Error"}


def parse_response(text: str) -> dict:
    result = {"decision": "HOLD", "confidence": 0.5, "stop_loss": None, "take_profit": None, "reasoning": text.strip()}
    for line in text.strip().splitlines():
        if line.startswith("DECISION:"):
            d = line.replace("DECISION:", "").strip()
            if d in ("BUY", "SELL", "HOLD"):
                result["decision"] = d
        elif line.startswith("CONFIDENCE:"):
            try: result["confidence"] = float(line.replace("CONFIDENCE:", "").strip())
            except ValueError: pass
        elif line.startswith("STOP_LOSS:"):
            try: result["stop_loss"] = float(line.replace("STOP_LOSS:", "").strip())
            except ValueError: result["stop_loss"] = None
        elif line.startswith("TAKE_PROFIT:"):
            try: result["take_profit"] = float(line.replace("TAKE_PROFIT:", "").strip())
            except ValueError: result["take_profit"] = None
        elif line.startswith("REASONING:"):
            result["reasoning"] = line.replace("REASONING:", "").strip()
    return result


# ── CONSENSUS (mirrors trader/main.py) ───────────────────────────────────────

PERSONA_NAMES = list(PERSONAS.keys())

def consensus(results: list) -> dict:
    decisions = [r["decision"] for r in results]
    avg_conf  = round(sum(r["confidence"] for r in results) / len(results), 3)

    buys  = [r for r in results if r["decision"] == "BUY"]
    sells = [r for r in results if r["decision"] == "SELL"]
    holds = [r for r in results if r["decision"] == "HOLD"]

    def _actor(group):
        return max(group, key=lambda r: r["confidence"])

    def _reasoning(group):
        return " | ".join(
            f"{PERSONA_NAMES[results.index(r)].upper()}: {r['reasoning']}"
            for r in group
        )

    if len(set(decisions)) == 1:
        actor = _actor(results)
        return {"decision": decisions[0], "confidence": avg_conf,
                "reasoning": _reasoning(results),
                "stop_loss": actor.get("stop_loss"), "take_profit": actor.get("take_profit"),
                "signal": "strong" if decisions[0] != "HOLD" else "hold"}

    if len(buys) >= 2:
        actor = _actor(buys)
        mc    = round(sum(r["confidence"] for r in buys) / len(buys) * (1.0 if len(buys)==3 else 0.9), 3)
        return {"decision": "BUY", "confidence": mc,
                "reasoning": _reasoning(buys),
                "stop_loss": actor.get("stop_loss"), "take_profit": actor.get("take_profit"),
                "signal": "strong" if len(buys) == 3 else "lean"}

    if len(sells) >= 2:
        actor = _actor(sells)
        mc    = round(sum(r["confidence"] for r in sells) / len(sells) * (1.0 if len(sells)==3 else 0.9), 3)
        return {"decision": "SELL", "confidence": mc,
                "reasoning": _reasoning(sells),
                "stop_loss": actor.get("stop_loss"), "take_profit": actor.get("take_profit"),
                "signal": "strong" if len(sells) == 3 else "lean"}

    return {"decision": "HOLD", "confidence": avg_conf,
            "reasoning": f"Conflicting — {', '.join(f'{p.upper()}: {d}' for p, d in zip(PERSONA_NAMES, decisions))}",
            "stop_loss": None, "take_profit": None, "signal": "conflict"}


# ── OUTCOME ───────────────────────────────────────────────────────────────────

def compute_outcome(decision: str, entry: float, sl, tp, future_close: float):
    """Determine what happened to the trade OUTCOME_DAYS later."""
    if decision == "HOLD":
        return "hold", None, 0.0

    if decision == "BUY":
        if tp and future_close >= tp:
            closed, status = tp, "target"
        elif sl and future_close <= sl:
            closed, status = sl, "stopped"
        else:
            closed = future_close
            status = "target" if future_close > entry else "stopped"
        pnl = round((closed - entry) / entry * 100, 4)

    else:  # SELL
        if tp and future_close <= tp:
            closed, status = tp, "target"
        elif sl and future_close >= sl:
            closed, status = sl, "stopped"
        else:
            closed = future_close
            status = "target" if future_close < entry else "stopped"
        pnl = round((entry - closed) / entry * 100, 4)

    return status, round(closed, 4), pnl


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("VEKTOR SEEDER — 2-Year Historical Trade Backfill")
    print("=" * 60)

    total = 0

    for ticker in WATCHLIST:
        print(f"\n[{ticker}]")
        df = fetch_history(ticker)
        if df.empty:
            print("  No data — skipping")
            continue

        sampled = sample_days(df)
        print(f"  {len(sampled)} sample days to seed")

        for i, (date, row) in enumerate(sampled.iterrows()):
            entry = round(float(row["Close"]), 2)
            date_str = str(date.date())

            # Get price OUTCOME_DAYS later
            future_idx   = min(df.index.get_loc(date) + OUTCOME_DAYS, len(df) - 1)
            future_close = round(float(df.iloc[future_idx]["Close"]), 2)

            print(f"  [{i+1}/{len(sampled)}] {date_str} @ ${entry} → {future_close} ({OUTCOME_DAYS}d later)")

            # Run all 3 personas
            results = []
            for name, style in PERSONAS.items():
                r = ask_persona(name, style, ticker, row)
                r["persona"] = name
                results.append(r)
                time.sleep(0.3)  # Groq rate limit

            final  = consensus(results)
            status, closed_price, pnl = compute_outcome(
                final["decision"], entry,
                final.get("stop_loss"), final.get("take_profit"),
                future_close,
            )

            supabase.table("trades").insert({
                "asset":          ticker,
                "decision":       final["decision"],
                "reasoning":      final["reasoning"],
                "confidence":     final["confidence"],
                "persona":        "seeded-consensus",
                "paper_trade":    True,
                "price_at_trade": entry,
                "stop_loss":      final.get("stop_loss"),
                "take_profit":    final.get("take_profit"),
                "status":         status,
                "closed_price":   closed_price,
                "pnl":            pnl if final["decision"] != "HOLD" else None,
                "created_at":     date_str + "T14:30:00+00:00",
            }).execute()

            total += 1
            icon = "✅" if status == "target" else ("❌" if status == "stopped" else "—")
            print(f"    {icon} {final['decision']} conf={final['confidence']:.2f} pnl={pnl:+.2f}%")

        print(f"  Done with {ticker}")

    print("\n" + "=" * 60)
    print(f"SEEDER COMPLETE — {total} trades inserted")
    print("=" * 60)


if __name__ == "__main__":
    main()
