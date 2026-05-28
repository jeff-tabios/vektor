"""
Runs daily — checks all open trades and closes them if price hit
stop loss or take profit. Also ratchets trailing stops as trades move
in our favor.
"""
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, os.path.dirname(__file__))
from pricing import get_price

load_dotenv()

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# (gain_threshold, locked_in_gain)
# e.g. if trade is up 5%, lock in 2.5% by moving stop there
TRAIL_STEPS = [
    (0.05, 0.025),
    (0.03, 0.010),
    (0.015, 0.000),  # breakeven
]


def close_trade(trade_id: int, status: str, closed_price: float, pnl: float):
    supabase.table("trades").update({
        "status":       status,
        "closed_price": closed_price,
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


def ratchet_stop(decision: str, entry: float, current: float, current_stop: float) -> float | None:
    """
    Returns a new stop loss if it should be moved, otherwise None.
    Stop only ever moves in the favorable direction — never against the trade.
    """
    for gain_pct, lock_pct in TRAIL_STEPS:
        if decision == "BUY":
            gain = (current - entry) / entry
            if gain >= gain_pct:
                new_stop = entry * (1 + lock_pct)
                if new_stop > current_stop:
                    return new_stop
                break
        elif decision == "SELL":
            gain = (entry - current) / entry
            if gain >= gain_pct:
                new_stop = entry * (1 - lock_pct)
                if new_stop < current_stop:
                    return new_stop
                break
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
        print("No open trades to check.")
        return

    print(f"Checking {len(open_trades)} open trade(s)...")

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
            price_cache[asset] = get_price(asset)
        current = price_cache[asset]

        if not current:
            print(f"  [{asset}] could not fetch price — skipping")
            continue

        # --- trailing stop ratchet ---
        if sl:
            new_stop = ratchet_stop(decision, entry, current, sl)
            if new_stop:
                update_stop(trade_id, new_stop)
                direction = "▲" if decision == "BUY" else "▼"
                print(f"  {direction} {asset} {decision} stop ratcheted {sl:.2f} → {new_stop:.2f}")
                sl = new_stop  # use updated stop for close check below

        # --- close check ---
        status = None
        closed_at = current

        if decision == "BUY":
            if sl and current <= sl:
                status = "stopped"
                closed_at = sl
            elif tp and current >= tp:
                status = "target"
                closed_at = tp

        elif decision == "SELL":
            if sl and current >= sl:
                status = "stopped"
                closed_at = sl
            elif tp and current <= tp:
                status = "target"
                closed_at = tp

        if status:
            pnl = calc_pnl(decision, entry, closed_at)
            close_trade(trade_id, status, closed_at, pnl)
            emoji = "✅" if status == "target" else "❌"
            print(f"  {emoji} {asset} {decision} closed — {status} at {closed_at} | P&L: {pnl:+.2f}%")
        else:
            pnl = calc_pnl(decision, entry, current)
            print(f"  ⏳ {asset} {decision} still open | current={current} | unrealized: {pnl:+.2f}%")

    print("Done.")


if __name__ == "__main__":
    run()
