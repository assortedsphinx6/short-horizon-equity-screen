"""Friday data are joined only to already persisted Thursday decisions."""
import numpy as np
import pandas as pd
from config import BENCHMARK, LEAN_BINS, LEAN_MIDPOINT
from src.data import invalid_bars

OUTCOME_COLUMNS = ["decision_date", "ticker", "outcome_date", "status", "outcome", "outcome_exclusion",
                   "friday_close", "friday_high", "closing_breakout", "intraday_breakout",
                   "friday_return", "spy_friday_return", "friday_excess"]


def session_status(thursday, calendar, observed_at):
    friday = pd.Timestamp(thursday) + pd.Timedelta(days=1)
    if friday not in calendar.index:
        return "holiday"
    if calendar.loc[friday, "market_close"] > observed_at:
        return "pending"
    return "completed"


def classify(close, high, thursday_close, consolidation_high):
    closing = close > consolidation_high
    return ("continuation" if closing else "stall" if close <= thursday_close else "neutral",
            bool(closing), bool(high > consolidation_high))


def evaluate(decisions, prices, calendar, observed_at):
    rows = []
    for r in decisions.itertuples():
        friday = pd.Timestamp(r.decision_date) + pd.Timedelta(days=1)
        status = session_status(r.decision_date, calendar, observed_at)
        row = dict.fromkeys(OUTCOME_COLUMNS, None)
        row.update(decision_date=r.decision_date, ticker=r.ticker, outcome_date=friday,
                   status=status, outcome_exclusion="")
        if status == "completed":
            bars = {}
            for ticker in [r.ticker, BENCHMARK]:
                f = prices.get(ticker)
                if f is None or friday not in f.index:
                    row.update(status="missing_data", outcome_exclusion=f"{ticker}: missing Friday bar")
                    break
                bar = f.loc[[friday]]
                error = invalid_bars(bar)
                if (bar.stock_splits.fillna(0) != 0).any():
                    error = "split_on_friday"
                if error:
                    row.update(status="missing_data", outcome_exclusion=f"{ticker}: {error}")
                    break
                bars[ticker] = bar.iloc[0]
            if row["status"] == "completed":
                stock, spy = bars[r.ticker], bars[BENCHMARK]
                outcome, closing, intraday = classify(stock.close, stock.high, r.thursday_close, r.consolidation_high)
                ret = stock.close / r.thursday_close - 1
                spyret = spy.close / r.spy_thursday_close - 1
                row.update(outcome=outcome, friday_close=stock.close, friday_high=stock.high,
                           closing_breakout=closing, intraday_breakout=intraday, friday_return=ret,
                           spy_friday_return=spyret, friday_excess=ret-spyret)
        rows.append(row)
    return pd.DataFrame(rows, columns=OUTCOME_COLUMNS)


def metrics(frame):
    n = len(frame)
    result = {"n": n}
    for label in ["continuation", "neutral", "stall"]:
        count = int(frame.outcome.eq(label).sum())
        result[label + "_count"] = count
        result[label + "_rate"] = count/n if n else np.nan
    for field in ["friday_return", "friday_excess"]:
        result[field + "_mean"] = frame[field].mean() if n else np.nan
        result[field + "_median"] = frame[field].median() if n else np.nan
    return result


def summary_tables(decisions, outcomes):
    decisions, outcomes = decisions.copy(), outcomes.copy()
    decisions["decision_date"] = pd.to_datetime(decisions.decision_date)
    outcomes["decision_date"] = pd.to_datetime(outcomes.decision_date)
    joined = decisions.merge(outcomes, on=["decision_date", "ticker"], how="left", validate="one_to_one")
    rows, buckets, sanity = [], [], []
    for population, f in [("all_qualified", joined), ("pm_top10", joined[joined.pm_visible.astype(bool)])]:
        done = f[f.status.eq("completed")]
        rows.append(dict(population=population, **metrics(done)))
        # Explicit inequalities keep 100 in the final interval without moving interior edges.
        for lo, hi in zip(LEAN_BINS[:-1], LEAN_BINS[1:]):
            part = done[(done.lean_score >= lo) & ((done.lean_score < hi) if hi < 100 else (done.lean_score <= hi))]
            buckets.append(dict(population=population, bucket=f"[{lo},{hi}{']' if hi == 100 else ')'}", **metrics(part)))
        for label, part in [("unconditional", done), ("higher_lean_gt50", done[done.lean_score > LEAN_MIDPOINT]),
                            ("lower_lean_lt50", done[done.lean_score < LEAN_MIDPOINT]), ("balanced_eq50", done[done.lean_score == LEAN_MIDPOINT]),
                            ("unscorable", done[done.lean_score.isna()])]:
            sanity.append(dict(population=population, group=label, **metrics(part)))
    return joined, pd.DataFrame(rows), pd.DataFrame(buckets), pd.DataFrame(sanity)
