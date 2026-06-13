import os
import time
from groq import Groq
from prompt import build_context, build_prompt, parse_response

_client = None
MODEL    = "llama-3.3-70b-versatile"   # better instruction following → higher faithfulness
MAX_RETRIES = 3

FAITHFULNESS_PROMPT = """You are auditing a trading decision for how well its reasoning is grounded in the provided context.

Context:
{context}

Decision: {decision}
Reasoning: {reasoning}

"Grounded" means each claim either:
- states a fact, figure, or event that appears in the context, or
- is a direct, reasonable interpretation of data in the context (e.g. "RSI of 78 suggests overbought"
  is grounded if that RSI value is in the context).

"Not grounded" means the reasoning relies on specific facts, numbers, or events that do not appear
anywhere in the context and cannot be inferred from it.

Score the reasoning from 0.0 to 1.0:
0.9-1.0 = every claim is stated in or directly inferable from the context
0.7-0.8 = mostly grounded, at most one minor unsupported or generic statement
0.4-0.6 = a mix of grounded and ungrounded claims
0.0-0.3 = largely unrelated to or contradicts the context

Reply with ONLY a single number between 0.0 and 1.0."""


def get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def _score_faithfulness(decision: str, reasoning: str, chunks: list) -> float:
    context = build_context(chunks)
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
    Retries up to MAX_RETRIES, feeding back the prior reasoning so the model
    can revise ungrounded claims. Falls back to HOLD if faithfulness never
    meets the threshold.
    """
    config = supabase.table("system_config").select("key,value").execute().data or []
    config = {r["key"]: r["value"] for r in config}
    faith_threshold = float(config.get("faithfulness_threshold", 0.75))

    t0 = time.time()
    result = None

    for attempt in range(MAX_RETRIES):
        previous_reasoning = result["reasoning"] if attempt > 0 and result else None
        prompt = build_prompt(persona, query, chunks, previous_reasoning=previous_reasoning)

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
