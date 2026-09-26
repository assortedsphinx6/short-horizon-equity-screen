"""Human-readable reports generated from real saved tables."""
import json
from pathlib import Path

import pandas as pd

from config import LEAN_MIDPOINT

# Display wording only: a lean score this close to 50 is described as near neutral.
NEAR_NEUTRAL_POINTS = 1.0

# Every output folder has the same layout: human-facing files in deliverables/, machine-readable tables in data/.
DELIVERABLES_DIR = "deliverables"
DATA_DIR = "data"


def deliverable_file(out, name):
    folder = Path(out) / DELIVERABLES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def data_file(out, name):
    folder = Path(out) / DATA_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name

PORTFOLIO_NOTE = """# Portfolio alert: proposed operational defaults

This is a conceptual proposal, not an implemented or tested alert. Agree these provisional defaults with the PM before production.

“Doing well” means a live position has a signed marked-to-market gain of at least 1% of its entry notional, after estimated trading costs. Reverse the price-move direction for shorts. This avoids counting tiny price noise. Together, the qualifying positions must contribute at least 0.25% of current portfolio NAV, so the alert is economically material. Use unrealized gains on remaining live quantity, allocate entry and estimated exit costs to that quantity, and show realized gains separately. Use a weighted entry basis for partial fills; do not reset the entry timestamp when adding to a position.

“Quickly” means entered in the preceding 60 minutes, measuring gain since entry: an actionable intraday horizon. The phrase is ambiguous: if the PM instead means recent acceleration of the existing book, the same framework applies to trailing-hour P&L rather than time since entry. “Many” means at least three distinct live positions and at least 30% of all currently open positions meet that age and gain criterion. Three prevents a two-position book from looking broad; 30% prevents a large book triggering on three isolated winners. Consolidate duplicate legs by economic exposure and show sector concentration.

Check every five minutes during the regular session. Require the full condition on two consecutive checks, then fire once and disarm. Five-minute cadence and two confirmations reduce transient noise. Rearm only after two consecutive nonqualifying checks AND at least 60 minutes since the last alert; then require two fresh qualifying checks. The hour cooldown limits repetition. Unknown or stale data cannot count as a qualifying or nonqualifying check; suppress notification and reset consecutive-check counters until reliable marks return.

Include timestamp, winners/open-position denominator, NAV contribution, top drivers, mark freshness, and realized versus unrealized gains. Guard against stale or zero marks, partial fills, reversals, correlated legs, and winners masking a catastrophic loser; report the largest loss alongside the alert. This needs authenticated positions, marks, fees, NAV and timestamps. Replay internal position/mark streams to assess alert burden and missed episodes before tuning any defaults; public stock OHLCV cannot validate it.
"""


def markdown_table(frame):
    if frame.empty:
        return "No rows."
    def display(v):
        if pd.isna(v):
            return "NA"
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v).replace("|", "/").replace("\n", " ")
    return "\n".join(["| " + " | ".join(frame.columns) + " |",
                       "| " + " | ".join(["---"] * len(frame.columns)) + " |"] +
                      ["| " + " | ".join(display(x) for x in r) + " |" for r in frame.itertuples(index=False, name=None)])


def write_screen(out, screen, candidates):
    screen.to_csv(data_file(out, "current_thursday_screen.csv"), index=False)
    candidates.to_csv(data_file(out, "current_thursday_candidates_audit.csv"), index=False)


def load_saved_outputs(out):
    """Everything PM-facing is read back from the saved core outputs, never recomputed."""
    meta = json.loads(data_file(out, "run_metadata.json").read_text())
    read = lambda name: pd.read_csv(data_file(out, name), float_precision="round_trip")
    audit = read("thursday_audit.csv")
    exclusions = read("feature_exclusions.csv")
    context_path = data_file(out, "current_screen_context.csv")
    return dict(
        meta=meta, screen=read("current_thursday_screen.csv"),
        candidates=read("current_thursday_candidates_audit.csv"),
        members=read("universe_snapshot.csv").set_index("ticker"),
        summary=read("outcome_summary.csv").set_index("population"),
        sanity=read("lean_sanity.csv").set_index(["population", "group"]),
        audit=audit, decision_audit=audit[audit.decision_date.eq(meta["decision_date"])].iloc[0],
        exclusions=exclusions[exclusions.decision_date.eq(meta["decision_date"])],
        context=read(context_path.name).set_index("ticker") if context_path.exists() else None)


