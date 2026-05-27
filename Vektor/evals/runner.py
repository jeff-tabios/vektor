import os
import numpy as np
from supabase import create_client
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"
K = 5


def recall_at_k(result_ids, expected_id, k=K):
    return 1.0 if expected_id in result_ids[:k] else 0.0


def run_evals(supabase, k=K):
    model = SentenceTransformer(MODEL_NAME)

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
            supabase.rpc("match_chunks", {"query_embedding": embedding, "match_count": k})
            .execute()
            .data or []
        )
        result_ids = [r["id"] for r in results]
        scores.append(recall_at_k(result_ids, q["expected_chunk_id"], k))

    recall = float(np.mean(scores)) if scores else 0.0
    print(f"Recall@{k}: {recall:.2%}  ({len(scores)} questions)")
    return recall


if __name__ == "__main__":
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    run_evals(client)
