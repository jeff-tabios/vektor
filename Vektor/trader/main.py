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
    "BTC":  "Bitcoin price trend RSI MACD market sentiment trading signals",
    "ETH":  "Ethereum price trend RSI MACD market sentiment staking",
    "SPY":  "S&P 500 SPY price trend RSI MACD VIX market sentiment Fed rates macro",
    "QQQ":  "Nasdaq QQQ tech stocks price trend RSI MACD momentum volatility",
    "NVDA": "NVIDIA stock price trend RSI MACD earnings AI semiconductor",
    "TSLA": "Tesla stock price trend RSI MACD earnings volatility sentiment",
    "AAPL": "Apple stock price trend RSI MACD earnings market sentiment",
    "AMD":  "AMD stock price trend RSI MACD earnings semiconductor",
}

PERSONAS = ["taleb", "saliba"]


def run(asset: str = "SPY", paper_trade: bool = True):
    t0 = time.time()
    query = ASSET_QUERIES.get(asset, ASSET_QUERIES["SPY"])

    print(f"\n── Trading {asset} ──")

    chunks, retrieval_ms = retrieve(query, supabase, asset=asset)
    if not chunks:
        print("No chunks retrieved — skipping trade")
        return

    print(f"Retrieved {len(chunks)} chunks in {retrieval_ms:.0f}ms")

    for persona in PERSONAS:
        print(f"\nPersona: {persona}")

        result = execute(query, chunks, persona, supabase)
        total_ms = round((time.time() - t0) * 1000, 2)

        print(f"  Decision:     {result['decision']}")
        print(f"  Confidence:   {result['confidence']:.2f}")
        print(f"  Stop Loss:    {result.get('stop_loss') or 'N/A'}")
        print(f"  Take Profit:  {result.get('take_profit') or 'N/A'}")
        print(f"  Faithfulness: {result['faithfulness']:.2f}")
        print(f"  Reasoning:    {result['reasoning']}")

        supabase.table("trades").insert({
            "asset":          asset,
            "decision":       result["decision"],
            "reasoning":      result["reasoning"],
            "confidence":     result["confidence"],
            "persona":        persona,
            "paper_trade":    paper_trade,
            "price_at_trade": None,
            "stop_loss":      result.get("stop_loss"),
            "take_profit":    result.get("take_profit"),
        }).execute()

        supabase.table("trade_evals").insert({
            "query":        query,
            "decision":     result["decision"],
            "faithfulness": result["faithfulness"],
            "retrieval_ms": retrieval_ms,
            "rerank_ms":    retrieval_ms,
            "llm_ms":       result["llm_ms"],
            "total_ms":     total_ms,
        }).execute()

    print(f"\n── Done in {total_ms:.0f}ms ──")


if __name__ == "__main__":
    asset = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    run(asset=asset, paper_trade=True)
