import os
from groq import Groq

_client = None

PROMPT = """You are building a retrieval evaluation dataset.
Given the text below, write ONE specific question that:
- Can ONLY be answered using information in this exact text
- Is about a concrete fact, number, event, or claim
- Is NOT general knowledge

Return only the question, nothing else.

Text:
{text}"""


def get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def generate_questions(chunks: list, max_chunks: int = 5) -> list:
    client = get_client()
    questions = []

    for chunk in chunks[:max_chunks]:
        try:
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": PROMPT.format(text=chunk["text"][:800])}],
                max_tokens=100,
                temperature=0.3,
            )
            q = resp.choices[0].message.content.strip()
            if q and "?" in q:
                questions.append({
                    "query": q,
                    "question_type": "rolling",
                    "expected_chunk_id": chunk["id"],
                })
        except Exception as e:
            print(f"eval_generator error: {e}")

    return questions
