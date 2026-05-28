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

TABLE_CSS = """
<style>
*{color:#fff!important;box-sizing:border-box}
html,body,.vk{background:#111!important}
.vk{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding-bottom:20px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:4px}
.card{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:14px;min-width:0}
.card-label{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#666;margin-bottom:6px}
.card-value{font-size:20px;font-weight:700;line-height:1.3;word-break:break-word}
.card-value .small{font-size:13px;font-weight:400;color:#aaa;display:block;margin-top:2px}
hr{border:none;border-top:1px solid #2a2a2a;margin:12px 0}
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
.summary{margin:12px 0;padding:16px;background:#111;border:1px solid #2a2a2a;border-radius:12px}
.summary-text{font-size:14px;color:#bbb;line-height:1.7}
.summary-note{font-size:11px;color:#555;margin-top:8px}
@media(max-width:580px){
  .grid4{grid-template-columns:repeat(2,1fr)}
  .grid3{grid-template-columns:repeat(2,1fr)}
  .card-value{font-size:17px}
  .explain-row{grid-template-columns:repeat(2,1fr)}
}
</style>
"""

SHELL_CSS = """
*{color-scheme:dark!important;box-sizing:border-box}
html,body,
.gradio-container,
.gradio-container > .main,
.gradio-container > .main > .wrap,
.block,.prose,.html-container,
.svelte-1kyws56,.app{
  background:#111!important;
  color:#fff!important;
}
p,span,div,h1,h2,h3,h4,label,td,th,li{color:#fff!important}
.gradio-container{max-width:100%!important;padding:0!important}
.gr-button{margin:8px 16px!important;width:calc(100% - 32px)!important}
footer,#footer{display:none!important}
"""

FORCE_DARK_JS = """
() => {
  document.documentElement.style.setProperty('background','#111','important');
  document.body.style.setProperty('background','#111','important');
  document.body.style.setProperty('color','#e8e8e8','important');
  document.querySelectorAll('.gradio-container,.block,.prose,.html-container,.main,.wrap')
    .forEach(function(el){
      el.style.setProperty('background','#111','important');
      el.style.setProperty('color','#e8e8e8','important');
    });
  return -(new Date().getTimezoneOffset()) / 60;
}
"""


# ── Helpers ─────────────────────────────────────────────


def fmt_date(ts, tz_offset=4.0):
    if not ts:
        return "—"
    try:
        from datetime import timezone, timedelta
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        dt = dt.astimezone(timezone(timedelta(hours=tz_offset)))
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
    return "winning" if (pnl or 0) > 0 else ("losing" if (pnl or 0) < 0 else "open")


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
        empty = '<tr><td class="empty" colspan="' + str(len(headers)) + '">No data yet.</td></tr>'
        return '<div class="tw"><table><thead><tr>' + ths + '</tr></thead><tbody>' + empty + '</tbody></table></div>'
    trs = ""
    for row in rows:
        cells = ""
        for c in row:
            if isinstance(c, tuple):
                cells += '<td class="' + c[1] + '">' + str(c[0]) + "</td>"
            else:
                cells += "<td>" + (str(c) if c is not None else "—") + "</td>"
        trs += "<tr>" + cells + "</tr>"
    return '<div class="tw"><table><thead><tr>' + ths + '</tr></thead><tbody>' + trs + '</tbody></table></div>'


# ── Data fetching ────────────────────────────────────────

