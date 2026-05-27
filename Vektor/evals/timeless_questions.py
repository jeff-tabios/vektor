import os
from supabase import create_client

TIMELESS = [
    {"query": "What is Bitcoin halving and how does it historically affect price?",             "asset": "BTC"},
    {"query": "How does the Bitcoin lightning network enable fast low-fee payments?",           "asset": "BTC"},
    {"query": "What is the MVRV ratio and what does it signal about Bitcoin valuation?",        "asset": "BTC"},
    {"query": "How does on-chain exchange outflow indicate accumulation by long-term holders?", "asset": "BTC"},
    {"query": "What is the stock-to-flow model and its critics?",                              "asset": "BTC"},
    {"query": "What is Ethereum proof of stake and how does it differ from proof of work?",    "asset": "ETH"},
    {"query": "What are EIP-1559 fee burns and how do they affect ETH supply?",                "asset": "ETH"},
    {"query": "What is the significance of the Ethereum Merge for network security?",          "asset": "ETH"},
    {"query": "How does the funding rate in perpetual futures markets indicate sentiment?",    "asset": "general"},
    {"query": "What is a short squeeze and what conditions cause it in crypto markets?",       "asset": "general"},
    {"query": "How does open interest in futures markets signal price direction?",             "asset": "general"},
    {"query": "What is the fear and greed index and how is it calculated?",                    "asset": "general"},
    {"query": "How does liquidity depth in order books affect slippage on large trades?",      "asset": "general"},
    {"query": "What are fat tail risks and why do they matter more in crypto than equities?",  "asset": "general"},
    {"query": "How does volatility clustering affect risk management in crypto trading?",      "asset": "general"},
]


def seed(supabase):
    existing = (
        supabase.table("eval_questions")
        .select("query")
        .eq("question_type", "timeless")
        .execute()
    )
    existing_queries = {r["query"] for r in existing.data} if existing.data else set()

    to_insert = [
        {"query": q["query"], "question_type": "timeless", "expires_at": None}
        for q in TIMELESS
        if q["query"] not in existing_queries
    ]

    if to_insert:
        supabase.table("eval_questions").insert(to_insert).execute()
        print(f"Seeded {len(to_insert)} timeless questions")
    else:
        print("All timeless questions already seeded")


if __name__ == "__main__":
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    seed(client)
