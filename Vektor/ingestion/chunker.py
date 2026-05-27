from typing import List

CHUNK_TOKENS = 500
OVERLAP_TOKENS = 50
WORDS_PER_TOKEN = 0.75


def chunk_text(text: str, chunk_tokens: int = CHUNK_TOKENS, overlap_tokens: int = OVERLAP_TOKENS) -> List[str]:
    words = text.split()
    chunk_words = int(chunk_tokens * WORDS_PER_TOKEN)
    overlap_words = int(overlap_tokens * WORDS_PER_TOKEN)

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_words
        chunk = " ".join(words[start:end]).strip()
        if len(chunk) > 50:
            chunks.append(chunk)
        if end >= len(words):
            break
        start = end - overlap_words

    return chunks