def build_stats():
    runs       = supabase.table("ingestion_runs").select("recall_at_5,chunks_added").execute().data or []
    all_trades = supabase.table("trades").select("decision").execute().data or []
    evals      = supabase.table("trade_evals").select("faithfulness").execute().data or []

    avg_recall   = sum(r["recall_at_5"] for r in runs if r["recall_at_5"]) / len(runs) if runs else 0
    avg_faith    = sum(e["faithfulness"] for e in evals if e["faithfulness"]) / len(evals) if evals else 0
    total_chunks = sum(r["chunks_added"] for r in runs if r["chunks_added"]) if runs else 0
    buy  = sum(1 for t in all_trades if t["decision"] == "BUY")
    sell = sum(1 for t in all_trades if t["decision"] == "SELL")
    hold = sum(1 for t in all_trades if t["decision"] == "HOLD")

    ri    = "g" if avg_recall >= 0.9 else ("y" if avg_recall >= 0.7 else "r")
    fi    = "g" if avg_faith  >= 0.8 else ("y" if avg_faith  >= 0.6 else "r")
    trust = (avg_recall + avg_faith) / 2
    ti    = "g" if trust >= 0.85 else ("y" if trust >= 0.7 else "r")

    return TABLE_CSS + '<div class="vk"><div class="grid4">' + \
        card("Recall@5",        '<span class="' + ri + '">' + "{:.1%}".format(avg_recall) + '</span>') + \
        card("Faithfulness",    '<span class="' + fi + '">' + "{:.1%}".format(avg_faith)  + '</span>') + \
        card("Knowledge",       "{:,}<span class='small'>chunks</span>".format(total_chunks)) + \
        card("Trustworthiness", '<span class="' + ti + '">' + "{:.1%}".format(trust) + '</span>') + \
        '</div></div>'


def make_summary(avg_recall, avg_faith, total_pnl, win_rate, n, open_count, buy, sell, hold):
    lines = []
    total = buy + sell + hold

    # AI quality
    if avg_recall >= 0.95:
        lines.append("The AI is finding relevant context with near-perfect accuracy ({:.1%}) — the knowledge base is working well.".format(avg_recall))
    elif avg_recall >= 0.8:
        lines.append("Context retrieval is solid at {:.1%}.".format(avg_recall))
    else:
        lines.append("Context retrieval at {:.1%} is low — signals may be missing key data.".format(avg_recall))

    if avg_faith >= 0.85:
        lines.append("Reasoning is strongly grounded in real market data ({:.1%} faithfulness).".format(avg_faith))
    elif avg_faith >= 0.65:
        lines.append("Reasoning quality is acceptable at {:.1%}.".format(avg_faith))
    else:
        lines.append("Faithfulness is low ({:.1%}) — the AI may be going beyond what the data supports.".format(avg_faith))

    # Signal mix
    if total > 0:
        hold_pct = hold / total
        if hold_pct >= 0.7:
            lines.append("The AI is cautious — {:.0%} of all signals are HOLD, suggesting market conditions are unclear or conflicting.".format(hold_pct))
        elif buy > sell:
            lines.append("Signals lean bullish: {} BUY vs {} SELL.".format(buy, sell))
        elif sell > buy:
            lines.append("Signals lean bearish: {} SELL vs {} BUY.".format(sell, buy))
        else:
            lines.append("Signals are evenly split: {} BUY and {} SELL.".format(buy, sell))

    # P&L verdict
    if n == 0:
        lines.append("No completed trades yet to measure performance.")
    elif n < 10:
        lines.append("Only {} trade{} tracked so far — need at least 20 to draw real conclusions.".format(n, "s" if n != 1 else ""))
        if total_pnl > 0:
            lines.append("Early result is positive at {:+.2f}%, but too soon to read into it.".format(total_pnl))
        else:
            lines.append("Early result is {:+.2f}% — too soon to read into it.".format(total_pnl))
    else:
        if win_rate >= 0.6:
            lines.append("Win rate of {:.0%} over {} trades is strong — signals are showing a clear edge.".format(win_rate, n))
        elif win_rate >= 0.5:
            lines.append("Win rate of {:.0%} over {} trades is above break-even. Promising but keep watching.".format(win_rate, n))
        else:
            lines.append("Win rate of {:.0%} over {} trades is below 50% — signals need improvement.".format(win_rate, n))
        if total_pnl > 0:
            lines.append("Total simulated return is {:+.2f}%.".format(total_pnl))
        else:
            lines.append("Total simulated return is {:+.2f}%.".format(total_pnl))

    if open_count > 0:
        lines.append("{} trade{} still open and being tracked against live prices.".format(open_count, "s" if open_count != 1 else ""))

    text = " ".join(lines)
    return (
        '<div class="summary">'
        '<div class="summary-text">' + text + '</div>'
        '<div class="summary-note">⚠️ Paper trading only — no real money involved. Not financial advice.</div>'
        '</div>'
    )


