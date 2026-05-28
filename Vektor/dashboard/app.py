import os
from datetime import datetime
import gradio as gr
import yfinance as yf
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

SYMBOL_MAP = {
    "SPY": "SPY", "QQQ": "QQQ", "NVDA": "NVDA", "TSLA": "TSLA",
    "AAPL": "AAPL", "AMD": "AMD", "BTC": "BTC-USD", "ETH": "ETH-USD",
}

# ── Helpers ─────────────────────────────────────────────

def fmt_date(ts):
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        h  = dt.hour % 12 or 12
        ap = "am" if dt.hour < 12 else "pm"
        return f"{dt.strftime('%b')} {dt.day}, {h}:{dt.strftime('%M')}{ap}"
    except Exception:
        return ts[:10]

def get_prices(assets):
    prices = {}
    for asset in assets:
        sym = SYMBOL_MAP.get(asset, asset)
        try:
            h = yf.Ticker(sym).history(period="1d", interval="5m")
            if not h.empty:
                prices[asset] = round(float(h["Close"].iloc[-1]), 2)
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

def get_status(decision, entry, current, sl, tp):
    if decision == "HOLD": return "hold"
    if not entry or not current: return "unknown"
    if decision == "BUY":
        if sl and current <= sl: return "stopped"
        if tp and current >= tp: return "target"
    if decision == "SELL":
        if sl and current >= sl: return "stopped"
        if tp and current <= tp: return "target"
    pnl = calc_pnl(decision, entry, current)
    if pnl is None: return "open"
    return "winning" if pnl > 0 else "losing"

STATUS_ICON = {
    "stopped": "❌", "target": "✅", "winning": "📈",
    "losing": "📉", "open": "⏳", "hold": "—", "unknown": "?"
}

# ── HTML builders ────────────────────────────────────────

def stat_card(label, value, color=""):
    return f'''
    <div class="card">
        <div class="card-label">{label}</div>
        <div class="card-value {color}">{value}</div>
    </div>'''

def td(val, cls=""):
    return f'<td class="{cls}">{val if val is not None else "—"}</td>'

def render_table(headers, rows):
    ths = "".join(f"<th>{h}</th>" for h in headers)
    trs = ""
    for row in rows:
        trs += "<tr>" + "".join(td(c[0], c[1]) if isinstance(c, tuple) else td(c) for c in row) + "</tr>"
    if not rows:
        trs = f'<tr><td colspan="{len(headers)}" class="empty">No data yet</td></tr>'
    return f'''
    <div class="table-wrap">
        <table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>
    </div>'''

# ── Main render ──────────────────────────────────────────

