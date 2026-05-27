from sentence_transformers import CrossEncoder
from typing import List

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_model = None


def get_model() -> CrossEncoder:
    global _model
    if _model is None:
        _model = CrossEncoder(MODEL_NAME)
    return _model


def rerank(query: str, chunks: List[dict], top_k: int = 5) -> List[dict]:
    if not chunks:
        return []

    model = get_model()
    pairs = [(query, chunk["text"]) for chunk in chunks]
    scores = model.predict(pairs)

    ranked = sorted(
        zip(scores, chunks),
        key=lambda x: x[0],
        reverse=True,
    )

    results = []
    for score, chunk in ranked[:top_k]:
        chunk["rerank_score"] = float(score)
        results.append(chunk)

    return results
