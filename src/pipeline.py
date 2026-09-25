"""Readable orchestration for the Thursday screen and historical study."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

import pandas as pd

from config import BENCHMARK
from src.data import download, load_cache, save_cache, schedule, universe
from src.enrichment import enrich_shortlist
from src.evaluate import evaluate, session_status, summary_tables
from src.features import build_features
from src.report import markdown_table, write_history, write_screen
from src.screen import rank_and_screen

PACKAGE_NAMES = ["pandas", "numpy", "yfinance", "requests", "lxml", "pandas_market_calendars"]


def run_research(args):
    """Build the current screen, historical evidence, and optional context."""
    now = pd.Timestamp.now(tz="UTC")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.enrich_only:
        enrich_saved_screen(output_dir, offline=args.replay, now=now)
        return

    today = now.tz_convert("America/New_York").normalize().tz_localize(None)
    anchor, start = validate_requested_period(args, today)
    calendar = schedule(start, today + pd.Timedelta(days=8))
    prices, members, metadata, observed_at = load_market_inputs(args, now, today, start)
    decision, label = choose_decision_date(args, anchor, prices, calendar, observed_at)
    metadata.update(
        decision_date=str(decision.date()), data_as_of=str(latest_completed_bar(prices, calendar, observed_at).date()),
        universe_count=len(members), months=args.months, market_timezone="America/New_York", snapshot_label=label,
    )
    screen = build_current_screen(prices, members, decision, calendar, metadata, output_dir)
    study = build_historical_study(prices, members, decision, calendar, observed_at, args.months)
    totals = save_historical_study(study, prices, members, calendar, observed_at, metadata, output_dir)
    print_run_summary(screen, totals, output_dir, observed_at)
    enrich_saved_screen(output_dir, offline=args.replay, now=now)


def validate_requested_period(args, today):
    anchor = pd.Timestamp(args.as_of) if args.as_of else today
    if anchor.tzinfo is not None or anchor != anchor.normalize() or (args.as_of and anchor.weekday() != 3):
        raise ValueError("--as-of must be a date-only Thursday, YYYY-MM-DD")
    if args.months < 1:
        raise ValueError("--months must be positive")
    return anchor, anchor - pd.DateOffset(months=args.months) - pd.Timedelta(days=65)


def load_market_inputs(args, now, today, start):
    """Replay the frozen cache or download a fresh universe and price history."""
    cache_dir = Path("cache")
    if args.replay:
        prices, members, metadata = load_cache(cache_dir)
        if pd.Timestamp(metadata["requested_start"]) > start:
            raise ValueError("Cache does not cover requested warm-up; rerun without --replay")
        observed_at = pd.Timestamp(metadata["data_observed_at_utc"])
        return prices, members, dict(metadata, replay=True, run_at_utc=now.isoformat()), observed_at

    members = universe(now)
    print(f"Constituents: {len(members)} from {members.source_url.iloc[0]}", flush=True)
    observed_at = pd.Timestamp.now(tz="UTC")
    prices, failures = download([BENCHMARK] + members.ticker.tolist(), start, today + pd.Timedelta(days=1))
    if BENCHMARK not in prices:
        raise RuntimeError("Yahoo SPY download failed; no valid session index or empirical screen")
    metadata = {
        "run_at_utc": now.isoformat(), "data_observed_at_utc": observed_at.isoformat(),
        "requested_start": str(start.date()), "requested_end_exclusive": str((today + pd.Timedelta(days=1)).date()),
        "download_failures": failures, "replay": False, "universe_source": members.source_url.iloc[0],
        "universe_fetched_at_utc": members.fetched_at_utc.iloc[0],
        "adjustment": "yfinance auto_adjust=True, raw reported volume; repair=False; split windows excluded",
        "versions": {name: importlib.metadata.version(name) for name in PACKAGE_NAMES},
    }
    save_cache(prices, members, metadata, cache_dir)
    return prices, members, metadata, observed_at


def completed_sessions(calendar, observed_at):
    return calendar[calendar.market_close <= observed_at].index


def latest_completed_bar(prices, calendar, observed_at):
    return prices[BENCHMARK].dropna(subset=["close"]).index.intersection(completed_sessions(calendar, observed_at)).max()


def choose_decision_date(args, anchor, prices, calendar, observed_at):
    """Select only a completed Thursday and describe the screen's timing honestly."""
    complete = completed_sessions(calendar, observed_at)
    if args.as_of and anchor not in complete:
        raise ValueError("--as-of must be a completed Thursday trading session")
    available = prices[BENCHMARK].dropna(subset=["close"]).index.intersection(complete)
    thursdays = available[available.weekday == 3]
    if thursdays.empty:
        raise ValueError("No completed Thursday in downloaded SPY data")
    decision = anchor if args.as_of else thursdays.max()
    if decision not in thursdays:
        raise ValueError("Requested completed Thursday has no SPY data")
    expected_latest = complete[complete.weekday == 3].max()
    if decision < expected_latest and not args.as_of:
        print(f"WARNING: latest available Thursday {decision.date()} is older than expected {expected_latest.date()}")
    if decision < expected_latest or (args.as_of and decision < thursdays.max()) or session_status(decision, calendar, observed_at) == "completed":
        return decision, "historical Thursday snapshot"
    if session_status(decision, calendar, observed_at) == "holiday":
        return decision, "Thursday-close screen; Friday holiday, no evaluation"
    return decision, "latest Thursday-close screen; Friday outcome pending"