def render():
    try:
        # fetch
        runs   = supabase.table("ingestion_runs").select("recall_at_5,chunks_added,created_at").order("created_at", desc=True).limit(20).execute().data or []
        all_trades = supabase.table("trades").select("*").order("created_at", desc=True).limit(100).execute().data or []
        evals  = supabase.table("trade_evals").select("faithfulness").execute().data or []
        config = supabase.table("system_config").select("key,value").execute().data or []

        # stats
        avg_recall   = sum(r["recall_at_5"] for r in runs if r["recall_at_5"]) / len(runs) if runs else 0
        avg_faith    = sum(e["faithfulness"] for e in evals if e["faithfulness"]) / len(evals) if evals else 0
        total_chunks = sum(r["chunks_added"] for r in runs if r["chunks_added"]) if runs else 0
        buy  = sum(1 for t in all_trades if t["decision"] == "BUY")
        sell = sum(1 for t in all_trades if t["decision"] == "SELL")
        hold = sum(1 for t in all_trades if t["decision"] == "HOLD")

        ri = "green" if avg_recall >= 0.9 else ("yellow" if avg_recall >= 0.7 else "red")
        fi = "green" if avg_faith  >= 0.8 else ("yellow" if avg_faith  >= 0.6 else "red")

        # performance
        active = [t for t in all_trades if t["decision"] != "HOLD"]
        assets = list({t["asset"] for t in active if t.get("asset")})
        prices = get_prices(assets) if assets else {}

        perf_rows = []
        pnl_vals  = []
        open_count = 0
        for t in active:
            cp     = prices.get(t["asset"])
            entry  = t.get("price_at_trade")
            sl     = t.get("stop_loss")
            tp     = t.get("take_profit")
            pnl    = calc_pnl(t["decision"], entry, cp)
            status = get_status(t["decision"], entry, cp, sl, tp)
            icon   = STATUS_ICON.get(status, "")
            pnl_str = f"{pnl:+.2f}%" if pnl is not None else "—"
            pnl_cls = "green" if (pnl or 0) > 0 else ("red" if (pnl or 0) < 0 else "")
            sig_cls = "buy" if t["decision"] == "BUY" else "sell"
            if pnl is not None: pnl_vals.append(pnl)
            if status in ("winning", "losing", "open"): open_count += 1
            perf_rows.append([
                t["asset"],
                (t["decision"], sig_cls),
                f"${entry:,.2f}" if entry else "—",
                f"${sl:,.2f}"    if sl    else "—",
                f"${tp:,.2f}"    if tp    else "—",
                f"${cp:,.2f}"    if cp    else "—",
                (pnl_str, pnl_cls),
                f"{icon} {status}",
                fmt_date(t.get("created_at")),
            ])

        total_pnl = round(sum(pnl_vals), 2) if pnl_vals else 0
        winners   = sum(1 for v in pnl_vals if v > 0)
        win_rate  = winners / len(pnl_vals) if pnl_vals else 0
        pnl_color = "green" if total_pnl > 0 else ("red" if total_pnl < 0 else "")

        perf_html = render_table(
            ["Asset","Signal","Entry","Stop","Target","Now","P&L","Status","When"],
            perf_rows
        )

        # all signals
        sig_rows = []
        for t in all_trades:
            sig_cls = "buy" if t["decision"] == "BUY" else ("sell" if t["decision"] == "SELL" else "muted")
            conf = f"{t['confidence']:.0%}" if t.get("confidence") else "—"
            entry = t.get("price_at_trade")
            sl    = t.get("stop_loss")
            tp    = t.get("take_profit")
            sig_rows.append([
                t["asset"],
                (t["decision"], sig_cls),
                conf,
                f"${entry:,.2f}" if entry else "—",
                f"${sl:,.2f}"    if sl    else "—",
                f"${tp:,.2f}"    if tp    else "—",
                fmt_date(t.get("created_at")),
            ])

        sigs_html = render_table(
            ["Asset","Signal","Conf","Entry","Stop","Target","When"],
            sig_rows
        )

        # ingestion runs
        ing_rows = []
        for r in runs:
            rc = r.get("recall_at_5") or 0
            rc_cls = "green" if rc >= 0.9 else ("yellow" if rc >= 0.7 else "red")
            ing_rows.append([
                str(r.get("chunks_added", "—")),
                (f"{rc:.1%}", rc_cls),
                fmt_date(r.get("created_at")),
            ])
        ing_html = render_table(["Chunks Added", "Recall@5", "When"], ing_rows)

        # config
        cfg_rows = [[r["key"], r["value"]] for r in config]
        cfg_html = render_table(["Key", "Value"], cfg_rows)

        return HTML_TEMPLATE.format(
            recall=f"{avg_recall:.1%}", recall_cls=ri,
            faith=f"{avg_faith:.1%}",  faith_cls=fi,
            chunks=f"{total_chunks:,}",
            signals=f"🟢 {buy} &nbsp; 🔴 {sell} &nbsp; ⚪ {hold}",
            total_pnl=f"{total_pnl:+.2f}%", pnl_cls=pnl_color,
            win_rate=f"{win_rate:.0%} ({winners}/{len(pnl_vals)})",
            open_count=str(open_count),
            perf_html=perf_html,
            sigs_html=sigs_html,
            ing_html=ing_html,
            cfg_html=cfg_html,
        )
    except Exception as e:
        return f"<p style='color:red;padding:20px'>Error: {e}</p>"


