import os
import sys
import time

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, os.path.dirname(__file__))
from retriever import retrieve
from executor import execute
from pricing import get_price

IBKR_AVAILABLE = False
if os.environ.get("IBKR_ENABLED", "").lower() == "true":
    try:
        from ibkr import execute_trade as ibkr_execute
        IBKR_AVAILABLE = True
    except ImportError:
        pass

load_dotenv()

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

ASSET_QUERIES = {
    "SPY":  "S&P 500 SPY price trend RSI MACD VIX Fed rates CPI unemployment macro",
    "QQQ":  "Nasdaq QQQ tech stocks price trend RSI MACD momentum volatility",
    "NVDA": "NVIDIA stock price trend RSI MACD earnings AI semiconductor",
    "TSLA": "Tesla stock price trend RSI MACD earnings volatility sentiment",
    "AAPL": "Apple stock price trend RSI MACD earnings market sentiment",
    "AMD":  "AMD stock price trend RSI MACD earnings semiconductor",
}

PERSONAS = ["taleb", "saliba", "druckenmiller"]


def consensus(results: list) -> dict:
    decisions  = [r["decision"] for r in results]
    avg_faith  = round(sum(r["faithfulness"] for r in results) / len(results), 3)
    avg_conf   = round(sum(r["confidence"]   for r in results) / len(results), 3)

    buys  = [r for r in results if r["decision"] == "BUY"]
    sells = [r for r in results if r["decision"] == "SELL"]
    holds = [r for r in results if r["decision"] == "HOLD"]

    def _reasoning(group):
        return " | ".join(
            f"{PERSONAS[results.index(r)].upper()}: {r['reasoning']}"
            for r in group
        )

    def _actor(group):
        """Highest-confidence persona in the group — use their stops."""
        return max(group, key=lambda r: r["confidence"])

    # ── All 3 agree ──────────────────────────────────────────────────────────
    if len(set(decisions)) == 1:
        actor = _actor(results)
        return {
            "decision":     decisions[0],
            "confidence":   avg_conf,
            "faithfulness": avg_faith,
            "reasoning":    _reasoning(results),
            "stop_loss":    actor.get("stop_loss"),
            "take_profit":  actor.get("take_profit"),
            "signal":       "strong" if decisions[0] != "HOLD" else "hold",
        }

    # ── Majority BUY (2+) ────────────────────────────────────────────────────
    if len(buys) >= 2:
        actor    = _actor(buys)
        majority_conf = round(sum(r["confidence"] for r in buys) / len(buys), 3)
        haircut  = 1.0 if len(buys) == 3 else 0.9
        return {
            "decision":     "BUY",
            "confidence":   round(majority_conf * haircut, 3),
            "faithfulness": avg_faith,
            "reasoning":    _reasoning(buys) + (f" | {PERSONAS[results.index(holds[0])].upper()}: held" if holds else ""),
            "stop_loss":    actor.get("stop_loss"),
            "take_profit":  actor.get("take_profit"),
            "signal":       "strong" if len(buys) == 3 else "lean",
        }

    # ── Majority SELL (2+) ───────────────────────────────────────────────────
    if len(sells) >= 2:
        actor    = _actor(sells)
        majority_conf = round(sum(r["confidence"] for r in sells) / len(sells), 3)
        haircut  = 1.0 if len(sells) == 3 else 0.9
        return {
            "decision":     "SELL",
            "confidence":   round(majority_conf * haircut, 3),
            "faithfulness": avg_faith,
            "reasoning":    _reasoning(sells) + (f" | {PERSONAS[results.index(holds[0])].upper()}: held" if holds else ""),
            "stop_loss":    actor.get("stop_loss"),
            "take_profit":  actor.get("take_profit"),
            "signal":       "strong" if len(sells) == 3 else "lean",
        }

    # ── 1 BUY + 1 SELL + 1 HOLD or other split — true conflict ──────────────
    return {
        "decision":     "HOLD",
        "confidence":   avg_conf,
        "faithfulness": avg_faith,
        "reasoning":    f"Conflicting signals — {', '.join(f'{p.upper()}: {d}' for p, d in zip(PERSONAS, decisions))}. Staying out.",
        "stop_loss":    None,
        "take_profit":  None,
        "signal":       "conflict",
    }


def run(asset: str = "SPY", paper_trade: bool = True):
    t0 = time.time()
    query = ASSET_QUERIES.get(asset, ASSET_QUERIES["SPY"])

    print(f"\n── Trading {asset} ──")

    entry_price = get_price(asset)
    print(f"Entry price: {entry_price}")

    chunks, retrieval_ms = retrieve(query, supabase, asset=asset)
    if not chunks:
        print("No chunks retrieved — skipping trade")
        return

    print(f"Retrieved {len(chunks)} chunks in {retrieval_ms:.0f}ms")

    results = []
    for persona in PERSONAS:
        print(f"Running {persona}...")
        result = execute(query, chunks, persona, supabase)
        result["persona"] = persona
        results.append(result)
        print(f"  {persona}: {result['decision']} (conf={result['confidence']:.2f}, faith={result['faithfulness']:.2f})")

    final = consensus(results)
    total_ms = round((time.time() - t0) * 1000, 2)

    print(f"\n── Consensus ──")
    print(f"  Signal:       {final['signal'].upper()}")
    print(f"  Decision:     {final['decision']}")
    print(f"  Confidence:   {final['confidence']:.2f}")
    print(f"  Stop Loss:    {final['stop_loss'] or 'N/A'}")
    print(f"  Take Profit:  {final['take_profit'] or 'N/A'}")
    print(f"  Faithfulness: {final['faithfulness']:.2f}")
    print(f"  Reasoning:    {final['reasoning']}")

    ibkr_order_id = None
    ibkr_executed = False

    if IBKR_AVAILABLE and final["decision"] != "HOLD" and final["signal"] != "conflict":
        print(f"\n── IBKR ──")
        ibkr_order_id = ibkr_execute(
            asset=asset,
            decision=final["decision"],
            entry_price=entry_price or 0.0,
            stop_loss=final["stop_loss"],
            take_profit=final["take_profit"],
            paper=paper_trade,
        )
        ibkr_executed = ibkr_order_id is not None
        if ibkr_executed:
            print(f"  Order placed — id={ibkr_order_id}")
        else:
            print(f"  Order skipped (TWS not running or missing stops)")

    supabase.table("trades").insert({
        "asset":          asset,
        "decision":       final["decision"],
        "reasoning":      final["reasoning"],
        "confidence":     final["confidence"],
        "persona":        "consensus",
        "paper_trade":    paper_trade,
        "price_at_trade": entry_price,
        "stop_loss":      final["stop_loss"],
        "take_profit":    final["take_profit"],
        "ibkr_order_id":  ibkr_order_id,
        "ibkr_executed":  ibkr_executed,
    }).execute()

    supabase.table("trade_evals").insert({
        "query":        query,
        "decision":     final["decision"],
        "faithfulness": final["faithfulness"],
        "retrieval_ms": retrieval_ms,
        "rerank_ms":    retrieval_ms,
        "llm_ms":       sum(r["llm_ms"] for r in results),
        "total_ms":     total_ms,
    }).execute()

    print(f"\n── Done in {total_ms:.0f}ms ──")


if __name__ == "__main__":
    asset = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    run(asset=asset, paper_trade=True)
