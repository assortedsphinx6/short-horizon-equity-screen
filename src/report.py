"""Human-readable reports generated from real saved tables."""
import pandas as pd

PORTFOLIO_NOTE = """# Portfolio alert: proposed operational defaults

This is a conceptual proposal, not an implemented or tested alert. Agree these provisional defaults with the PM before production.

“Doing well” means a live position has a signed marked-to-market gain of at least 1% of its entry notional, after estimated trading costs. Reverse the price-move direction for shorts. This avoids counting tiny price noise. Together, the qualifying positions must contribute at least 0.25% of current portfolio NAV, so the alert is economically material. Use unrealized gains on remaining live quantity, allocate entry and estimated exit costs to that quantity, and show realized gains separately. Use a weighted entry basis for partial fills; do not reset the entry timestamp when adding to a position.

“Quickly” means entered in the preceding 60 minutes, measuring gain since entry: an actionable intraday horizon. Older positions accelerating recently are outside this definition. “Many” means at least three distinct live positions and at least 30% of all currently open positions meet that age and gain criterion. Three prevents a two-position book from looking broad; 30% prevents a large book triggering on three isolated winners. Consolidate duplicate legs by economic exposure and show sector concentration.

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


def write_screen(out, screen, candidates, date, label, meta):
    screen.to_csv(out / "current_thursday_screen.csv", index=False)
    candidates.to_csv(out / "current_thursday_candidates_audit.csv", index=False)
    cols = ["ticker", "stock_impulse_return", "excess_return", "rvol", "compression_ratio",
            "excess_return_percentile", "rvol_percentile", "excitement_score", "retention", "close_location",
            "consolidation_rs_percentile", "lean_score", "lean", "reason"]
    (out / "current_thursday_screen.md").write_text(
        f"# {date.date()}: {label}\n\n{len(candidates)} qualifying; {len(screen)} displayed, "
        f"{int((~candidates.scorable.astype(bool)).sum())} qualifying but unscorable.\n\n"
        f"Run UTC: {meta['run_at_utc']}; market time zone America/New_York. "
        f"Data observed: {meta['data_observed_at_utc']}; latest completed SPY bar: {meta['data_as_of']}.\n\n"
        "Returns and percentiles are fractions; scores are 0–100, RVOL/compression are ratios. "
        "CSV retains full precision. Lean is a heuristic, not a probability.\n\n" +
        markdown_table(screen[[c for c in cols if c in screen]]) + "\n")
    lines = [f"1. {date.date()} Thursday close: {len(candidates)} qualify, {len(screen)} shown; {label}.",
             "2. Five-session SPY outperformance and above-baseline volume define the impulse.",
             "3. The next three sessions must compress versus the prior 20-session range baseline."]
    for i in range(3):
        if i < len(screen):
            r = screen.iloc[i]
            lines.append(f"{i+4}. {r.ticker}: {r.lean} lean ({r.lean_score:.1f}); retention {r.retention:.0%}, range location {r.close_location:.0%}, pause RS rank {r.consolidation_rs_percentile:.0%}.")
        else:
            lines.append(f"{i+4}. No additional qualifying, scorable name.")
    lines += ["7. Daily OHLCV cannot reveal live news or order flow; lean is not a probability.",
              "8. Next: freeze future Thursday snapshots and test unchanged rules on held-out Fridays."]
    assert len(lines) == 8 and all(lines)
    (out / "pm_note_screen.md").write_text("\n".join(lines) + "\n")
    (out / "pm_note_portfolio_alert.md").write_text(PORTFOLIO_NOTE)


def write_history(out, audit, exclusions, joined, totals, buckets, sanity, meta):
    for name, table in [("outcome_summary", totals), ("lean_buckets", buckets), ("lean_sanity", sanity)]:
        table.to_csv(out / f"{name}.csv", index=False)
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
            "See thursday_audit.csv for missing benchmark windows and Thursday holidays; "
            "universe_features.csv for valid rank populations; historical_thursday_screens.csv for all qualifiers.\n\n"
            "Current membership projected backward has survivorship/selection bias. Yahoo history may be revised "
            "and is not an archived Thursday data vintage. Thursday decisions were persisted before outcome joins. "
            "Same-Friday names are correlated, so name-events are not independent experiments. "
            "This is a descriptive recent-regime check, without threshold fitting, out-of-sample validation, "
            "execution costs, borrow constraints or trading P&L. News, sentiment and true order flow are unobserved.\n")
    (out / "historical_summary.md").write_text(text)