def near_neutral(row):
    return pd.notna(row.lean_score) and 0 < abs(row.lean_score - LEAN_MIDPOINT) < NEAR_NEUTRAL_POINTS


def lean_phrase(row):
    """Wording only: the stored >50 / <50 / =50 lean label is never changed."""
    if pd.isna(row.lean_score):
        return "no lean (unscorable)"
    if near_neutral(row):
        return f"very weak {row.lean} lean (near neutral)"
    return f"{row.lean} lean"


def pct(x, signed=False):
    return "n/a" if pd.isna(x) else f"{x:+.2%}" if signed else f"{x:.1%}"


def plain_reason(row):
    """Plain-English read of the lean inputs, built from saved values; wording only, no new rule."""
    if pd.isna(row.retention):
        return "Qualifies, but has no lean: the impulse never traded above its starting close."
    kept = row.retention_raw
    if kept > 1:
        held = "Pushed above its impulse high (retention capped at 100%)"
    elif kept < 0:
        held = "Fell below where the impulse started (retention floored at 0%)"
    elif kept >= 0.9:
        held = f"Held nearly all of its move ({kept:.0%})"
    elif kept >= 0.6:
        held = f"Held most of its move ({kept:.0%})"
    elif kept >= 0.4:
        held = f"Held about half of its move ({kept:.0%})"
    else:
        held = f"Gave back most of its move (kept {kept:.0%})"
    where = ("near the top" if row.close_location >= 0.75 else
             "near the bottom" if row.close_location <= 0.25 else "in the middle")
    joiner = "and" if (row.retention >= 0.5) == (row.close_location >= 0.5) else "but"
    versus = "beat" if row.consolidation_rs > 0 else "lagged" if row.consolidation_rs < 0 else "matched"
    return (f"{held} {joiner} closed {where} of its three-day range ({row.close_location:.0%}); {versus} SPY "
            f"during a pause {1 - row.compression_ratio:.0%} tighter than its usual range.")


def write_screen_md(out):
    """Readable Thursday list: rule numbers, lean and a plain-English read. Every audit field stays in data/."""
    v = load_saved_outputs(out)
    meta, screen, candidates = v["meta"], v["screen"], v["candidates"]
    rows = ["| Ticker | Impulse vs SPY | RVOL | Compression | Excitement | Lean score | Read |",
            "| --- | ---: | ---: | ---: | ---: | --- | --- |"]
    for r in screen.itertuples():
        rows.append(f"| {r.ticker} | {pct(r.excess_return, True)} | {r.rvol:.2f}× | {r.compression_ratio:.2f} | "
                    f"{r.excitement_score:.1f} | {r.lean_score:.1f}: {lean_phrase(r)} | {plain_reason(r)} |")
    unscorable = int((~candidates.scorable.astype(bool)).sum()) if len(candidates) else 0
    text = (f"# Thursday {meta['decision_date']}: {meta['snapshot_label']}\n\n"
            f"{len(candidates)} qualifying; {len(screen)} displayed; {unscorable} qualifying without a lean. "
            f"Data observed {meta['data_observed_at_utc']}; latest completed SPY bar {meta['data_as_of']}.\n\n"
            + ("\n".join(rows) if len(screen) else "No qualifying names.") + "\n\n"
            "Qualification: impulse vs SPY > 0, RVOL > 1 and compression < 1, all strict; excitement orders the list. "
            "The lean is a heuristic, not a probability. Full precision, the three lean inputs and every audit field "
            "are in data/current_thursday_screen.csv; definitions are in README.md and formulas in RESEARCH_SPEC.md.\n")
    deliverable_file(out, "current_thursday_screen.md").write_text(text)