def build_performance(tz=0.0):
    # fetch system stats for summary
    runs  = supabase.table("ingestion_runs").select("recall_at_5").execute().data or []
    evals = supabase.table("trade_evals").select("faithfulness").execute().data or []
    all_t = supabase.table("trades").select("decision").execute().data or []
    avg_recall = sum(r["recall_at_5"] for r in runs if r["recall_at_5"]) / len(runs) if runs else 0
    avg_faith  = sum(e["faithfulness"] for e in evals if e["faithfulness"]) / len(evals) if evals else 0
    buy  = sum(1 for t in all_t if t["decision"] == "BUY")
    sell = sum(1 for t in all_t if t["decision"] == "SELL")
    hold = sum(1 for t in all_t if t["decision"] == "HOLD")

    trades = supabase.table("trades").select("*").neq("decision","HOLD").order("created_at",desc=True).limit(100).execute().data or []
    sig_card = card("Signals",
        '<span class="buy">' + str(buy) + ' BUY</span>'
        '<span style="color:#555"> · </span>'
        '<span class="sell">' + str(sell) + ' SELL</span>'
        '<span style="color:#555"> · ' + str(hold) + ' HOLD</span>')

    if not trades:
        summary   = make_summary(avg_recall, avg_faith, 0, 0, 0, 0, buy, sell, hold)
        pnl_cards = TABLE_CSS + '<div class="vk"><div class="grid4">' + sig_card + card("Total P&L","—") + card("Win Rate","—") + card("Open Trades","0") + '</div>' + summary + '</div>'
        return pnl_cards, TABLE_CSS + make_table(["Asset","Signal","Entry","Stop","Target","Now","P&L","Status","When"],[])

    prices = get_prices(list({t["asset"] for t in trades if t.get("asset")}))
    rows, pnl_vals, open_count = [], [], 0

    for t in trades:
        cp     = prices.get(t["asset"])
        entry  = t.get("price_at_trade")
        sl     = t.get("stop_loss")
        tp     = t.get("take_profit")
        pnl    = calc_pnl(t["decision"], entry, cp)
        status = get_status(t["decision"], entry, cp, sl, tp)
        pnl_s  = "{:+.2f}%".format(pnl) if pnl is not None else "—"
        pc     = "g" if (pnl or 0) > 0 else ("r" if (pnl or 0) < 0 else "")
        sc     = "buy" if t["decision"] == "BUY" else "sell"
        if pnl is not None: pnl_vals.append(pnl)
        if status in ("winning","losing","open"): open_count += 1
        rows.append([
            t["asset"], (t["decision"], sc),
            ("${:,.2f}".format(entry) if entry else "—"),
            ("${:,.2f}".format(sl)    if sl    else "—"),
            ("${:,.2f}".format(tp)    if tp    else "—"),
            ("${:,.2f}".format(cp)    if cp    else "—"),
            (pnl_s, pc),
            STATUS_ICON.get(status,"") + " " + status,
            fmt_date(t.get("created_at"), tz),
        ])

    total_pnl = round(sum(pnl_vals), 2) if pnl_vals else 0
    winners   = sum(1 for v in pnl_vals if v > 0)
    win_rate  = winners / len(pnl_vals) if pnl_vals else 0
    pc        = "g" if total_pnl > 0 else ("r" if total_pnl < 0 else "")

    summary   = make_summary(avg_recall, avg_faith, total_pnl, win_rate, len(pnl_vals), open_count, buy, sell, hold)
    pnl_cards = (
        TABLE_CSS + '<div class="vk"><div class="grid4">'
        + sig_card
        + card("Total P&L",   '<span class="' + pc + '">{:+.2f}%</span>'.format(total_pnl))
        + card("Win Rate",    "{:.0%} ({}/{})".format(win_rate, winners, len(pnl_vals)))
        + card("Open Trades", str(open_count))
        + '</div>' + summary + '</div>'
    )
    return pnl_cards, TABLE_CSS + make_table(
        ["Asset","Signal","Entry","Stop","Target","Now","P&L","Status","When"], rows
    )


