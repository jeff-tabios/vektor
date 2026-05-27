import importlib.util
import os
import numpy as np
from supabase import create_client
from sentence_transformers import SentenceTransformer

def _load(path):
    name = os.path.basename(os.path.dirname(path)) + "_" + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rerank = _load(os.path.join(ROOT, "reranker", "main.py")).rerank

MODEL_NAME = "all-MiniLM-L6-v2"
K = 5


def recall_at_k(result_ids, expected_id, k=K):
    return 1.0 if expected_id in result_ids[:k] else 0.0


def get_retrieval_k(supabase) -> int:
    r = supabase.table("system_config").select("value").eq("key", "retrieval_k").execute()
    return int(r.data[0]["value"]) if r.data else 20


def run_evals(supabase, k=K):
    model = SentenceTransformer(MODEL_NAME)
    retrieval_k = get_retrieval_k(supabase)

    questions = (
        supabase.table("eval_questions")
        .select("*")
        .not_.is_("expected_chunk_id", "null")
        .execute()
        .data or []
    )

    if not questions:
        print("No eval questions with expected_chunk_id set. Run ingestion first.")
        return None

    scores = []
    for q in questions:
        embedding = model.encode([q["query"]], normalize_embeddings=True)[0].tolist()
        results = (
            supabase.rpc("match_chunks", {"query_embedding": embedding, "match_count": retrieval_k})
            .execute()
            .data or []
        )
        reranked = rerank(q["query"], results, top_k=k)
        result_ids = [r["id"] for r in reranked]
        scores.append(recall_at_k(result_ids, q["expected_chunk_id"], k))

    recall = float(np.mean(scores)) if scores else 0.0
    print(f"Recall@{k} (after rerank): {recall:.2%}  ({len(scores)} questions)")
    return recall


if __name__ == "__main__":
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    run_evals(client)
