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

STATUS_ICON = {
    "stopped": "❌", "target": "✅", "winning": "📈",
    "losing": "📉", "open": "⏳", "hold": "—", "unknown": "?"
}

CSS = """
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
.vk{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#e8e8e8;padding:16px;max-width:960px;margin:0 auto}
h1{font-size:22px;font-weight:800;margin-bottom:16px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px}
.card{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:14px;min-width:0}
.card-label{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#666;margin-bottom:6px}
.card-value{font-size:22px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
hr{border:none;border-top:1px solid #2a2a2a;margin:12px 0}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.tab-btn{padding:7px 16px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;background:#1a1a1a;border:1px solid #2a2a2a;color:#888}
.tab-btn.on{background:#2a2a2a;color:#fff;border-color:#444}
.pane{display:none}
.pane.on{display:block}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:12px;border:1px solid #2a2a2a}
table{width:100%;border-collapse:collapse;font-size:13px}
thead tr{background:#161616}
th{padding:10px 14px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:#666;white-space:nowrap;border-bottom:1px solid #2a2a2a}
td{padding:10px 14px;white-space:nowrap;border-bottom:1px solid #1e1e1e}
tr:last-child td{border-bottom:none}
tr:hover td{background:#1a1a1a}
.empty{text-align:center;color:#666;padding:24px!important}
.g{color:#22c55e}.y{color:#eab308}.r{color:#ef4444}.m{color:#888}
.buy{color:#22c55e;font-weight:700}.sell{color:#ef4444;font-weight:700}
@media(max-width:580px){
  .grid4{grid-template-columns:repeat(2,1fr)}
  .grid3{grid-template-columns:repeat(2,1fr)}
  .card-value{font-size:18px}
  h1{font-size:18px}
}
</style>
"""

JS = """
<script>
function tab(name,btn){
  document.querySelectorAll('.pane').forEach(function(p){p.classList.remove('on')});
  document.querySelectorAll('.tab-btn').forEach(function(b){b.classList.remove('on')});
  document.getElementById('p-'+name).classList.add('on');
  btn.classList.add('on');
}
</script>
"""


def fmt_date(ts):
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        h  = dt.hour % 12 or 12
        ap = "am" if dt.hour < 12 else "pm"
        return "{} {}, {}:{} {}".format(dt.strftime("%b"), dt.day, h, dt.strftime("%M"), ap)
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
    return None


def get_status(decision, entry, current, sl, tp):
    if decision == "HOLD":
        return "hold"
    if not entry or not current:
        return "unknown"
    if decision == "BUY":
        if sl and current <= sl:
            return "stopped"
        if tp and current >= tp:
            return "target"
    if decision == "SELL":
        if sl and current >= sl:
            return "stopped"
        if tp and current <= tp:
            return "target"
    pnl = calc_pnl(decision, entry, current)
    if pnl is None:
        return "open"
    return "winning" if pnl > 0 else "losing"


def card(label, value_html):
    return (
        '<div class="card">'
        '<div class="card-label">' + label + '</div>'
        '<div class="card-value">' + value_html + '</div>'
        '</div>'
    )


def make_table(headers, rows):
    ths = "".join("<th>" + h + "</th>" for h in headers)
    if not rows:
        return (
            '<div class="tw"><table>'
            '<thead><tr>' + ths + '</tr></thead>'
            '<tbody><tr><td class="empty" colspan="' + str(len(headers)) + '">No data yet — check back after the next trading session.</td></tr></tbody>'
            '</table></div>'
        )
    trs = ""
    for row in rows:
        cells = ""
        for c in row:
            if isinstance(c, tuple):
                cells += '<td class="' + c[1] + '">' + str(c[0]) + "</td>"
            else:
                cells += "<td>" + (str(c) if c is not None else "—") + "</td>"
        trs += "<tr>" + cells + "</tr>"
    return (
        '<div class="tw"><table>'
        '<thead><tr>' + ths + '</tr></thead>'
        '<tbody>' + trs + '</tbody>'
        '</table></div>'
    )