def build_current_screen(prices, members, decision, calendar, metadata, output_dir):
    features, _ = build_features(prices, members.ticker, decision, calendar)
    screen, candidates, _ = rank_and_screen(features)
    write_screen(output_dir, screen, candidates, decision, metadata["snapshot_label"], metadata)
    print(f"{decision.date()}: {len(features)} valid stocks, {len(candidates)} qualifiers, {len(screen)} displayed")
    return screen


def build_historical_study(prices, members, decision, calendar, observed_at, months):
    """Rebuild every Thursday independently before any Friday outcome is read."""
    decisions, universes, exclusions, audit = [], [], [], []
    for date in pd.date_range(decision - pd.DateOffset(months=months), decision, freq="W-THU"):
        record = dict(decision_date=date, scanned=False, eligible_universe_count=0, qualified_count=0,
                      pm_visible_count=0, friday_status=session_status(date, calendar, observed_at), exclusion="")
        try:
            if date not in calendar.index:
                raise ValueError("Thursday holiday")
            if calendar.loc[date, "market_close"] > observed_at:
                raise ValueError("Thursday not completed at data observation")
            features, excluded = build_features(prices, members.ticker, date, calendar)
            _, qualified, valid = rank_and_screen(features)
            decisions.append(qualified); universes.append(valid); exclusions.append(excluded)
            record.update(scanned=True, eligible_universe_count=len(features), qualified_count=len(qualified),
                          pm_visible_count=int(qualified.pm_visible.sum()))
        except ValueError as exc:
            record["exclusion"] = str(exc)
        audit.append(record)
    return dict(decisions=pd.concat(decisions, ignore_index=True), universes=pd.concat(universes, ignore_index=True),
                exclusions=pd.concat(exclusions, ignore_index=True), audit=pd.DataFrame(audit))


def save_historical_study(study, prices, members, calendar, observed_at, metadata, output_dir):
    """Persist Thursday decisions first, then evaluate Friday outcomes."""
    decisions = study["decisions"]
    for filename, frame in {
        "historical_thursday_screens.csv": decisions, "universe_features.csv": study["universes"],
        "feature_exclusions.csv": study["exclusions"], "thursday_audit.csv": study["audit"],
        "universe_snapshot.csv": members,
    }.items():
        frame.to_csv(output_dir / filename, index=False)
    Path("data").mkdir(exist_ok=True)
    members.to_csv("data/universe.csv", index=False)
    history_path = output_dir / "historical_thursday_screens.csv"
    frozen_hash = hashlib.sha256(history_path.read_bytes()).hexdigest()
    outcomes = evaluate(decisions, prices, calendar, observed_at)
    outcomes.to_csv(output_dir / "friday_outcomes.csv", index=False)
    joined, totals, buckets, sanity = summary_tables(decisions, outcomes)
    write_history(output_dir, study["audit"], study["exclusions"], joined, totals, buckets, sanity, metadata)
    metadata.update(thursday_decisions_sha256=frozen_hash, calendar_thursdays=len(study["audit"]),
                    scanned_thursdays=int(study["audit"].scanned.sum()), qualified_name_events=len(decisions),
                    completed_name_events=int(outcomes.status.eq("completed").sum()))
    (output_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2))
    (output_dir / "RUN_FAILED.txt").unlink(missing_ok=True)
    return totals


def print_run_summary(screen, totals, output_dir, observed_at):
    print(markdown_table(screen[["ticker", "excitement_score", "lean_score", "lean"]]))
    print(markdown_table(totals))
    print(f"Saved {output_dir.resolve()}; data cutoff {observed_at}; market zone America/New_York")


def enrich_saved_screen(output_dir, *, offline=False, now=None):
    """Verify the frozen shortlist, then add context without altering signals."""
    if (output_dir / "RUN_FAILED.txt").exists():
        raise ValueError("Saved run is marked failed; rerun the Yahoo core before enrichment")
    metadata = json.loads((output_dir / "run_metadata.json").read_text())
    history_path = output_dir / "historical_thursday_screens.csv"
    if hashlib.sha256(history_path.read_bytes()).hexdigest() != metadata["thursday_decisions_sha256"]:
        raise ValueError("Saved Thursday decisions do not match their recorded hash")
    screen = pd.read_csv(output_dir / "current_thursday_screen.csv", float_precision="round_trip")
    history = pd.read_csv(history_path, float_precision="round_trip")
    expected = history[history.decision_date.eq(metadata["decision_date"]) & history.pm_visible].reset_index(drop=True)
    pd.testing.assert_frame_equal(screen, expected, check_dtype=False)
    members = pd.read_csv(output_dir / "universe_snapshot.csv")
    try:
        manifest = enrich_shortlist(screen, members, metadata, output_dir, offline=offline, now=now)
        print(f"SEC context status: {manifest['sec_status_counts']}")
        (output_dir / "ENRICHMENT_FAILED.txt").unlink(missing_ok=True)
    except Exception as exc:
        message = f"Context unavailable: {type(exc).__name__}: {exc}. Yahoo core remains valid.\n"
        (output_dir / "ENRICHMENT_FAILED.txt").write_text(message)
        print(message, file=sys.stderr)
