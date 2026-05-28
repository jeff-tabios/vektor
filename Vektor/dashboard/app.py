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

CSS = """
body, .gradio-container { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important; }
.gradio-container { max-width: 960px !important; margin: 0 auto !important; padding: 12px !important; }
.refresh-btn { border-radius: 10px !important; font-weight: 600 !important; margin: 8px 0 !important; }
footer { display: none !important; }

@media (max-width: 640px) {
    .gradio-container { padding: 6px !important; }
    .gr-markdown h2 { font-size: 20px !important; }
    .gr-markdown h3 { font-size: 11px !important; }
}
"""


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


def calc_pnl(decision, entry, current):
    if not entry or not current or decision == "HOLD":
        return None
    if decision == "BUY":
        return round((current - entry) / entry * 100, 2)
    if decision == "SELL":
        return round((entry - current) / entry * 100, 2)
    return None


def get_status(decision, entry, current, sl, tp):
    if decision == "HOLD":
        return "— hold"
    if not entry or not current:
        return "? unknown"
    if decision == "BUY":
        if sl and current <= sl:  return "❌ stopped"
        if tp and current >= tp:  return "✅ target"
    if decision == "SELL":
        if sl and current >= sl:  return "❌ stopped"
        if tp and current <= tp:  return "✅ target"
    pnl = calc_pnl(decision, entry, current)
    if pnl is None:               return "⏳ open"
    return "📈 winning" if pnl > 0 else "📉 losing"


def performance_table():
    try:
        trades = (
            supabase.table("trades")
            .select("*")
            .neq("decision", "HOLD")
            .order("created_at", desc=True)
            .limit(100)
            .execute()
            .data or []
        )
        if not trades:
            return pd.DataFrame(), "### Total P&L\n## —", "### Win Rate\n## —", "### Open\n## —"

        assets = list({t["asset"] for t in trades if t.get("asset")})
        prices = get_current_prices(assets)

        rows = []
        for t in trades:
            cp     = prices.get(t["asset"])
            entry  = t.get("price_at_trade")
            sl     = t.get("stop_loss")
            tp     = t.get("take_profit")
            pnl    = calc_pnl(t["decision"], entry, cp)
            status = get_status(t["decision"], entry, cp, sl, tp)
            rows.append({
                "Asset":    t["asset"],
                "Signal":   t["decision"],
                "Entry $":  entry,
                "Stop $":   sl,
                "Target $": tp,
                "Now $":    cp,
                "P&L %":    f"{pnl:+.2f}%" if pnl is not None else "—",
                "Status":   status,
                "Date":     t["created_at"][:10] if t.get("created_at") else "",
            })

        df = pd.DataFrame(rows)

        pnl_vals   = [float(r["P&L %"].replace("%", "")) for r in rows if r["P&L %"] != "—"]
        total_pnl  = round(sum(pnl_vals), 2) if pnl_vals else 0
        winners    = sum(1 for v in pnl_vals if v > 0)
        win_rate   = winners / len(pnl_vals) if pnl_vals else 0
        open_count = sum(1 for r in rows if any(x in r["Status"] for x in ["open", "winning", "losing"]))

        color = "🟢" if total_pnl > 0 else ("🔴" if total_pnl < 0 else "⚪")
        return (
            df,
            f"### Total P&L\n## {color} {total_pnl:+.2f}%",
            f"### Win Rate\n## {win_rate:.0%}  ({winners}/{len(pnl_vals)})",
            f"### Open\n## {open_count} trades",
        )
    except Exception as e:
        return pd.DataFrame({"error": [str(e)]}), "—", "—", "—"


