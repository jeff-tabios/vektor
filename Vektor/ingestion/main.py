import argparse
import os
import re
import sys
import time

import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "evals"))
from runner import run_evals

from chunker import chunk_text
from embedder import embed
from eval_generator import generate_questions
from healer import heal
from market_data import fetch_market_data

load_dotenv()

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

RSS_FEEDS = [
    # Crypto
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/",              "general"),
    ("Cointelegraph", "https://cointelegraph.com/rss",                                "general"),
    ("Decrypt",       "https://decrypt.co/feed",                                      "general"),
    ("BitcoinMag",    "https://bitcoinmagazine.com/feed",                             "BTC"),
    ("TheBlock",      "https://www.theblock.co/rss.xml",                              "general"),
    ("CryptoSlate",   "https://cryptoslate.com/feed/",                                "general"),
    ("NewsBTC",       "https://www.newsbtc.com/feed/",                                "BTC"),
    ("Bitcoinist",    "https://bitcoinist.com/feed/",                                 "BTC"),
    ("BeInCrypto",    "https://beincrypto.com/feed/",                                 "general"),
    ("AMBCrypto",     "https://ambcrypto.com/feed/",                                  "general"),
    ("CryptoNews",    "https://cryptonews.com/news/feed/",                            "general"),
    ("UToday",        "https://u.today/rss",                                          "general"),
    # Stocks / Macro
    ("Reuters",       "https://feeds.reuters.com/reuters/businessNews",               "general"),
    ("CNBC",          "https://www.cnbc.com/id/100003114/device/rss/rss.html",        "general"),
    ("MarketWatch",   "https://feeds.content.dowjones.io/public/rss/mw_marketpulse", "general"),
    ("Investopedia",  "https://www.investopedia.com/feedbuilder/feed/getfeed/?feedName=rss_headline", "general"),
]

ALL_TABLES = ["chunks", "eval_questions", "ingestion_runs", "trades", "trade_evals", "healing_log"]
DEFAULT_NUKE_TABLES = ["chunks", "eval_questions", "ingestion_runs"]


def nuke(tables: list):
    print(f"── NUKE: {', '.join(tables)} ──")
    for table in tables:
        supabase.table(table).delete().neq("id", 0).execute()
        print(f"  Cleared {table}")
    print("── Done ──\n")


def clean(text: str) -> str:
    text = BeautifulSoup(text, "html.parser").get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def fetch_articles() -> list:
    articles = []
    for source, url, asset in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:
                text = clean(getattr(entry, "summary", "") or getattr(entry, "title", ""))
                if len(text) > 100:
                    articles.append({
                        "text": text,
                        "source": source,
                        "source_url": getattr(entry, "link", ""),
                        "asset": asset,
                    })
        except Exception as e:
            print(f"Feed error [{source}]: {e}")
    return articles


def existing_urls() -> set:
    r = supabase.table("chunks").select("source_url").execute()
    return {row["source_url"] for row in r.data} if r.data else set()


def run():
    t0 = time.time()
    print("── Ingestion start ──")

    articles = fetch_articles()
    print(f"Fetched {len(articles)} articles")

    seen = existing_urls()
    new_articles = [a for a in articles if a["source_url"] not in seen]
    print(f"New articles: {len(new_articles)}")

    # always refresh market data regardless of new articles
    print("Fetching market data...")
    market_chunks = fetch_market_data()
    if market_chunks:
        supabase.table("chunks").delete().eq("source", "market_data").execute()
        market_embeddings = embed([c["text"] for c in market_chunks])
        for chunk, emb in zip(market_chunks, market_embeddings):
            chunk["embedding"] = emb
        supabase.table("chunks").insert(market_chunks).execute()
        print(f"Refreshed {len(market_chunks)} market data chunks")

    if not new_articles:
        print("No new articles — market data updated only")
        print("Running evals...")
        recall = run_evals(supabase)
        duration_ms = round((time.time() - t0) * 1000, 2)
        supabase.table("ingestion_runs").insert({
            "chunks_added": len(market_chunks),
            "chunks_deleted": 0,
            "eval_questions_generated": 0,
            "recall_at_5": recall,
            "duration_ms": duration_ms,
        }).execute()
        heal(supabase, recall=recall)
        print(f"── Done in {duration_ms:.0f}ms ──")
        return

    all_chunks = []
    for article in new_articles:
        for piece in chunk_text(article["text"]):
            all_chunks.append({
                "text": piece,
                "source": article["source"],
                "source_url": article["source_url"],
                "asset": article["asset"],
            })

    print(f"Embedding {len(all_chunks)} chunks...")
    embeddings = embed([c["text"] for c in all_chunks])
    for chunk, emb in zip(all_chunks, embeddings):
        chunk["embedding"] = emb

    inserted = []
    for i in range(0, len(all_chunks), 100):
        result = supabase.table("chunks").insert(all_chunks[i:i + 100]).execute()
        inserted.extend(result.data or [])
    print(f"Inserted {len(inserted)} chunks")

    q_count = 0
    existing_q_count = supabase.table("eval_questions").select("id", count="exact").execute().count or 0
    chunks_for_evals = inserted

    if existing_q_count < 50:
        all_chunks_sample = (
            supabase.table("chunks").select("id,text,source").limit(100).execute().data or []
        )
        seen_ids = {c["id"] for c in inserted}
        extra = [c for c in all_chunks_sample if c["id"] not in seen_ids]
        chunks_for_evals = (inserted + extra)[:100]

    if chunks_for_evals:
        questions = generate_questions(chunks_for_evals, max_chunks=50)
        if questions:
            supabase.table("eval_questions").insert(questions).execute()
            q_count = len(questions)
            print(f"Generated {q_count} eval questions")

    supabase.rpc("delete_stale_chunks", {}).execute()
    supabase.rpc("delete_expired_evals", {}).execute()

    print("Running evals...")
    recall = run_evals(supabase)

    duration_ms = round((time.time() - t0) * 1000, 2)

    supabase.table("ingestion_runs").insert({
        "chunks_added": len(inserted),
        "chunks_deleted": 0,
        "eval_questions_generated": q_count,
        "recall_at_5": recall,
        "duration_ms": duration_ms,
    }).execute()

    heal(supabase, recall=recall)
    print(f"── Done in {duration_ms:.0f}ms ──")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--nuke",
        nargs="*",
        metavar="TABLE",
        help=f"Clear tables before running. No args = default ({', '.join(DEFAULT_NUKE_TABLES)}). Pass table names to clear specific ones. Use 'all' to clear everything.",
    )
    args = parser.parse_args()

    if args.nuke is not None:
        if args.nuke == ["all"]:
            nuke(ALL_TABLES)
        elif args.nuke:
            nuke(args.nuke)
        else:
            nuke(DEFAULT_NUKE_TABLES)

    run()
