"""Rank all setup-valid stocks first; filter only afterward."""
import numpy as np
import pandas as pd
from config import TOP_N, LEAN_MIDPOINT

EMPTY_COLUMNS = ["decision_date", "ticker", "eligible_universe_count", "candidate", "scorable", "pm_visible",
                 "excitement_score", "lean_score", "lean", "reason", "scoring_exclusion",
                 "negative_absolute_impulse", "thursday_close", "spy_thursday_close", "consolidation_high"]


def reason(row):
    if not row.scorable:
        return "Qualifies; lean unavailable because impulse high does not exceed the starting close."
    rs_word = "outperformed" if row.consolidation_rs > 0 else "underperformed" if row.consolidation_rs < 0 else "matched"
    return (f"Excess-return/volume percentiles {row.excess_return_percentile:.0%}/{row.rvol_percentile:.0%}; "
            f"retained {row.retention:.0%} of the impulse (clipped); "
            f"close at {row.close_location:.0%} of pause range; {rs_word} SPY "
            f"by {abs(row.consolidation_rs):.2%} during pause (RS percentile {row.consolidation_rs_percentile:.0%}).")


def rank_and_screen(features):
    if features.empty:
        empty = pd.DataFrame(columns=EMPTY_COLUMNS)
        return empty.copy(), empty.copy(), empty.copy()
    f = features.copy()
    for field in ("excess_return", "rvol", "consolidation_rs"):
        f[field + "_percentile"] = f[field].rank(method="average", pct=True)
    f["eligible_universe_count"] = len(f)
    f["excitement_score"] = 100 * (f.excess_return_percentile + f.rvol_percentile) / 2
    f["candidate"] = (f.excess_return > 0) & (f.rvol > 1) & (f.compression_ratio < 1)
    f["scorable"] = f.scoring_exclusion.eq("")
    f["lean_score"] = 100 * (f.retention + f.close_location + f.consolidation_rs_percentile) / 3
    f["lean"] = pd.Series(np.select([f.lean_score > LEAN_MIDPOINT, f.lean_score < LEAN_MIDPOINT],
                                    ["continuation", "stall"], default="balanced"), index=f.index)
    f.loc[~f.scorable, "lean"] = None
    f["pm_visible"] = False
    selected = f[f.candidate & f.scorable].sort_values(["excitement_score", "ticker"], ascending=[False, True]).head(TOP_N).index
    f.loc[selected, "pm_visible"] = True
    f["reason"] = f.apply(reason, axis=1)
    f = f.sort_values(["excitement_score", "ticker"], ascending=[False, True]).reset_index(drop=True)
    return f[f.pm_visible].copy(), f[f.candidate].copy(), f
