import os
import re
import time

import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client

from chunker import chunk_text
from embedder import embed
from eval_generator import generate_questions
from healer import heal

load_dotenv()

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

RSS_FEEDS = [
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/", "general"),
    ("Cointelegraph", "https://cointelegraph.com/rss",                    "general"),
    ("Decrypt",       "https://decrypt.co/feed",                          "general"),
    ("BitcoinMag",    "https://bitcoinmagazine.com/feed",                 "BTC"),
]


def clean(text: str) -> str:
    text = BeautifulSoup(text, "html.parser").get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def fetch_articles() -> list:
    articles = []
    for source, url, asset in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
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

    if not new_articles:
        print("Nothing to ingest")
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
    if inserted:
        questions = generate_questions(inserted)
        if questions:
            supabase.table("eval_questions").insert(questions).execute()
            q_count = len(questions)
            print(f"Generated {q_count} eval questions")

    supabase.rpc("delete_stale_chunks", {}).execute()
    supabase.rpc("delete_expired_evals", {}).execute()

    duration_ms = round((time.time() - t0) * 1000, 2)

    supabase.table("ingestion_runs").insert({
        "chunks_added": len(inserted),
        "chunks_deleted": 0,
        "eval_questions_generated": q_count,
        "recall_at_5": None,
        "duration_ms": duration_ms,
    }).execute()

    heal(supabase, recall=None)
    print(f"── Done in {duration_ms:.0f}ms ──")


if __name__ == "__main__":
    run()
