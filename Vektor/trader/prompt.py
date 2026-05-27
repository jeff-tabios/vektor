PERSONAS = {
    "taleb": {
        "name": "Nassim Taleb",
        "style": (
            "You are a trader inspired by Nassim Taleb's philosophy.\n"
            "You focus on asymmetric risk, tail events, and antifragility.\n"
            "You default to HOLD unless the risk/reward is overwhelmingly asymmetric.\n"
            "You never risk ruin. Capital preservation comes first.\n"
            "You are deeply skeptical of confident predictions."
        ),
    },
    "saliba": {
        "name": "Anthony Saliba",
        "style": (
            "You are a trader inspired by Anthony Saliba's options trading philosophy.\n"
            "You focus on volatility, momentum, and defined risk/reward setups.\n"
            "You act decisively when signals align and cut losses quickly.\n"
            "You think in probabilities, not certainties.\n"
            "For options: stop at 50% of premium paid, take profit at 100% gain."
        ),
    },
}

_TEMPLATE = """{persona_style}

You are analyzing {asset} using ONLY the following recent news and market context:

---
{context}
---

Based SOLELY on the information above, make a trading decision.
Use the current price from the market data above to set your stop loss and take profit levels.

Respond in this exact format:
DECISION: [BUY/SELL/HOLD]
CONFIDENCE: [0.0-1.0]
STOP_LOSS: [price level to exit if wrong. For HOLD use N/A]
TAKE_PROFIT: [price level to lock in gains. For HOLD use N/A]
REASONING: [2-3 sentences citing specific facts from the context above]"""

_STRICT_TEMPLATE = """{persona_style}

You are analyzing {asset}. You MUST base every single claim on the context below.
Do NOT use any external knowledge. If context is insufficient, respond HOLD.

Context:
---
{context}
---

Use the current price from the market data above to set stop loss and take profit levels.

Respond in this exact format:
DECISION: [BUY/SELL/HOLD]
CONFIDENCE: [0.0-1.0]
STOP_LOSS: [price level to exit if wrong. For HOLD use N/A]
TAKE_PROFIT: [price level to lock in gains. For HOLD use N/A]
REASONING: [2-3 sentences citing specific facts from the context above]"""


def build_prompt(persona: str, asset: str, chunks: list, strict: bool = False) -> str:
    p = PERSONAS.get(persona, PERSONAS["taleb"])
    context = "\n\n".join(f"[{c.get('source', '')}] {c['text']}" for c in chunks)
    template = _STRICT_TEMPLATE if strict else _TEMPLATE
    return template.format(
        persona_style=p["style"],
        asset=asset,
        context=context[:4000],
    )


def parse_response(text: str) -> dict:
    result = {
        "decision": "HOLD",
        "confidence": 0.5,
        "stop_loss": None,
        "take_profit": None,
        "reasoning": text.strip(),
    }
    for line in text.strip().splitlines():
        if line.startswith("DECISION:"):
            d = line.replace("DECISION:", "").strip()
            if d in ("BUY", "SELL", "HOLD"):
                result["decision"] = d
        elif line.startswith("CONFIDENCE:"):
            try:
                result["confidence"] = float(line.replace("CONFIDENCE:", "").strip())
            except ValueError:
                pass
        elif line.startswith("STOP_LOSS:"):
            val = line.replace("STOP_LOSS:", "").strip()
            try:
                result["stop_loss"] = float(val)
            except ValueError:
                result["stop_loss"] = None
        elif line.startswith("TAKE_PROFIT:"):
            val = line.replace("TAKE_PROFIT:", "").strip()
            try:
                result["take_profit"] = float(val)
            except ValueError:
                result["take_profit"] = None
        elif line.startswith("REASONING:"):
            result["reasoning"] = line.replace("REASONING:", "").strip()
    return result
