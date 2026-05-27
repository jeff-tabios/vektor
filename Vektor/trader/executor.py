import os
import time
from groq import Groq
from prompt import build_prompt, parse_response

_client = None
MODEL = "llama-3.1-8b-instant"
MAX_RETRIES = 3

FAITHFULNESS_PROMPT = """Rate how well this trading decision is grounded in the provided context.

Context:
{context}

Decision: {decision}
Reasoning: {reasoning}

Score 0.0 to 1.0:
1.0 = Every claim in the reasoning is directly from the context
0.5 = Some claims supported, some are external knowledge
0.0 = Reasoning ignores or contradicts the context

Reply with ONLY a single number between 0.0 and 1.0."""


def get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def _score_faithfulness(decision: str, reasoning: str, chunks: list) -> float:
    context = "\n".join(c["text"][:300] for c in chunks)
    prompt = FAITHFULNESS_PROMPT.format(
        context=context, decision=decision, reasoning=reasoning
    )
    try:
        resp = get_client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.0,
        )
        return float(resp.choices[0].message.content.strip())
    except Exception:
        return 0.5


def execute(query: str, chunks: list, persona: str, supabase) -> dict:
    """
    Makes a trading decision with a faithfulness quality gate.
    Retries up to MAX_RETRIES with increasingly strict prompts.
    Falls back to HOLD if faithfulness never meets the threshold.
    """
    config = supabase.table("system_config").select("key,value").execute().data or []
    config = {r["key"]: r["value"] for r in config}
    faith_threshold = float(config.get("faithfulness_threshold", 0.75))

    t0 = time.time()
    result = None

    for attempt in range(MAX_RETRIES):
        strict = attempt > 0
        prompt = build_prompt(persona, query, chunks, strict=strict)

        try:
            resp = get_client().chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.2,
            )
            raw = resp.choices[0].message.content
            result = parse_response(raw)
        except Exception as e:
            print(f"LLM error attempt {attempt + 1}: {e}")
            continue

        faith = _score_faithfulness(result["decision"], result["reasoning"], chunks)
        result["faithfulness"] = faith

        if faith >= faith_threshold:
            if attempt > 0:
                print(f"Faithfulness passed on attempt {attempt + 1}: {faith:.2f}")
            break
        else:
            print(f"Faithfulness {faith:.2f} < {faith_threshold} on attempt {attempt + 1}, retrying...")

    if result is None:
        result = {"decision": "HOLD", "confidence": 0.0, "reasoning": "All attempts failed.", "faithfulness": 0.0}
    elif result.get("faithfulness", 0) < faith_threshold:
        print(f"Faithfulness never met threshold after {MAX_RETRIES} attempts — forcing HOLD")
        result["decision"] = "HOLD"
        result["reasoning"] = f"[Quality gate failed] Original: {result['reasoning']}"

    result["llm_ms"] = round((time.time() - t0) * 1000, 2)
    return result