HTML_TEMPLATE = """
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
.vk {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #e8e8e8; padding: 16px; max-width: 960px; margin: 0 auto; }}
h1 {{ font-size: 22px; font-weight: 800; margin-bottom: 16px; letter-spacing: -0.5px; }}

/* stat grids */
.grid4, .grid3 {{ display: grid; gap: 10px; margin-bottom: 12px; }}
.grid4 {{ grid-template-columns: repeat(4, 1fr); }}
.grid3 {{ grid-template-columns: repeat(3, 1fr); }}
.card {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 14px; }}
.card-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: #666; margin-bottom: 6px; }}
.card-value {{ font-size: 22px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

/* divider */
hr {{ border: none; border-top: 1px solid #2a2a2a; margin: 12px 0; }}

/* tabs */
.tabs {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }}
.tab-btn {{ padding: 7px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500;
           background: #1a1a1a; border: 1px solid #2a2a2a; color: #888; transition: all 0.15s; }}
.tab-btn.active, .tab-btn:hover {{ background: #2a2a2a; color: #fff; border-color: #444; }}
.tab-pane {{ display: none; }}
.tab-pane.active {{ display: block; }}

/* table */
.table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 12px; border: 1px solid #2a2a2a; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
thead tr {{ background: #161616; }}
th {{ padding: 10px 14px; text-align: left; font-size: 10px; text-transform: uppercase;
     letter-spacing: 0.07em; color: #666; white-space: nowrap; border-bottom: 1px solid #2a2a2a; }}
td {{ padding: 10px 14px; white-space: nowrap; border-bottom: 1px solid #1e1e1e; }}
tr:last-child td {{ border-bottom: none; }}
tr:hover td {{ background: #1a1a1a; }}
.empty {{ text-align: center; color: #666; padding: 24px !important; }}

/* colors */
.green  {{ color: #22c55e; }}
.yellow {{ color: #eab308; }}
.red    {{ color: #ef4444; }}
.muted  {{ color: #888; }}
.buy    {{ color: #22c55e; font-weight: 700; }}
.sell   {{ color: #ef4444; font-weight: 700; }}

/* mobile */
@media (max-width: 580px) {{
    .grid4 {{ grid-template-columns: repeat(2, 1fr); }}
    .grid3 {{ grid-template-columns: repeat(2, 1fr); }}
    .card-value {{ font-size: 18px; }}
    h1 {{ font-size: 18px; }}
}}
</style>

<div class="vk">
  <h1>📊 Vektor Trader</h1>

  <div class="grid4">
    {stat_card_recall}
    {stat_card_faith}
    {stat_card_chunks}
    {stat_card_signals}
  </div>

  <hr>

  <div class="grid3">
    {stat_card_pnl}
    {stat_card_winrate}
    {stat_card_open}
  </div>

  <div class="tabs">
    <button class="tab-btn active" onclick="showTab('perf',this)">📈 Performance</button>
    <button class="tab-btn" onclick="showTab('sigs',this)">📋 All Signals</button>
    <button class="tab-btn" onclick="showTab('ing',this)">🗄️ Ingestion</button>
    <button class="tab-btn" onclick="showTab('cfg',this)">⚙️ System</button>
  </div>

  <div id="tab-perf" class="tab-pane active">{perf_html}</div>
  <div id="tab-sigs" class="tab-pane">{sigs_html}</div>
  <div id="tab-ing"  class="tab-pane">{ing_html}</div>
  <div id="tab-cfg"  class="tab-pane">{cfg_html}</div>
</div>

<script>
function showTab(name, btn) {{
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
}}
</script>
"""