def completed_fridays(audit):
    return int((audit.scanned.astype(bool) & audit.friday_status.eq("completed")).sum())


def write_pm_note(out):
    """Eight lines for the PM, derived only from saved outputs."""
    v = load_saved_outputs(out)
    meta, screen = v["meta"], v["screen"]
    names = lambda frame: ", ".join(f"{r.ticker} {r.lean_score:.1f}" for r in frame.itertuples()) or "none"
    cont = screen[screen.lean.eq("continuation")].sort_values("lean_score", ascending=False)
    stall = screen[screen.lean.eq("stall")].sort_values("lean_score")
    balanced = screen[screen.lean.eq("balanced")]
    weak = screen[screen.apply(near_neutral, axis=1)] if len(screen) else screen
    weak_text = (f"; {' and '.join(weak.ticker)} {'is' if len(weak) == 1 else 'are'} within "
                 f"{NEAR_NEUTRAL_POINTS:g} point of 50, so read as near neutral, not a call") if len(weak) else ""
    balanced_text = f"; balanced (exactly 50): {names(balanced)}" if len(balanced) else ""
    if len(cont) and len(stall):
        c, s = cont.iloc[0], stall.iloc[0]
        why = (f"e.g. {c.ticker} kept {c.retention:.0%} of its move and closed at {c.close_location:.0%} of its range; "
               f"{s.ticker} kept {s.retention:.0%} and closed at {s.close_location:.0%}.")
    else:
        why = "see the one-line reason for each name in the screen."
    sectors = v["members"].reindex(screen.ticker).sector.value_counts()
    if len(sectors):
        concentrated = sectors.iloc[0] > len(screen) / 2
        sector_text = (f"Sector mix: {sectors.iloc[0]} of {len(screen)} are {sectors.index[0]}"
                       + (", so the list is largely one sector bet, not independent ideas." if concentrated else "."))
    else:
        sector_text = "Sector mix: no names displayed."
    hi, lo = v["sanity"].loc[("pm_top10", "higher_lean_gt50")], v["sanity"].loc[("pm_top10", "lower_lean_lt50")]
    lines = [
        f"Thu {meta['decision_date']} close: {len(v['candidates'])} of "
        f"{int(v['decision_audit'].eligible_universe_count)} S&P 500 constituent securities beat SPY over five sessions on "
        f"above-baseline volume, then traded a tighter-than-normal three-session range; the {len(screen)} "
        "with the most unusual move plus volume are below.",
        f"Continuation leans, strongest first (lean score, 50 = balanced): {names(cont)}.",
        f"Stall leans, strongest first: {names(stall)}{weak_text}{balanced_text}.",
        "Why: the lean averages how much of the move each stock kept, where Thursday closed in its three-day "
        f"range, and how it did against SPY during the pause; {why}",
        sector_text,
        f"History ({completed_fridays(v['audit'])} completed Fridays, {int(v['summary'].loc['pm_top10', 'n'])} "
        f"displayed names): higher leans closed above the range {pct(hi.continuation_rate)} vs "
        f"{pct(lo.continuation_rate)} for lower leans, but stalled {pct(hi.stall_rate)} vs {pct(lo.stall_rate)}, "
        f"with mean Friday return vs SPY {pct(hi.friday_excess_mean, True)} vs {pct(lo.friday_excess_mean, True)}; "
        "descriptive for this sample only, not evidence of a tradable edge.",
        "It sees only daily price and volume: no news, catalysts, options or order flow, or intraday path; history "
        "uses today's S&P 500 members; the lean is a heuristic, not a probability.",
        "Next test, fixed in advance: on the next 10 saved Thursday lists, compare leans above vs below 50 Friday by "
        "Friday; keep going only if the breakout gap persists and higher leans also stall less and beat SPY on "
        "most of those Fridays.",
    ]
    if len(lines) != 8 or not all(lines):
        raise RuntimeError("The PM note must be exactly eight non-empty lines")
    deliverable_file(out, "pm_note_screen.md").write_text("\n".join(lines) + "\n")


