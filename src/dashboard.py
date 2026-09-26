"""Static PM dashboard rendered only from saved outputs; it holds no numbers of its own."""
from html import escape

import pandas as pd

from src.report import completed_fridays, lean_phrase, load_saved_outputs, pct

STYLE = """
:root{--ink:#172235;--muted:#5d6b82;--line:#dce3ec;--paper:#f4f7fb;--card:#fff;--navy:#0d1c31;
--green:#087f5b;--green2:#dff7ed;--red:#b33a3a;--red2:#fff0ef;--grey:#5f6b7a;--grey2:#eef1f5}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{background:var(--navy);color:#fff;padding:18px 24px}header b{font-size:1.1rem}header span{color:#b8c4d6;display:block;font-size:.85rem}
main{max-width:1280px;margin:auto;padding:20px 24px 48px}h2{font-size:1.15rem;margin:28px 0 10px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}
.status{margin-bottom:16px}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}
.kpi{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:12px}.kpi b{display:block;font-size:1.4rem}
.kpi span,.muted{color:var(--muted);font-size:.85rem}.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:980px}th{text-align:left;font-size:.72rem;text-transform:uppercase;
letter-spacing:.05em;color:var(--muted);padding:10px;border-bottom:1px solid var(--line)}
td{padding:12px 10px;border-bottom:1px solid #e8edf3;vertical-align:top}.t{font-weight:800}.small{font-size:.8rem;color:var(--muted)}
.pill{display:inline-block;border-radius:999px;padding:3px 9px;font-size:.75rem;font-weight:700}
.continuation{background:var(--green2);color:var(--green)}.stall{background:var(--red2);color:var(--red)}
.balanced,.weak{background:var(--grey2);color:var(--grey)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}ul{margin:6px 0 0;padding-left:18px}li{margin:4px 0}
@media(max-width:800px){.kpis,.grid{grid-template-columns:1fr 1fr}}@media(max-width:520px){.kpis,.grid{grid-template-columns:1fr}}
"""


def sec_text(context, ticker):
    if context is None or ticker not in context.index:
        return "SEC context not run"
    r = context.loc[ticker]
    if r.sec_status == "none":
        return "No target filing (8-K, 10-Q, 10-K, 6-K, 20-F) accepted in the signal window"
    if r.sec_status == "ok":
        link = f' <a href="{escape(str(r.sec_latest_url))}">latest</a>' if pd.notna(r.sec_latest_url) else ""
        return f"{int(r.sec_filing_count)} target filing(s); latest {escape(str(r.sec_latest_form))}{link}"
    if r.sec_status == "not_requested_historical":
        return "Not requested (historical snapshot)"
    return f"Unavailable: {escape(str(r.sec_error))} (does not mean no filings)"


def signal_row(r, v):
    member = v["members"].loc[r.ticker] if r.ticker in v["members"].index else None
    company = escape(str(member.company_name)) if member is not None else ""
    sector = escape(str(member.sector)) if member is not None else ""
    phrase = lean_phrase(r)
    css = "weak" if phrase.startswith("very weak") else (r.lean if isinstance(r.lean, str) else "balanced")
    return (
        f"<tr><td><span class='t'>{escape(r.ticker)}</span><br><span class='small'>{company}<br>{sector}</span></td>"
        f"<td><span class='pill {css}'>{escape(phrase)}</span><br><span class='small'>lean score {r.lean_score:.1f}"
        f" / 100</span></td>"
        f"<td>{r.excitement_score:.1f}<br><span class='small'>excitement / 100</span></td>"
        f"<td>{pct(r.excess_return, True)}<br><span class='small'>stock {pct(r.stock_impulse_return, True)}, "
        f"SPY {pct(r.spy_impulse_return, True)}</span></td>"
        f"<td>{r.rvol:.2f}×</td><td>{r.compression_ratio:.2f}</td>"
        f"<td class='small'>kept {r.retention:.0%} of move<br>closed at {r.close_location:.0%} of range<br>"
        f"pause RS percentile {r.consolidation_rs_percentile:.0%}</td>"
        f"<td class='small'>{escape(str(r.reason))}</td><td class='small'>{sec_text(v['context'], r.ticker)}</td></tr>")


def evidence_panel(v, population, title):
    s = v["summary"].loc[population]
    hi, lo = v["sanity"].loc[(population, "higher_lean_gt50")], v["sanity"].loc[(population, "lower_lean_lt50")]
    return (
        f"<div class='panel'><b>{title}</b><p class='muted'>{int(s.n)} completed Friday observations.</p><ul>"
        f"<li>All: continuation {pct(s.continuation_rate)}, neutral {pct(s.neutral_rate)}, "
        f"stall {pct(s.stall_rate)}; mean Friday return vs SPY {pct(s.friday_excess_mean, True)}.</li>"
        f"<li>Higher lean (&gt;50, n={int(hi.n)}): closed above the range {pct(hi.continuation_rate)}, "
        f"stalled {pct(hi.stall_rate)}, mean vs SPY {pct(hi.friday_excess_mean, True)}.</li>"
        f"<li>Lower lean (&lt;50, n={int(lo.n)}): closed above the range {pct(lo.continuation_rate)}, "
        f"stalled {pct(lo.stall_rate)}, mean vs SPY {pct(lo.friday_excess_mean, True)}.</li></ul></div>")