# Patch: inject stat cards into template
_orig_render = render
def render():
    try:
        runs   = supabase.table("ingestion_runs").select("recall_at_5,chunks_added,created_at").order("created_at", desc=True).limit(20).execute().data or []
        all_trades = supabase.table("trades").select("*").order("created_at", desc=True).limit(100).execute().data or []
        evals  = supabase.table("trade_evals").select("faithfulness").execute().data or []
        config = supabase.table("system_config").select("key,value").execute().data or []

        avg_recall   = sum(r["recall_at_5"] for r in runs if r["recall_at_5"]) / len(runs) if runs else 0
        avg_faith    = sum(e["faithfulness"] for e in evals if e["faithfulness"]) / len(evals) if evals else 0
        total_chunks = sum(r["chunks_added"] for r in runs if r["chunks_added"]) if runs else 0
        buy  = sum(1 for t in all_trades if t["decision"] == "BUY")
        sell = sum(1 for t in all_trades if t["decision"] == "SELL")
        hold = sum(1 for t in all_trades if t["decision"] == "HOLD")
        ri = "green" if avg_recall >= 0.9 else ("yellow" if avg_recall >= 0.7 else "red")
        fi = "green" if avg_faith  >= 0.8 else ("yellow" if avg_faith  >= 0.6 else "red")

        active = [t for t in all_trades if t["decision"] != "HOLD"]
        assets = list({t["asset"] for t in active if t.get("asset")})
        prices = get_prices(assets) if assets else {}

        perf_rows, pnl_vals, open_count = [], [], 0
        for t in active:
            cp     = prices.get(t["asset"])
            entry  = t.get("price_at_trade")
            sl     = t.get("stop_loss")
            tp     = t.get("take_profit")
            pnl    = calc_pnl(t["decision"], entry, cp)
            status = get_status(t["decision"], entry, cp, sl, tp)
            icon   = STATUS_ICON.get(status, "")
            pnl_str = f"{pnl:+.2f}%" if pnl is not None else "—"
            pnl_cls = "green" if (pnl or 0) > 0 else ("red" if (pnl or 0) < 0 else "")
            sig_cls = "buy" if t["decision"] == "BUY" else "sell"
            if pnl is not None: pnl_vals.append(pnl)
            if status in ("winning", "losing", "open"): open_count += 1
            perf_rows.append([
                t["asset"], (t["decision"], sig_cls),
                f"${entry:,.2f}" if entry else "—",
                f"${sl:,.2f}"    if sl    else "—",
                f"${tp:,.2f}"    if tp    else "—",
                f"${cp:,.2f}"    if cp    else "—",
                (pnl_str, pnl_cls), f"{icon} {status}",
                fmt_date(t.get("created_at")),
            ])

        total_pnl = round(sum(pnl_vals), 2) if pnl_vals else 0
        winners   = sum(1 for v in pnl_vals if v > 0)
        win_rate  = winners / len(pnl_vals) if pnl_vals else 0
        pnl_color = "green" if total_pnl > 0 else ("red" if total_pnl < 0 else "")

        sig_rows = []
        for t in all_trades:
            sig_cls = "buy" if t["decision"] == "BUY" else ("sell" if t["decision"] == "SELL" else "muted")
            conf  = f"{t['confidence']:.0%}" if t.get("confidence") else "—"
            entry = t.get("price_at_trade")
            sl    = t.get("stop_loss")
            tp    = t.get("take_profit")
            sig_rows.append([
                t["asset"], (t["decision"], sig_cls), conf,
                f"${entry:,.2f}" if entry else "—",
                f"${sl:,.2f}"    if sl    else "—",
                f"${tp:,.2f}"    if tp    else "—",
                fmt_date(t.get("created_at")),
            ])

        ing_rows = []
        for r in runs:
            rc = r.get("recall_at_5") or 0
            rc_cls = "green" if rc >= 0.9 else ("yellow" if rc >= 0.7 else "red")
            ing_rows.append([str(r.get("chunks_added","—")), (f"{rc:.1%}", rc_cls), fmt_date(r.get("created_at"))])

        cfg_rows = [[r["key"], r["value"]] for r in config]

        html = HTML_TEMPLATE.replace("{stat_card_recall}",   stat_card("Recall@5",     f'<span class="{ri}">{avg_recall:.1%}</span>'))
        html = html.replace("{stat_card_faith}",    stat_card("Faithfulness", f'<span class="{fi}">{avg_faith:.1%}</span>'))
        html = html.replace("{stat_card_chunks}",   stat_card("Knowledge",    f"{total_chunks:,} chunks"))
        html = html.replace("{stat_card_signals}",  stat_card("Signals",      f'<span class="buy">{buy} BUY</span> · <span class="sell">{sell} SELL</span> · <span class="muted">{hold}</span>'))
        html = html.replace("{stat_card_pnl}",      stat_card("Total P&L",    f'<span class="{pnl_color}">{total_pnl:+.2f}%</span>'))
        html = html.replace("{stat_card_winrate}",  stat_card("Win Rate",     f"{win_rate:.0%} ({winners}/{len(pnl_vals)})"))
        html = html.replace("{stat_card_open}",     stat_card("Open Trades",  str(open_count)))
        html = html.replace("{perf_html}", render_table(["Asset","Signal","Entry","Stop","Target","Now","P&L","Status","When"], perf_rows))
        html = html.replace("{sigs_html}", render_table(["Asset","Signal","Conf","Entry","Stop","Target","When"], sig_rows))
        html = html.replace("{ing_html}",  render_table(["Chunks","Recall@5","When"], ing_rows))
        html = html.replace("{cfg_html}",  render_table(["Key","Value"], cfg_rows))
        return html

    except Exception as e:
        import traceback
        return f"<p style='color:red;padding:20px'>Error: {e}<br><pre>{traceback.format_exc()}</pre></p>"


# ── Gradio shell (just a container + refresh button) ────
SHELL_CSS = """
.gradio-container { max-width: 100% !important; padding: 0 !important; background: #111 !important; }
.gr-button { margin: 8px 16px !important; }
footer { display: none !important; }
"""

with gr.Blocks(css=SHELL_CSS, theme=gr.themes.Monochrome()) as demo:
    dashboard = gr.HTML()
    refresh_btn = gr.Button("🔄 Refresh", variant="primary")
    refresh_btn.click(render, outputs=dashboard)
    demo.load(render, outputs=dashboard)

demo.launch()
