import os
from datetime import datetime
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
body, .gradio-container {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
.gradio-container {
    max-width: 960px !important;
    margin: 0 auto !important;
    padding: 12px !important;
}
footer { display: none !important; }

/* ── stat grid ── */
.stat-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 8px;
}
.stat-grid-2 {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-bottom: 8px;
}
.stat-card {
    background: #1c1c1c;
    border: 1px solid #2e2e2e;
    border-radius: 12px;
    padding: 12px 14px;
    overflow: hidden;
}
.stat-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #888;
    margin-bottom: 4px;
    white-space: nowrap;
}
.stat-value {
    font-size: 22px;
    font-weight: 700;
    color: #fff;
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* ── scrollable tables ── */
.gr-dataframe, .table-wrap, [data-testid="dataframe"] {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch !important;
}
.gr-dataframe table, .dataframe {
    min-width: max-content !important;
}
.gr-dataframe td, .gr-dataframe th {
    white-space: nowrap !important;
    padding: 6px 12px !important;
    font-size: 13px !important;
}

/* ── refresh button ── */
.refresh-btn {
    border-radius: 10px !important;
    font-weight: 600 !important;
    margin: 8px 0 !important;
    width: 100% !important;
}

/* ── mobile ── */
@media (max-width: 600px) {
    .gradio-container { padding: 8px !important; }
    .stat-grid  { grid-template-columns: repeat(2, 1fr) !important; }
    .stat-grid-2 { grid-template-columns: repeat(2, 1fr) !important; }
    .stat-value { font-size: 18px !important; }
    .stat-label { font-size: 9px !important; }
}
"""


# ── Helpers ─────────────────────────────────────────────

def fmt_date(ts):
    """'2026-05-27T14:30:00' → 'May 27, 2:30pm'"""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        month = dt.strftime("%b")
        day   = dt.day
        hour  = dt.hour % 12 or 12
        mins  = dt.strftime("%M")
        ampm  = "am" if dt.hour < 12 else "pm"
        return f"{month} {day}, {hour}:{mins}{ampm}"
    except Exception:
        return ts[:10]


def card(label, value):
    return (
        f'<div class="stat-card">'
        f'<div class="stat-label">{label}</div>'
        f'<div class="stat-value">{value}</div>'
        f'</div>'
    )


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


# ── Data functions ───────────────────────────────────────

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

        ri = "🟢" if avg_recall >= 0.9 else ("🟡" if avg_recall >= 0.7 else "🔴")
        fi = "🟢" if avg_faith  >= 0.8 else ("🟡" if avg_faith  >= 0.6 else "🔴")

        html  = '<div class="stat-grid">'
        html += card("Recall@5",     f"{ri} {avg_recall:.1%}")
        html += card("Faithfulness", f"{fi} {avg_faith:.1%}")
        html += card("Knowledge",    f"{total_chunks:,}")
        html += card("Signals",      f"🟢{buy} 🔴{sell} ⚪{hold}")
        html += "</div>"
        return html
    except Exception as e:
        return f"<p style='color:red'>Error: {e}</p>"


def performance_table():
    _empty_pnl = (
        '<div class="stat-grid-2">'
        + card("Total P&L", "—")
        + card("Win Rate",  "—")
        + card("Open",      "—")
        + "</div>"
    )
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
            return pd.DataFrame(), _empty_pnl

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
                "Entry":    entry,
                "Stop":     sl,
                "Target":   tp,
                "Now":      cp,
                "P&L":      f"{pnl:+.2f}%" if pnl is not None else "—",
                "Status":   status,
                "When":     fmt_date(t.get("created_at")),
            })

        df = pd.DataFrame(rows)

        pnl_vals   = [float(r["P&L"].replace("%", "")) for r in rows if r["P&L"] != "—"]
        total_pnl  = round(sum(pnl_vals), 2) if pnl_vals else 0
        winners    = sum(1 for v in pnl_vals if v > 0)
        win_rate   = winners / len(pnl_vals) if pnl_vals else 0
        open_count = sum(1 for r in rows if any(x in r["Status"] for x in ["open", "winning", "losing"]))

        color = "🟢" if total_pnl > 0 else ("🔴" if total_pnl < 0 else "⚪")

        pnl_html  = '<div class="stat-grid-2">'
        pnl_html += card("Total P&L", f"{color} {total_pnl:+.2f}%")
        pnl_html += card("Win Rate",  f"{win_rate:.0%} ({winners}/{len(pnl_vals)})")
        pnl_html += card("Open",      f"{open_count}")
        pnl_html += "</div>"

        return df, pnl_html
    except Exception as e:
        return pd.DataFrame({"error": [str(e)]}), _empty_pnl


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
                "Asset":   t["asset"],
                "Signal":  t["decision"],
                "Conf":    f"{t['confidence']:.0%}" if t.get("confidence") else "—",
                "Entry":   t.get("price_at_trade"),
                "Stop":    t.get("stop_loss"),
                "Target":  t.get("take_profit"),
                "When":    fmt_date(t.get("created_at")),
            })
        return pd.DataFrame(rows)
    except Exception as e:
        return pd.DataFrame({"error": [str(e)]})


def refresh():
    stats_html      = summary_stats()
    perf_df, pnl_html = performance_table()
    return (
        stats_html,
        pnl_html,
        perf_df,
        recent_trades_table(),
        fetch("ingestion_runs", cols="id,chunks_added,recall_at_5,created_at"),
        fetch("system_config", order_col="key"),
    )


# ── Layout ──────────────────────────────────────────────
with gr.Blocks(title="Vektor", theme=gr.themes.Monochrome(), css=CSS) as demo:

    gr.Markdown("# 📊 Vektor Trader")

    stats_html = gr.HTML()
    pnl_html   = gr.HTML()

    refresh_btn = gr.Button("🔄 Refresh", variant="primary", elem_classes=["refresh-btn"])

    with gr.Tabs():
        with gr.Tab("📈 Performance"):
            gr.Markdown("*BUY/SELL signals vs current price.*")
            perf_tbl = gr.DataFrame(wrap=False)

        with gr.Tab("📋 All Signals"):
            gr.Markdown("*Every signal including HOLDs.*")
            trades_tbl = gr.DataFrame(wrap=False)

        with gr.Tab("🗄️ Ingestion"):
            gr.Markdown("*News & market data — runs every 4h.*")
            ingestion_tbl = gr.DataFrame(wrap=False)

        with gr.Tab("⚙️ System"):
            gr.Markdown("*Config values for trader & healer.*")
            config_tbl = gr.DataFrame(wrap=False)

    outputs = [
        stats_html, pnl_html,
        perf_tbl, trades_tbl, ingestion_tbl, config_tbl,
    ]

    refresh_btn.click(refresh, outputs=outputs)
    demo.load(refresh, outputs=outputs)

demo.launch()