def write_history(out, audit, exclusions, joined, totals, buckets, sanity, meta):
    for name, table in [("outcome_summary", totals), ("lean_buckets", buckets), ("lean_sanity", sanity)]:
        table.to_csv(data_file(out, f"{name}.csv"), index=False)
    status = joined.groupby("status").size().rename("name_events").reset_index()
    exclusions_count = exclusions.groupby("reason").size().rename("name_dates").reset_index() if len(exclusions) else pd.DataFrame()
    findings = []
    for population in ["all_qualified", "pm_top10"]:
        parts = sanity[sanity.population.eq(population)].set_index("group")
        high, low = parts.loc["higher_lean_gt50"], parts.loc["lower_lean_lt50"]
        if high.n and low.n:
            findings.append(
                f"{population}: higher leans closed above the range in {int(high.continuation_count)}/{int(high.n)} "
                f"cases ({high.continuation_rate:.1%}), versus {int(low.continuation_count)}/{int(low.n)} "
                f"({low.continuation_rate:.1%}) for lower leans. Mean Friday excess returns were "
                f"{high.friday_excess_mean:.3%} and {low.friday_excess_mean:.3%}, respectively.")
    findings.append("A high close-location component also puts the stock closer to the breakout boundary: "
                    "breakout separation is not by itself evidence of general directional or economic skill. "
                    "Read the stall rates and continuous returns alongside breakout frequencies.")
    text = (f"# Historical Thursday / Friday evidence\n\n"
            f"Decision span: {audit.decision_date.min().date()} to {audit.decision_date.max().date()}. "
            f"Calendar Thursdays considered: {len(audit)}; successfully scanned: {int(audit.scanned.sum())}. "
            f"Completed next-Friday sessions: {int(((audit.friday_status == 'completed') & audit.scanned).sum())}; "
            f"Friday holidays skipped: {int(((audit.friday_status == 'holiday') & audit.scanned).sum())}; "
            f"pending Friday dates: {int(((audit.friday_status == 'pending') & audit.scanned).sum())}.\n\n"
            f"Median eligible stock universe: {audit.loc[audit.scanned, 'eligible_universe_count'].median():g}. "
            f"Qualified name-events: {len(joined)}; PM-visible: {int(joined.pm_visible.sum())}; "
            f"unscorable qualifiers: {int((~joined.scorable.astype(bool)).sum())}; "
            f"negative absolute impulse qualifiers: {int(joined.negative_absolute_impulse.sum())}.\n\n"
            "The all-qualified population includes unscorable qualifiers in unconditional outcomes; "
            "score buckets exclude them. PM-top10 evaluates only each Thursday's displayed names. "
            "Rates use completed, valid Friday observations only. All returns below are decimal fractions, not percent units.\n\n"
            "## Observed findings\n\n" + "\n\n".join(findings) + "\n\n"
            "## Outcome availability\n\n" + markdown_table(status) + "\n\n"
            "## Completed outcomes by population\n\n" + markdown_table(totals) + "\n\n"
            "## Frozen lean buckets\n\n" + markdown_table(buckets) + "\n\n"
            "Sparse buckets are underpowered; counts are shown and no statistical significance is claimed.\n\n"
            "## Higher/lower lean sanity check\n\n" + markdown_table(sanity) + "\n\n"
            "## Exclusions before ranking\n\n" + markdown_table(exclusions_count) + "\n\n"
            "In the data/ folder, see thursday_audit.csv for missing benchmark windows and Thursday holidays; "
            "universe_features.csv for valid rank populations; historical_thursday_screens.csv for all qualifiers.\n\n"
            "Current membership projected backward has survivorship/selection bias. Yahoo history may be revised "
            "and is not an archived Thursday data vintage. Thursday decisions were persisted before outcome joins. "
            "Same-Friday names are correlated, so name-events are not independent experiments. "
            "This is a descriptive recent-regime check, without threshold fitting, out-of-sample validation, "
            "execution costs, borrow constraints or trading P&L. News, sentiment and true order flow are unobserved.\n")
    deliverable_file(out, "historical_summary.md").write_text(text)
