"""A Thursday slice is the only market-data input to this module."""
import numpy as np
import pandas as pd
from config import BASELINE, CONSOLIDATION, IMPULSE, BENCHMARK
from src.data import invalid_bars


def build_features(prices, tickers, as_of, calendar):
    t = pd.Timestamp(as_of)
    if t.weekday() != 3:
        raise ValueError("Decision date must be Thursday")
    spy = prices[BENCHMARK].loc[:t]
    if spy.empty or spy.index[-1] != t:
        raise ValueError("Thursday SPY bar missing")
    # 29 observations: preceding close + 20 baseline + 5 impulse + 3 pause.
    n = BASELINE + IMPULSE + CONSOLIDATION + 1
    sessions = spy.index[-n:]
    expected = calendar.loc[:t].index[-n:]
    if len(sessions) != n or not sessions.equals(expected):
        raise ValueError("Incomplete SPY session index / warm-up")
    b = spy.reindex(sessions)
    error = invalid_bars(b)
    if error:
        raise ValueError(f"Invalid SPY baseline: {error}")
    p = BASELINE  # impulse starting close at position 20 = t-8
    e = p + IMPULSE  # impulse ending close at position 25 = t-3
    spy_impulse = b.close.iloc[e] / b.close.iloc[p] - 1
    spy_pause = b.close.iloc[-1] / b.close.iloc[e] - 1
    rows, excluded = [], []
    for ticker in tickers:
        if ticker == BENCHMARK:
            continue
        frame = prices.get(ticker)
        w = frame.loc[:t].reindex(sessions) if frame is not None else pd.DataFrame(index=sessions, columns=b.columns)
        error = invalid_bars(w)
        if not error and (w.stock_splits.fillna(0) != 0).any():
            error = "split_in_required_window"
        if error:
            excluded.append(dict(decision_date=t, ticker=ticker, reason=error))
            continue
        baseline_volume = w.volume.iloc[1:p+1].median()
        ranges = [(w.high.iloc[j-2:j+1].max() - w.low.iloc[j-2:j+1].min()) / w.close.iloc[j-3]
                  for j in range(3, p+1)]
        normal_range = float(np.median(ranges))
        if baseline_volume <= 0 or normal_range <= 0:
            excluded.append(dict(decision_date=t, ticker=ticker, reason="invalid_setup_denominator"))
            continue
        impulse = w.iloc[p+1:e+1]
        pause = w.iloc[e+1:]
        start, end, close = w.close.iloc[p], w.close.iloc[e], w.close.iloc[-1]
        high, low = pause.high.max(), pause.low.min()
        impulse_high = impulse.high.max()
        width = high - low
        retention_denominator = impulse_high - start
        retention_raw = (close - start) / retention_denominator if retention_denominator > 0 else np.nan
        impulse_return = end / start - 1
        rows.append(dict(
            decision_date=t, ticker=ticker, baseline_start=sessions[1], baseline_end=sessions[p],
            range_preceding_close_date=sessions[0], impulse_start=sessions[p+1], impulse_end=sessions[e],
            consolidation_start=sessions[e+1], impulse_start_close=start, impulse_end_close=end,
            thursday_close=close, spy_thursday_close=b.close.iloc[-1], impulse_high=impulse_high,
            stock_impulse_return=impulse_return, spy_impulse_return=spy_impulse,
            excess_return=impulse_return-spy_impulse, baseline_volume=baseline_volume,
            impulse_volume=impulse.volume.mean(), rvol=impulse.volume.mean()/baseline_volume,
            consolidation_high=high, consolidation_low=low, current_range=width/end,
            normal_range=normal_range, compression_ratio=(width/end)/normal_range,
            retention_denominator=retention_denominator, retention_raw=retention_raw,
            retention=np.clip(retention_raw, 0, 1), close_location=(close-low)/width if width else 0.5,
            flat_consolidation=bool(width == 0), consolidation_rs=close/end-1-spy_pause,
            negative_absolute_impulse=bool(impulse_return < 0),
            scoring_exclusion="invalid_retention_denominator" if retention_denominator <= 0 else ""))
    return pd.DataFrame(rows), pd.DataFrame(excluded, columns=["decision_date", "ticker", "reason"])
