# Vektor — autonomous improvement sessions

Vektor is a paper-trading signal app: a RAG pipeline (Supabase/pgvector) feeds
retrieved market/news context to a 3-persona LLM consensus (Taleb, Saliba,
Druckenmiller) which produces BUY/SELL/HOLD signals. Quality is tracked via
`ingestion_runs.recall_at_5` (context retrieval) and `trade_evals.faithfulness`
(reasoning groundedness), plus paper-trading win rate / P&L in `trades`.

Key paths:
- `Vektor/trader/` — retrieval (`retriever.py`), prompts (`prompt.py`), signal
  generation + faithfulness gate (`executor.py`), consensus (`main.py`),
  position closing (`closer.py`).
- `Vektor/ingestion/` — knowledge base pipeline, eval question generation,
  recall@5 scoring, auto-healing of retrieval params (`healer.py`).
- `Vektor/dashboard/app.py` — Gradio dashboard showing the metrics above.
- `Vektor/database/schema.sql` — `system_config` holds tunable thresholds
  (`faithfulness_threshold`, `recall_threshold`, `retrieval_k`, `rerank_k`, etc.)

## When running as a scheduled/autonomous session

1. **Survey current state**: check the dashboard metrics (recall@5,
   faithfulness, win rate, P&L, signal mix) and recent `trade_evals` /
   `ingestion_runs` rows for regressions or stuck values.
2. **Pick ONE focused improvement** — the highest-leverage issue (e.g. a
   metric that's low, a gate that's mis-tuned, a bug in trade closing). Don't
   bundle unrelated changes into one run.
3. **Implement** the change with minimal, focused diffs following existing
   patterns (no new abstractions, no unused code, no comments unless
   explaining a non-obvious WHY).
4. **QA before pushing**:
   - `python3 -m py_compile` (or import) every changed module to catch syntax
     errors.
   - If the change affects prompts/parsing, write a small throwaway script
     that exercises `build_prompt`/`parse_response`/`build_context` etc. with
     fake chunks to confirm output shape — delete the script before
     committing.
   - If there are pytest tests under the touched package, run them.
   - Sanity-check that `system_config` keys / `trades` / `trade_evals` /
     `ingestion_runs` schema usage still matches `Vektor/database/schema.sql`
     and any migrations.
5. **Commit and push directly to `main`** (no PR review required — this is a
   paper-trading system, so the cost of a regression is low and caught by the
   next day's metrics). Use a clear commit message explaining the metric/issue
   being addressed and why the change should help.
6. **Send a push notification** with a one-line summary of what changed and
   why.

Do not change `.github/workflows/*.yml` cron schedules, secrets, or the
Supabase schema without flagging it clearly in the commit message — these
affect the live (paper) trading cadence.
