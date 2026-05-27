from sentence_transformers import SentenceTransformer
from typing import List

MODEL_NAME = "all-MiniLM-L6-v2"
_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(texts: List[str]) -> List[List[float]]:
    return get_model().encode(
        texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False
    ).tolist()
