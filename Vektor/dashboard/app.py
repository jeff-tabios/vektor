import os
import gradio as gr
import pandas as pd
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def fetch(table, cols="*", limit=50, order_col="created_at"):
    try:
        r = (
            supabase.table(table)
            .select(cols)
            .order(order_col, desc=True)
            .limit(limit)
            .execute()
        )
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()
    except Exception as e:
        return pd.DataFrame({"error": [str(e)]})


def summary_stats():
    try:
        runs = supabase.table("ingestion_runs").select("recall_at_5,chunks_added").execute().data or []
        trades = supabase.table("trades").select("decision").execute().data or []
        evals = supabase.table("trade_evals").select("faithfulness").execute().data or []

        avg_recall = (
            sum(r["recall_at_5"] for r in runs if r["recall_at_5"]) / len(runs) if runs else 0
        )
        avg_faith = (
            sum(e["faithfulness"] for e in evals if e["faithfulness"]) / len(evals) if evals else 0
        )
        total_chunks = sum(r["chunks_added"] for r in runs if r["chunks_added"]) if runs else 0
        buy  = sum(1 for t in trades if t["decision"] == "BUY")
        sell = sum(1 for t in trades if t["decision"] == "SELL")
        hold = sum(1 for t in trades if t["decision"] == "HOLD")

        return (
            f"### Recall@5\n## {avg_recall:.1%}",
            f"### Faithfulness\n## {avg_faith:.1%}",
            f"### Total Chunks\n## {total_chunks:,}",
            f"### Trades\n## {buy} BUY · {sell} SELL · {hold} HOLD",
        )
    except Exception as e:
        return str(e), "—", "—", "—"


def refresh():
    stats = summary_stats()
    return (
        *stats,
        fetch("ingestion_runs"),
        fetch("trades"),
        fetch("trade_evals"),
        fetch("system_config", order_col="key"),
        fetch("healing_log"),
    )


with gr.Blocks(title="Vektor", theme=gr.themes.Monochrome()) as demo:
    gr.Markdown("# Vektor Trader")

    with gr.Row():
        recall_md  = gr.Markdown("### Recall@5\n## —")
        faith_md   = gr.Markdown("### Faithfulness\n## —")
        chunks_md  = gr.Markdown("### Total Chunks\n## —")
        trades_md  = gr.Markdown("### Trades\n## —")

    refresh_btn = gr.Button("Refresh", variant="primary")

    with gr.Tabs():
        with gr.Tab("Ingestion Runs"):
            ingestion_tbl = gr.DataFrame()
        with gr.Tab("Trades"):
            trades_tbl = gr.DataFrame()
        with gr.Tab("Trade Evals"):
            evals_tbl = gr.DataFrame()
        with gr.Tab("System Config"):
            config_tbl = gr.DataFrame()
        with gr.Tab("Healing Log"):
            healing_tbl = gr.DataFrame()

    outputs = [recall_md, faith_md, chunks_md, trades_md,
               ingestion_tbl, trades_tbl, evals_tbl, config_tbl, healing_tbl]

    refresh_btn.click(refresh, outputs=outputs)
    demo.load(refresh, outputs=outputs)

demo.launch()
