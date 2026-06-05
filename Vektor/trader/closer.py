"""
Simulated IBKR-style closer.

Runs every 15 minutes during market hours via closer.yml.
Uses intraday high/low to check stops — exactly how IBKR bracket
orders work. Ratchets trailing stops based on the best intraday
price reached, not just the current price.
"""
import os
import sys
from datetime import datetime, timezone

import yfinance as yf
from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, os.path.dirname(__file__))

load_dotenv()

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

SYMBOL_MAP = {
    "SPY": "SPY", "QQQ": "QQQ", "NVDA": "NVDA",
    "TSLA": "TSLA", "AAPL": "AAPL", "AMD": "AMD",
}

# Trailing stop ratchet steps: (gain_threshold, locked_in_gain)
TRAIL_STEPS = [
    (0.05, 0.025),   # up 5%   → lock in 2.5%
    (0.03, 0.010),   # up 3%   → lock in 1%
    (0.015, 0.000),  # up 1.5% → breakeven
]


def get_intraday(asset: str) -> tuple:
    """
    Returns (current, day_high, day_low) using 1-minute intraday data.
    This is how IBKR checks stops — on actual price touching the level.
    """
    sym = SYMBOL_MAP.get(asset, asset)
    try:
        hist = yf.Ticker(sym).history(period="1d", interval="1m")
        if hist.empty:
            return None, None, None
        current  = round(float(hist["Close"].iloc[-1]), 4)
        day_high = round(float(hist["High"].max()), 4)
        day_low  = round(float(hist["Low"].min()), 4)
        return current, day_high, day_low
    except Exception as e:
        print(f"  Price error ({asset}): {e}")
        return None, None, None


def close_trade(trade_id: int, status: str, closed_price: float, pnl: float):
    supabase.table("trades").update({
        "status":       status,
        "closed_price": round(closed_price, 4),
        "pnl":          pnl,
    }).eq("id", trade_id).execute()


def update_stop(trade_id: int, new_stop: float):
    supabase.table("trades").update({
        "stop_loss": round(new_stop, 4),
    }).eq("id", trade_id).execute()


def calc_pnl(decision: str, entry: float, closed: float) -> float:
    if decision == "BUY":
        return round((closed - entry) / entry * 100, 4)
    if decision == "SELL":
        return round((entry - closed) / entry * 100, 4)
    return 0.0


def ratchet_stop(decision: str, entry: float, best_price: float, current_stop: float):
    """
    Ratchet based on best intraday price (high for BUY, low for SELL).
    Stop only ever moves in the favorable direction.
    """
    for gain_pct, lock_pct in TRAIL_STEPS:
        if decision == "BUY":
            gain = (best_price - entry) / entry
            if gain >= gain_pct:
                new_stop = entry * (1 + lock_pct)
                return new_stop if new_stop > current_stop else None
        elif decision == "SELL":
            gain = (entry - best_price) / entry
            if gain >= gain_pct:
                new_stop = entry * (1 - lock_pct)
                return new_stop if new_stop < current_stop else None
    return None


def run():
    open_trades = (
        supabase.table("trades")
        .select("*")
        .eq("status", "open")
        .neq("decision", "HOLD")
        .execute()
        .data or []
    )

    if not open_trades:
        print("No open trades.")
        return

    print(f"Checking {len(open_trades)} open trade(s) [IBKR-style intraday]...")

    price_cache = {}

    for trade in open_trades:
        asset    = trade["asset"]
        decision = trade["decision"]
        entry    = trade.get("price_at_trade")
        sl       = trade.get("stop_loss")
        tp       = trade.get("take_profit")
        trade_id = trade["id"]

        if not entry:
            continue

        if asset not in price_cache:
            price_cache[asset] = get_intraday(asset)
        current, day_high, day_low = price_cache[asset]

        if not current:
            print(f"  [{asset}] no price — skipping")
            continue

        # Best intraday price in our favour
        best = day_high if decision == "BUY" else day_low

        # ── Trailing stop ratchet (based on intraday best) ────────────────
        if sl and best:
            new_stop = ratchet_stop(decision, entry, best, sl)
            if new_stop:
                update_stop(trade_id, new_stop)
                direction = "▲" if decision == "BUY" else "▼"
                print(f"  {direction} {asset} {decision} stop ratcheted {sl:.2f} → {new_stop:.2f} (intraday best={best:.2f})")
                sl = new_stop

        # ── IBKR-style stop/target check using intraday high/low ─────────
        status    = None
        closed_at = None

        if decision == "BUY":
            if sl and day_low <= sl:        # low touched stop loss
                status, closed_at = "stopped", sl
            elif tp and day_high >= tp:     # high touched take profit
                status, closed_at = "target", tp

        elif decision == "SELL":
            if sl and day_high >= sl:       # high touched stop loss
                status, closed_at = "stopped", sl
            elif tp and day_low <= tp:      # low touched take profit
                status, closed_at = "target", tp

        if status:
            pnl = calc_pnl(decision, entry, closed_at)
            close_trade(trade_id, status, closed_at, pnl)
            emoji = "✅" if status == "target" else "❌"
            print(f"  {emoji} {asset} {decision} closed — {status} at {closed_at:.2f} | P&L: {pnl:+.2f}%")
        else:
            pnl = calc_pnl(decision, entry, current)
            print(f"  ⏳ {asset} {decision} open | now={current:.2f} hi={day_high:.2f} lo={day_low:.2f} | unrealized: {pnl:+.2f}%")

    print("Done.")


if __name__ == "__main__":
    run()
