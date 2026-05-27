"""
Runs daily — checks all open trades and closes them if price hit
stop loss or take profit. Updates trades.status, closed_price, pnl.
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


def close_trade(trade_id: int, status: str, closed_price: float, pnl: float):
    supabase.table("trades").update({
        "status":       status,
        "closed_price": closed_price,
        "pnl":          pnl,
    }).eq("id", trade_id).execute()


def calc_pnl(decision: str, entry: float, closed: float) -> float:
    if decision == "BUY":
        return round((closed - entry) / entry * 100, 4)
    if decision == "SELL":
        return round((entry - closed) / entry * 100, 4)
    return 0.0


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
            print(f"  ⏳ {asset} {decision} still open | current={current} | unrealized P&L: {pnl:+.2f}%")

    print("Done.")


if __name__ == "__main__":
    run()
