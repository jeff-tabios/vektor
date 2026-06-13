import importlib.util
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(path):
    name = os.path.basename(os.path.dirname(path)) + "_" + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_reranker = _load(os.path.join(ROOT, "reranker", "main.py"))
_embedder = _load(os.path.join(ROOT, "ingestion", "embedder.py"))

rerank = _reranker.rerank
embed  = _embedder.embed

MAX_RETRIES   = 3
K_INCREMENT   = 10


def _get_config(supabase) -> dict:
    rows = supabase.table("system_config").select("key,value").execute().data or []
    return {r["key"]: r["value"] for r in rows}


def retrieve(query: str, supabase, asset: str = "general") -> tuple:
    """
    Retrieves and reranks chunks with a quality gate.
    Retries up to MAX_RETRIES times, increasing k each attempt.
    Returns (chunks, retrieval_ms).
    """
    config      = _get_config(supabase)
    retrieval_k = int(config.get("retrieval_k", 30))   # fetch more candidates
    rerank_k    = int(config.get("rerank_k", 8))        # pass 8 chunks to LLM (more signal)

    t0      = time.time()
    chunks  = []

    for attempt in range(MAX_RETRIES):
        current_k = min(retrieval_k + attempt * K_INCREMENT, 50)

        embedding = embed([query])[0]
        results = (
            supabase.rpc("match_chunks", {"query_embedding": embedding, "match_count": current_k})
            .execute()
            .data or []
        )

        # prefer asset-specific chunks but fall back to all
        filtered = [r for r in results if r.get("asset") in (asset, "general")]
        pool = filtered if filtered else results

        chunks = rerank(query, pool, top_k=rerank_k)

        if chunks:
            if attempt > 0:
                print(f"Retrieval: got results on attempt {attempt + 1} (k={current_k})")
            break
        else:
            print(f"Retrieval attempt {attempt + 1} empty, retrying with k={current_k + K_INCREMENT}")

    retrieval_ms = round((time.time() - t0) * 1000, 2)
    return chunks, retrieval_ms
