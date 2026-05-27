import os
import sys
import time

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, os.path.dirname(__file__))
from retriever import retrieve
from executor import execute

load_dotenv()

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

ASSET_QUERIES = {
    "BTC":  "Bitcoin price trend RSI MACD VIX market sentiment trading signals",
    "ETH":  "Ethereum price trend RSI MACD market sentiment staking",
    "SPY":  "S&P 500 SPY price trend RSI MACD VIX Fed rates CPI unemployment macro",
    "QQQ":  "Nasdaq QQQ tech stocks price trend RSI MACD momentum volatility",
    "NVDA": "NVIDIA stock price trend RSI MACD earnings AI semiconductor",
    "TSLA": "Tesla stock price trend RSI MACD earnings volatility sentiment",
    "AAPL": "Apple stock price trend RSI MACD earnings market sentiment",
    "AMD":  "AMD stock price trend RSI MACD earnings semiconductor",
}

PERSONAS = ["taleb", "saliba"]


def consensus(results: list) -> dict:
    decisions = [r["decision"] for r in results]

    if len(set(decisions)) == 1:
        # all agree
        return {
            "decision":    decisions[0],
            "confidence":  round(sum(r["confidence"] for r in results) / len(results), 3),
            "faithfulness": round(sum(r["faithfulness"] for r in results) / len(results), 3),
            "reasoning":   " | ".join(
                f"{p.upper()}: {r['reasoning']}"
                for p, r in zip(PERSONAS, results)
            ),
            "stop_loss":   results[0].get("stop_loss"),
            "take_profit": results[0].get("take_profit"),
            "signal":      "strong" if decisions[0] != "HOLD" else "hold",
        }
    else:
        # conflict → HOLD
        return {
            "decision":    "HOLD",
            "confidence":  0.5,
            "faithfulness": round(sum(r["faithfulness"] for r in results) / len(results), 3),
            "reasoning":   f"Conflicting signals — Taleb: {decisions[0]}, Saliba: {decisions[1]}. Staying out.",
            "stop_loss":   None,
            "take_profit": None,
            "signal":      "conflict",
        }


def run(asset: str = "SPY", paper_trade: bool = True):
    t0 = time.time()
    query = ASSET_QUERIES.get(asset, ASSET_QUERIES["SPY"])

    print(f"\n── Trading {asset} ──")

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

    supabase.table("trades").insert({
        "asset":          asset,
        "decision":       final["decision"],
        "reasoning":      final["reasoning"],
        "confidence":     final["confidence"],
        "persona":        "consensus",
        "paper_trade":    paper_trade,
        "price_at_trade": None,
        "stop_loss":      final["stop_loss"],
        "take_profit":    final["take_profit"],
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
