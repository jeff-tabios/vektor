---
name: vektor-status
description: Check Vektor's operational health — GitHub Actions run status for ingestion/trader/closer, Supabase quality metrics (recall@5, faithfulness, win rate, P&L), and the HF Spaces dashboard. Use when asked "how is Vektor doing", "is it working", "check status", "any failures", or similar health checks.
---

# Vektor status check

Vektor has no single health endpoint — piece the picture together from GitHub
Actions (proof the cron jobs actually ran) and Supabase (the quality metrics
those jobs produced).

## Identifiers

- GitHub repo: `jeff-tabios/vektor`
- HF Space (dashboard): `jefftabios/vektor` — https://huggingface.co/spaces/jefftabios/vektor
  - Gated: `WebFetch` on this URL returns 403. Don't rely on fetching it
    directly — Gradio also renders client-side, so a raw fetch wouldn't show
    live data anyway. Use Supabase queries (below) for the same numbers the
    dashboard shows, or check the "Deploy dashboard to HF Spaces" step in the
    latest `ingestion.yml` run to confirm the deploy itself succeeded.
- Workflows: `.github/workflows/ingestion.yml` (every 4h + market open),
  `trader.yml` (triggered by ingestion at market open), `closer.yml`
  (intraday, every ~2h), `keep-alive.yml` (daily HF Space ping).

## 1. Check GitHub Actions run history

Use `mcp__github__actions_list` (method `list_workflow_runs`, resource_id =
workflow filename). **Warning**: responses are huge regardless of
`per_page` and will blow the context window if read directly — the tool
saves oversized output to a file instead of returning it inline. Parse that
file with Python rather than reading it as text:

```python
import json
data = json.load(open("<saved-file-path>"))
for r in data["workflow_runs"][:15]:
    print(r["created_at"], r["conclusion"], r["id"])
```

For any `failure`, get the root cause without downloading the whole log:

```
mcp__github__get_job_logs(owner="jeff-tabios", repo="vektor", run_id=<id>,
                           failed_only=true, return_content=true, tail_lines=150)
```

### Known recurring failure mode

`Vektor/ingestion/embedder.py` loads `sentence-transformers/all-MiniLM-L6-v2`
fresh from Hugging Face Hub on **every** ingestion and trader run (no model
caching across CI runs — only `pip` deps are cached in the workflow). When HF
Hub rate-limits (`429 Too Many Requests`), the run dies with:

```
huggingface_hub.errors.LocalEntryNotFoundError ...
OSError: We couldn't connect to 'https://huggingface.co' to load the files...
```

If you see this, it's not a logic bug — it's the missing-cache issue. Fix is
to add `actions/cache` for `~/.cache/huggingface` keyed on the model name in
`ingestion.yml` and `trader.yml`.

## 2. Check Supabase quality metrics

The dashboard (`Vektor/dashboard/app.py`) reads these tables via the
`supabase` Python client, authenticated with `SUPABASE_URL` / `SUPABASE_KEY`.
**These are GitHub Actions secrets, not exposed as env vars in a Claude Code
session** — direct queries from here will fail with a `KeyError` unless the
user has supplied them some other way. If they're available:

```python
import os
from supabase import create_client
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

runs   = supabase.table("ingestion_runs").select("recall_at_5,chunks_added").execute().data
evals  = supabase.table("trade_evals").select("faithfulness").execute().data
trades = supabase.table("trades").select("decision,pnl,status").execute().data
config = supabase.table("system_config").select("key,value").execute().data

avg_recall = sum(r["recall_at_5"] for r in runs if r["recall_at_5"]) / len(runs)
avg_faith  = sum(e["faithfulness"] for e in evals if e["faithfulness"]) / len(evals)
```

Healthy thresholds (mirrors the dashboard's color coding):
- `recall_at_5` ≥ 0.9 good, ≥ 0.7 ok, below that — retrieval is degraded.
- `faithfulness` ≥ 0.8 good, ≥ 0.6 ok, below that — reasoning ungrounded.
- `system_config` holds the live thresholds (`recall_threshold`,
  `faithfulness_threshold`, `retrieval_k`, `rerank_k`) — compare against
  `Vektor/database/schema.sql` defaults to spot drift from auto-healing
  (`Vektor/ingestion/healer.py`).
- Win rate / P&L: only meaningful past ~20 closed trades; fewer than that,
  treat results as noise (this is also how `make_summary` in `app.py`
  phrases it).

## 3. If Supabase isn't reachable

Fall back to GitHub Actions alone: a healthy system shows `ingestion.yml`
succeeding every 4h, `trader.yml` succeeding once at market open on weekdays,
and `closer.yml` succeeding every ~2h during market hours. Cross-reference
failure timestamps against the known HF rate-limit pattern above before
assuming it's a real regression.