def render():
    try:
        runs       = supabase.table("ingestion_runs").select("recall_at_5,chunks_added,created_at").order("created_at", desc=True).limit(20).execute().data or []
        all_trades = supabase.table("trades").select("*").order("created_at", desc=True).limit(100).execute().data or []
        evals      = supabase.table("trade_evals").select("faithfulness").execute().data or []
        config     = supabase.table("system_config").select("key,value").execute().data or []

        avg_recall   = sum(r["recall_at_5"] for r in runs if r["recall_at_5"]) / len(runs) if runs else 0
        avg_faith    = sum(e["faithfulness"] for e in evals if e["faithfulness"]) / len(evals) if evals else 0
        total_chunks = sum(r["chunks_added"] for r in runs if r["chunks_added"]) if runs else 0
        buy   = sum(1 for t in all_trades if t["decision"] == "BUY")
        sell  = sum(1 for t in all_trades if t["decision"] == "SELL")
        hold  = sum(1 for t in all_trades if t["decision"] == "HOLD")

        ri = "g" if avg_recall >= 0.9 else ("y" if avg_recall >= 0.7 else "r")
        fi = "g" if avg_faith  >= 0.8 else ("y" if avg_faith  >= 0.6 else "r")

        # --- performance tab ---
        active = [t for t in all_trades if t["decision"] != "HOLD"]
        prices = get_prices(list({t["asset"] for t in active if t.get("asset")})) if active else {}

        perf_rows, pnl_vals, open_count = [], [], 0
        for t in active:
            cp     = prices.get(t["asset"])
            entry  = t.get("price_at_trade")
            sl     = t.get("stop_loss")
            tp     = t.get("take_profit")
            pnl    = calc_pnl(t["decision"], entry, cp)
            status = get_status(t["decision"], entry, cp, sl, tp)
            icon   = STATUS_ICON.get(status, "")
            pnl_s  = ("{:+.2f}%".format(pnl)) if pnl is not None else "—"
            pc     = "g" if (pnl or 0) > 0 else ("r" if (pnl or 0) < 0 else "")
            sc     = "buy" if t["decision"] == "BUY" else "sell"
            if pnl is not None:
                pnl_vals.append(pnl)
            if status in ("winning", "losing", "open"):
                open_count += 1
            perf_rows.append([
                t["asset"], (t["decision"], sc),
                ("${:,.2f}".format(entry) if entry else "—"),
                ("${:,.2f}".format(sl)    if sl    else "—"),
                ("${:,.2f}".format(tp)    if tp    else "—"),
                ("${:,.2f}".format(cp)    if cp    else "—"),
                (pnl_s, pc),
                icon + " " + status,
                fmt_date(t.get("created_at")),
            ])

        total_pnl = round(sum(pnl_vals), 2) if pnl_vals else 0
        winners   = sum(1 for v in pnl_vals if v > 0)
        win_rate  = winners / len(pnl_vals) if pnl_vals else 0
        pc        = "g" if total_pnl > 0 else ("r" if total_pnl < 0 else "")

        # --- all signals tab ---
        sig_rows = []
        for t in all_trades:
            sc    = "buy" if t["decision"] == "BUY" else ("sell" if t["decision"] == "SELL" else "m")
            conf  = ("{:.0%}".format(t["confidence"])) if t.get("confidence") else "—"
            entry = t.get("price_at_trade")
            sl    = t.get("stop_loss")
            tp    = t.get("take_profit")
            sig_rows.append([
                t["asset"], (t["decision"], sc), conf,
                ("${:,.2f}".format(entry) if entry else "—"),
                ("${:,.2f}".format(sl)    if sl    else "—"),
                ("${:,.2f}".format(tp)    if tp    else "—"),
                fmt_date(t.get("created_at")),
            ])

        # --- ingestion tab ---
        ing_rows = []
        for r in runs:
            rc     = r.get("recall_at_5") or 0
            rc_cls = "g" if rc >= 0.9 else ("y" if rc >= 0.7 else "r")
            ing_rows.append([
                str(r.get("chunks_added", "—")),
                ("{:.1%}".format(rc), rc_cls),
                fmt_date(r.get("created_at")),
            ])

        cfg_rows = [[r["key"], r["value"]] for r in config]

        # --- assemble ---
        top_stats = (
            '<div class="grid4">'
            + card("Recall@5",     '<span class="' + ri + '">' + "{:.1%}".format(avg_recall) + '</span>')
            + card("Faithfulness", '<span class="' + fi + '">' + "{:.1%}".format(avg_faith)  + '</span>')
            + card("Knowledge",    "{:,} chunks".format(total_chunks))
            + card("Signals",      '<span class="buy">' + str(buy) + ' BUY</span> &nbsp;<span class="sell">' + str(sell) + ' SELL</span> &nbsp;<span class="m">' + str(hold) + ' HOLD</span>')
            + '</div>'
        )
        pnl_stats = (
            '<div class="grid3">'
            + card("Total P&L",   '<span class="' + pc + '">' + "{:+.2f}%".format(total_pnl) + '</span>')
            + card("Win Rate",    "{:.0%} ({}/{})".format(win_rate, winners, len(pnl_vals)))
            + card("Open Trades", str(open_count))
            + '</div>'
        )
        tab_btns = (
            '<div class="tabs">'
            '<button class="tab-btn on"  onclick="tab(\'perf\',this)">📈 Performance</button>'
            '<button class="tab-btn"     onclick="tab(\'sigs\',this)">📋 All Signals</button>'
            '<button class="tab-btn"     onclick="tab(\'ing\',this)">🗄️ Ingestion</button>'
            '<button class="tab-btn"     onclick="tab(\'cfg\',this)">⚙️ System</button>'
            '</div>'
        )
        panes = (
            '<div id="p-perf" class="pane on">' + make_table(["Asset","Signal","Entry","Stop","Target","Now","P&L","Status","When"], perf_rows) + '</div>'
            '<div id="p-sigs" class="pane">'    + make_table(["Asset","Signal","Conf","Entry","Stop","Target","When"], sig_rows)                   + '</div>'
            '<div id="p-ing"  class="pane">'    + make_table(["Chunks","Recall@5","When"], ing_rows)                                               + '</div>'
            '<div id="p-cfg"  class="pane">'    + make_table(["Key","Value"], cfg_rows)                                                            + '</div>'
        )

        return (
            CSS
            + '<div class="vk">'
            + '<h1>📊 Vektor Trader</h1>'
            + top_stats
            + '<hr>'
            + pnl_stats
            + tab_btns
            + panes
            + '</div>'
            + JS
        )

    except Exception as e:
        import traceback
        return "<pre style='color:red;padding:20px'>" + traceback.format_exc() + "</pre>"


SHELL_CSS = """
.gradio-container{max-width:100%!important;padding:0!important;background:#111!important}
.gr-button{margin:8px 16px!important;width:calc(100% - 32px)!important}
footer{display:none!important}
"""

with gr.Blocks(css=SHELL_CSS, theme=gr.themes.Monochrome()) as demo:
    dashboard = gr.HTML()
    btn = gr.Button("🔄 Refresh", variant="primary")
    btn.click(render, outputs=dashboard)
    demo.load(render, outputs=dashboard)

demo.launch()
