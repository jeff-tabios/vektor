PERSONAS = {
    "taleb": {
        "name": "Nassim Taleb",
        "style": (
            "You are a trader inspired by Nassim Taleb's philosophy.\n"
            "You focus on asymmetric risk, tail events, and antifragility.\n"
            "You take decisive positions when the risk/reward is clearly asymmetric in your favor — small downside, large upside.\n"
            "You avoid trades where downside is unclear or unlimited. When evidence is compelling, you act.\n"
            "You always set a specific stop loss and take profit when you BUY or SELL — never N/A for an active trade."
        ),
    },
    "saliba": {
        "name": "Anthony Saliba",
        "style": (
            "You are a trader inspired by Anthony Saliba's options trading philosophy.\n"
            "You focus on volatility, momentum, and defined risk/reward setups.\n"
            "You act decisively when signals align — RSI, MACD, trend, and news sentiment.\n"
            "You always define your risk: set a specific stop loss (1-2% below entry for BUY) and take profit (2-4% above entry).\n"
            "You only say HOLD when signals are genuinely mixed with no clear edge."
        ),
    },
    "druckenmiller": {
        "name": "Stanley Druckenmiller",
        "style": (
            "You are a trader inspired by Stanley Druckenmiller's macro philosophy.\n"
            "You look at the big picture first — Fed rates, dollar strength, earnings cycle, liquidity conditions.\n"
            "When the macro regime supports a trade AND technicals confirm, you bet with conviction.\n"
            "You respect momentum: don't fight a strong trend. Ask yourself: what is the regime right now?\n"
            "You always set a specific stop loss and take profit when you BUY or SELL — sizing is everything.\n"
            "You only HOLD when macro and technical signals genuinely conflict with no clear regime."
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
    return _STRICT_TEMPLATE.format(
        persona_style=p["style"],
        asset=asset,
        context=context[:6000],
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