def write_dashboard(out):
    v = load_saved_outputs(out)
    meta, screen, audit = v["meta"], v["screen"], v["decision_audit"]
    observed = pd.Timestamp(meta["data_observed_at_utc"]).tz_convert("America/New_York")
    counts = screen.lean.value_counts()
    failures = meta.get("download_failures", {})
    friday_status = str(audit.friday_status)
    excluded = "; ".join(f"{escape(r.ticker)} ({escape(r.reason.replace('_', ' '))})"
                         for r in v["exclusions"].itertuples()) or "none"
    rows = "".join(signal_row(r, v) for r in screen.itertuples()) or "<tr><td colspan='9'>No qualifying names.</td></tr>"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Thursday Screen Dashboard</title><style>{STYLE}</style></head><body>
<header><b>Thursday-close screen: {escape(meta['decision_date'])}</b>
<span>Data observed {observed:%Y-%m-%d %H:%M} America/New_York · {escape(meta['snapshot_label'])}</span></header>
<main>
<div class="panel status"><b>{int(counts.get('continuation', 0))} continuation leans, {int(counts.get('stall', 0))} stall leans,
{int(counts.get('balanced', 0))} balanced.</b> The lean is a heuristic that summarizes Thursday's price action;
it is not a probability or a trade recommendation. Scores close to 50 carry little direction.
<div class="kpis"><div class="kpi"><b>{int(meta['universe_count'])}</b><span>constituent securities loaded</span></div>
<div class="kpi"><b>{int(audit.eligible_universe_count)}</b><span>eligible and ranked</span></div>
<div class="kpi"><b>{len(v['candidates'])}</b><span>passed all three filters</span></div>
<div class="kpi"><b>{len(screen)}</b><span>shown (top by excitement)</span></div></div>
<span class="muted">Excluded before ranking: {excluded}. The other qualifiers are in
<code>current_thursday_candidates_audit.csv</code>.</span></div>
<h2>Data-quality status</h2>
<div class="panel"><div class="kpis">
<div class="kpi"><b>{escape(str(meta['data_as_of']))}</b><span>latest completed market bar</span></div>
<div class="kpi"><b>{len(failures)}</b><span>unresolved Yahoo downloads</span></div>
<div class="kpi"><b>{len(v['exclusions'])}</b><span>securities excluded on this Thursday</span></div>
<div class="kpi"><b>{escape(friday_status)}</b><span>immediate Friday status</span></div>
</div><span class="muted">Observation frozen at {observed:%Y-%m-%d %H:%M} America/New_York. A pending Friday is
not evaluated, and unavailable input is never treated as a negative signal.</span></div>
<h2>Thursday list</h2>
<div class="panel scroll"><table><thead><tr><th>Name</th><th>Lean</th><th>Excitement</th><th>Impulse vs SPY</th>
<th>RVOL</th><th>Compression</th><th>Lean inputs</th><th>Reason</th><th>SEC context</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="muted">Qualification: impulse return vs SPY &gt; 0, RVOL &gt; 1, compression &lt; 1 (all strict).
Excitement = average of the excess-return and RVOL percentiles across all eligible stocks. SEC context never
affects qualification, ranking or lean.</p>
<h2>What happened on past Fridays</h2>
<p class="muted">{completed_fridays(v['audit'])} completed Fridays in the last {int(meta['months'])} months, same fixed rules.
Continuation = Friday close above Thursday's three-day high; stall = Friday close at or below Thursday's close;
otherwise neutral. Descriptive only.</p>
<div class="grid">{evidence_panel(v, 'pm_top10', 'Displayed top 10 each week')}
{evidence_panel(v, 'all_qualified', 'All qualifiers')}</div>
<div class="panel" style="margin-top:16px"><b>How to read this evidence</b><ul>
<li>Higher-lean names broke above the range more often, but stall rates were similar and there is no demonstrated return edge.</li>
<li>A close near the top of Thursday's range leaves less distance to a breakout, so part of that gap is mechanical.</li>
<li>Names on the same Friday are correlated, so observations are not independent; no trading costs or P&amp;L are modelled.</li></ul></div>
<h2>Limits</h2>
<div class="panel"><ul>
<li>Attention is proxied by unusual performance vs SPY plus above-normal volume; news and social attention are not measured.</li>
<li>RVOL &gt; 1 is a permissive above-baseline participation gate, not an extreme-volume threshold; in broad high-volume weeks it
filters little, and the RVOL percentile inside the excitement score does most of the discrimination.</li>
<li>History uses today's S&amp;P 500 members (survivorship bias) and Yahoo data downloaded after the fact, not an archived Thursday feed.</li>
</ul></div>
<p class="small">Generated from the saved CSV outputs of this run; rerun the pipeline to refresh.</p>
</main></body></html>
"""
    (out / "dashboard.html").write_text(page)