def summary_stats():
    try:
        runs   = supabase.table("ingestion_runs").select("recall_at_5,chunks_added").execute().data or []
        trades = supabase.table("trades").select("decision").execute().data or []
        evals  = supabase.table("trade_evals").select("faithfulness").execute().data or []

        avg_recall   = sum(r["recall_at_5"] for r in runs if r["recall_at_5"]) / len(runs) if runs else 0
        avg_faith    = sum(e["faithfulness"] for e in evals if e["faithfulness"]) / len(evals) if evals else 0
        total_chunks = sum(r["chunks_added"] for r in runs if r["chunks_added"]) if runs else 0
        buy  = sum(1 for t in trades if t["decision"] == "BUY")
        sell = sum(1 for t in trades if t["decision"] == "SELL")
        hold = sum(1 for t in trades if t["decision"] == "HOLD")

        recall_icon = "🟢" if avg_recall >= 0.9 else ("🟡" if avg_recall >= 0.7 else "🔴")
        faith_icon  = "🟢" if avg_faith  >= 0.8 else ("🟡" if avg_faith  >= 0.6 else "🔴")

        return (
            f"### Recall@5\n## {recall_icon} {avg_recall:.1%}",
            f"### Faithfulness\n## {faith_icon} {avg_faith:.1%}",
            f"### Knowledge\n## {total_chunks:,} chunks",
            f"### Signals\n## 🟢 {buy} · 🔴 {sell} · ⚪ {hold}",
        )
    except Exception as e:
        return str(e), "—", "—", "—"


def recent_trades_table():
    try:
        trades = (
            supabase.table("trades")
            .select("asset,decision,confidence,price_at_trade,stop_loss,take_profit,created_at")
            .order("created_at", desc=True)
            .limit(30)
            .execute()
            .data or []
        )
        if not trades:
            return pd.DataFrame()
        rows = []
        for t in trades:
            rows.append({
                "Asset":      t["asset"],
                "Signal":     t["decision"],
                "Conf":       f"{t['confidence']:.0%}" if t.get("confidence") else "—",
                "Entry $":    t.get("price_at_trade"),
                "Stop $":     t.get("stop_loss"),
                "Target $":   t.get("take_profit"),
                "Date":       t["created_at"][:16].replace("T", " ") if t.get("created_at") else "",
            })
        return pd.DataFrame(rows)
    except Exception as e:
        return pd.DataFrame({"error": [str(e)]})


def refresh():
    stats = summary_stats()
    perf  = performance_table()
    return (
        stats[0], stats[1], stats[2], stats[3],
        perf[1], perf[2], perf[3],
        perf[0],
        recent_trades_table(),
        fetch("ingestion_runs", cols="id,chunks_added,recall_at_5,created_at"),
        fetch("system_config", order_col="key"),
    )


# ── Layout ──────────────────────────────────────────────
with gr.Blocks(title="Vektor", theme=gr.themes.Monochrome(), css=CSS) as demo:

    gr.Markdown("# 📊 Vektor Trader")

    with gr.Row(equal_height=True):
        recall_md  = gr.Markdown("### Recall@5\n## —")
        faith_md   = gr.Markdown("### Faithfulness\n## —")
        chunks_md  = gr.Markdown("### Knowledge\n## —")
        signals_md = gr.Markdown("### Signals\n## —")

    gr.HTML("<hr style='border:none;border-top:1px solid #333;margin:4px 0'>")

    with gr.Row(equal_height=True):
        pnl_md     = gr.Markdown("### Total P&L\n## —")
        winrate_md = gr.Markdown("### Win Rate\n## —")
        open_md    = gr.Markdown("### Open\n## —")

    refresh_btn = gr.Button("🔄 Refresh", variant="primary", elem_classes=["refresh-btn"])

    with gr.Tabs():
        with gr.Tab("📈 Performance"):
            gr.Markdown("*Active BUY/SELL signals tracked against current price.*")
            perf_tbl = gr.DataFrame(wrap=True)

        with gr.Tab("📋 All Signals"):
            gr.Markdown("*Every signal logged including HOLDs.*")
            trades_tbl = gr.DataFrame(wrap=True)

        with gr.Tab("🗄️ Ingestion"):
            gr.Markdown("*News & market data runs — every 4 hours.*")
            ingestion_tbl = gr.DataFrame(wrap=True)

        with gr.Tab("⚙️ System"):
            gr.Markdown("*Config values controlling the trader and self-healer.*")
            config_tbl = gr.DataFrame(wrap=True)

    outputs = [
        recall_md, faith_md, chunks_md, signals_md,
        pnl_md, winrate_md, open_md,
        perf_tbl, trades_tbl, ingestion_tbl, config_tbl,
    ]

    refresh_btn.click(refresh, outputs=outputs)
    demo.load(refresh, outputs=outputs)

demo.launch()