def build_signals(tz=0.0):
    trades = supabase.table("trades").select("asset,decision,confidence,price_at_trade,stop_loss,take_profit,created_at").order("created_at",desc=True).limit(50).execute().data or []
    rows = []
    for t in trades:
        sc    = "buy" if t["decision"]=="BUY" else ("sell" if t["decision"]=="SELL" else "m")
        conf  = "{:.0%}".format(t["confidence"]) if t.get("confidence") else "—"
        entry = t.get("price_at_trade")
        sl    = t.get("stop_loss")
        tp    = t.get("take_profit")
        rows.append([
            t["asset"], (t["decision"], sc), conf,
            ("${:,.2f}".format(entry) if entry else "—"),
            ("${:,.2f}".format(sl)    if sl    else "—"),
            ("${:,.2f}".format(tp)    if tp    else "—"),
            fmt_date(t.get("created_at"), tz),
        ])
    return TABLE_CSS + make_table(["Asset","Signal","Conf","Entry","Stop","Target","When"], rows)


def build_ingestion(tz=0.0):
    runs = supabase.table("ingestion_runs").select("chunks_added,recall_at_5,created_at").order("created_at",desc=True).limit(20).execute().data or []
    rows = []
    for r in runs:
        rc  = r.get("recall_at_5") or 0
        cls = "g" if rc >= 0.9 else ("y" if rc >= 0.7 else "r")
        rows.append([str(r.get("chunks_added","—")), ("{:.1%}".format(rc), cls), fmt_date(r.get("created_at"), tz)])
    return TABLE_CSS + make_table(["Chunks Added","Recall@5","When"], rows)


def build_system():
    config = supabase.table("system_config").select("key,value").execute().data or []
    rows   = [[r["key"], r["value"]] for r in config]
    return TABLE_CSS + make_table(["Key","Value"], rows)


def refresh(tz_offset=0.0):
    try:
        tz              = float(tz_offset) if tz_offset is not None else 0.0
        stats           = build_stats()
        pnl_cards, perf = build_performance(tz)
        sigs            = build_signals(tz)
        ing             = build_ingestion(tz)
        sys_            = build_system()
        return stats, pnl_cards, perf, sigs, ing, sys_
    except Exception as e:
        import traceback
        err = "<pre style='color:red;padding:20px'>" + traceback.format_exc() + "</pre>"
        return err, err, err, err, err, err


# ── Layout ──────────────────────────────────────────────
with gr.Blocks(css=SHELL_CSS, theme=gr.themes.Monochrome(), js="() => { document.documentElement.classList.add('dark'); }") as demo:

    tz_box     = gr.Number(value=0, visible=False)
    stats_html = gr.HTML()
    pnl_html   = gr.HTML()
    btn        = gr.Button("🔄 Refresh", variant="primary")

    with gr.Tabs():
        with gr.Tab("📈 Performance"):
            perf_html = gr.HTML()
        with gr.Tab("📋 All Signals"):
            sigs_html = gr.HTML()
        with gr.Tab("🗄️ Ingestion"):
            ing_html  = gr.HTML()
        with gr.Tab("⚙️ System"):
            sys_html  = gr.HTML()

    outputs = [stats_html, pnl_html, perf_html, sigs_html, ing_html, sys_html]

    # FORCE_DARK_JS forces dark bg AND returns tz offset as input to refresh
    demo.load(fn=refresh, inputs=[tz_box], outputs=outputs, js=FORCE_DARK_JS)
    btn.click(fn=refresh, inputs=[tz_box], outputs=outputs, js=FORCE_DARK_JS)

demo.launch()
