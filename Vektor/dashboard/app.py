import os
import gradio as gr
import pandas as pd
import yfinance as yf
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

SYMBOL_MAP = {
    "SPY": "SPY", "QQQ": "QQQ", "NVDA": "NVDA", "TSLA": "TSLA",
    "AAPL": "AAPL", "AMD": "AMD", "BTC": "BTC-USD", "ETH": "ETH-USD",
}


def fetch(table, cols="*", limit=50, order_col="created_at"):
    try:
        r = supabase.table(table).select(cols).order(order_col, desc=True).limit(limit).execute()
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()
    except Exception as e:
        return pd.DataFrame({"error": [str(e)]})


def get_current_prices(assets):
    prices = {}
    for asset in assets:
        symbol = SYMBOL_MAP.get(asset, asset)
        try:
            hist = yf.Ticker(symbol).history(period="1d", interval="5m")
            if not hist.empty:
                prices[asset] = round(float(hist["Close"].iloc[-1]), 4)
        except Exception:
            pass
    return prices


def calc_pnl(row, current_price):
    if not row["price_at_trade"] or not current_price or row["decision"] == "HOLD":
        return None
    if row["decision"] == "BUY":
        return round((current_price - row["price_at_trade"]) / row["price_at_trade"] * 100, 2)
    if row["decision"] == "SELL":
        return round((row["price_at_trade"] - current_price) / row["price_at_trade"] * 100, 2)
    return None


def get_status(row, current_price):
    if row["decision"] == "HOLD":
        return "hold"
    if not row["price_at_trade"] or not current_price:
        return "unknown"
    sl = row.get("stop_loss")
    tp = row.get("take_profit")
    if row["decision"] == "BUY":
        if sl and current_price <= sl:   return "stopped ❌"
        if tp and current_price >= tp:   return "target ✅"
    if row["decision"] == "SELL":
        if sl and current_price >= sl:   return "stopped ❌"
        if tp and current_price <= tp:   return "target ✅"
    pnl = calc_pnl(row, current_price)
    if pnl is None:                      return "open"
    return "open 📈" if pnl > 0 else "open 📉"


def performance_table():
    try:
        trades = supabase.table("trades").select("*").neq("decision", "HOLD").order("created_at", desc=True).limit(100).execute().data or []
        if not trades:
            return pd.DataFrame(), "### Total P&L\n## —", "### Win Rate\n## —", "### Open Trades\n## —"

        assets = list({t["asset"] for t in trades if t.get("asset")})
        prices = get_current_prices(assets)

        rows = []
        for t in trades:
            cp = prices.get(t["asset"])
            pnl = calc_pnl(t, cp)
            status = get_status(t, cp)
            rows.append({
                "asset":        t["asset"],
                "decision":     t["decision"],
                "entry":        t["price_at_trade"],
                "stop_loss":    t.get("stop_loss"),
                "take_profit":  t.get("take_profit"),
                "current":      cp,
                "pnl_%":        pnl,
                "status":       status,
                "time":         t["created_at"][:16] if t.get("created_at") else "",
            })

        df = pd.DataFrame(rows)

        actionable = [r for r in rows if r["pnl_%"] is not None]
        total_pnl   = round(sum(r["pnl_%"] for r in actionable), 2) if actionable else 0
        winners     = sum(1 for r in actionable if r["pnl_%"] > 0)
        win_rate    = winners / len(actionable) if actionable else 0
        open_count  = sum(1 for r in rows if "open" in r["status"])

        return (
            df,
            f"### Total P&L\n## {total_pnl:+.2f}%",
            f"### Win Rate\n## {win_rate:.0%}  ({winners}/{len(actionable)})",
            f"### Open Trades\n## {open_count}",
        )
    except Exception as e:
        return pd.DataFrame({"error": [str(e)]}), "—", "—", "—"


def summary_stats():
    try:
        runs   = supabase.table("ingestion_runs").select("recall_at_5,chunks_added").execute().data or []
        trades = supabase.table("trades").select("decision").execute().data or []
        evals  = supabase.table("trade_evals").select("faithfulness").execute().data or []

        avg_recall    = sum(r["recall_at_5"] for r in runs if r["recall_at_5"]) / len(runs) if runs else 0
        avg_faith     = sum(e["faithfulness"] for e in evals if e["faithfulness"]) / len(evals) if evals else 0
        total_chunks  = sum(r["chunks_added"] for r in runs if r["chunks_added"]) if runs else 0
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
    perf  = performance_table()
    return (
        *stats,
        perf[1], perf[2], perf[3],
        perf[0],
        fetch("trades"),
        fetch("ingestion_runs"),
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

    gr.Markdown("---")

    with gr.Row():
        pnl_md    = gr.Markdown("### Total P&L\n## —")
        winrate_md = gr.Markdown("### Win Rate\n## —")
        open_md   = gr.Markdown("### Open Trades\n## —")

    refresh_btn = gr.Button("Refresh", variant="primary")

    with gr.Tabs():
        with gr.Tab("Performance"):
            perf_tbl = gr.DataFrame()
        with gr.Tab("Trades"):
            trades_tbl = gr.DataFrame()
        with gr.Tab("Ingestion Runs"):
            ingestion_tbl = gr.DataFrame()
        with gr.Tab("Trade Evals"):
            evals_tbl = gr.DataFrame()
        with gr.Tab("System Config"):
            config_tbl = gr.DataFrame()
        with gr.Tab("Healing Log"):
            healing_tbl = gr.DataFrame()

    outputs = [
        recall_md, faith_md, chunks_md, trades_md,
        pnl_md, winrate_md, open_md,
        perf_tbl, trades_tbl, ingestion_tbl, evals_tbl, config_tbl, healing_tbl,
    ]

    refresh_btn.click(refresh, outputs=outputs)
    demo.load(refresh, outputs=outputs)

demo.launch()
