"""Independent oracle for the saved 24 September screen.

Expected values are computed here with numpy and the standard library from the committed input vintage;
no production feature, ranking or screening function is called.
"""
import csv
import gzip
import math
from collections import defaultdict
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "frozen_2026-09-24"
THURSDAY = "2026-09-24"


def average_tie_percentiles(values):
    keys = list(values)
    x = np.array([values[k] for k in keys])
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j + 2) / 2
        i = j + 1
    return dict(zip(keys, ranks / len(x)))


def oracle():
    bars = defaultdict(dict)
    with gzip.open(FIXTURE / "prices.csv.gz", "rt") as fh:
        for row in csv.DictReader(fh):
            bars[row["ticker"]][row["date"][:10]] = row
    with open(FIXTURE / "universe.csv") as fh:
        universe = [r["ticker"] for r in csv.DictReader(fh)]
    sessions = sorted(d for d in bars["SPY"] if d <= THURSDAY)[-29:]
    value = lambda r, k: float(r[k]) if r[k] not in ("", "nan") else math.nan
    spy = [value(bars["SPY"][s], "close") for s in sessions]
    spy_impulse, spy_pause = spy[25] / spy[20] - 1, spy[28] / spy[25] - 1
    features, excluded = {}, {}
    for ticker in universe:
        window = [bars[ticker].get(s) for s in sessions]
        if any(b is None for b in window):
            excluded[ticker] = "missing"
            continue
        o, h, l, c, v = ([value(b, k) for b in window] for k in ("open", "high", "low", "close", "volume"))
        if not np.isfinite(np.array([o, h, l, c, v])).all():
            excluded[ticker] = "nonfinite"
            continue
        if any(float(b["stock_splits"] or 0) != 0 for b in window):
            excluded[ticker] = "split"
            continue
        baseline_volume = float(np.median(v[1:21]))
        ranges = [(max(h[j - 2:j + 1]) - min(l[j - 2:j + 1])) / c[j - 3] for j in range(3, 21)]
        normal = float(np.median(ranges))
        high, low = max(h[26:]), min(l[26:])
        denominator = max(h[21:26]) - c[20]
        features[ticker] = dict(
            excess_return=c[25] / c[20] - 1 - spy_impulse,
            rvol=sum(v[21:26]) / 5 / baseline_volume,
            compression_ratio=(high - low) / c[25] / normal,
            retention=min(max((c[28] - c[20]) / denominator, 0), 1) if denominator > 0 else math.nan,
            close_location=(c[28] - low) / (high - low) if high > low else 0.5,
            consolidation_rs=c[28] / c[25] - 1 - spy_pause, n_ranges=len(ranges))
    for field in ("excess_return", "rvol", "consolidation_rs"):
        ranks = average_tie_percentiles({k: f[field] for k, f in features.items()})
        for k, f in features.items():
            f[field + "_percentile"] = ranks[k]
    for f in features.values():
        f["excitement_score"] = 100 * (f["excess_return_percentile"] + f["rvol_percentile"]) / 2
        f["lean_score"] = 100 * (f["retention"] + f["close_location"] + f["consolidation_rs_percentile"]) / 3
        f["qualifies"] = f["excess_return"] > 0 and f["rvol"] > 1 and f["compression_ratio"] < 1
    qualified = sorted((k for k, f in features.items() if f["qualifies"]),
                       key=lambda k: (-features[k]["excitement_score"], k))
    shown = [k for k in qualified if not math.isnan(features[k]["retention"])][:10]
    return dict(sessions=sessions, universe=universe, excluded=excluded, features=features,
                qualified=qualified, shown=shown)


class September24OracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.o = oracle()
        cls.saved = pd.read_csv(ROOT / "outputs" / "data" / "universe_features.csv", float_precision="round_trip")
        cls.saved = cls.saved[cls.saved.decision_date.eq(THURSDAY)].set_index("ticker")

    def test_session_positions_are_trading_sessions_across_labor_day(self):
        s = self.o["sessions"]
        # Hand-counted NYSE sessions; Labor Day (7 Sep) lies inside the volume baseline.
        self.assertEqual((s[28], s[26], s[25], s[21], s[20], s[1], s[0]),
                         ("2026-09-24", "2026-09-22", "2026-09-21", "2026-09-15", "2026-09-14",
                          "2026-08-17", "2026-08-14"))

    def test_funnel_reconciles(self):
        self.assertEqual(len(self.o["universe"]), 503)
        self.assertEqual(self.o["excluded"], {"APH": "split"})
        self.assertEqual(len(self.o["features"]), 502)
        self.assertEqual(len(self.o["qualified"]), 65)
        self.assertTrue(all(f["n_ranges"] == 18 for f in self.o["features"].values()))

    def test_every_saved_feature_matches_the_oracle(self):
        self.assertEqual(set(self.saved.index), set(self.o["features"]))
        for field in ("excess_return", "rvol", "compression_ratio", "retention", "close_location",
                      "consolidation_rs", "excess_return_percentile", "rvol_percentile",
                      "consolidation_rs_percentile", "excitement_score", "lean_score"):
            expected = pd.Series({k: f[field] for k, f in self.o["features"].items()})
            with self.subTest(field=field):
                pd.testing.assert_series_equal(self.saved[field].sort_index(), expected.sort_index(),
                                               check_names=False, rtol=0, atol=1e-12)

    def test_saved_qualifiers_screen_and_cutoff_match_the_oracle(self):
        audit = pd.read_csv(ROOT / "outputs" / "data" / "current_thursday_candidates_audit.csv")
        screen = pd.read_csv(ROOT / "outputs" / "data" / "current_thursday_screen.csv")
        self.assertEqual(audit.ticker.tolist(), self.o["qualified"])
        self.assertEqual(screen.ticker.tolist(), self.o["shown"])
        f = self.o["features"]
        tenth, eleventh = f[self.o["shown"][-1]]["excitement_score"], f[self.o["qualified"][10]]["excitement_score"]
        self.assertGreater(tenth, eleventh)  # no tie at the display cutoff
        labels = {k: "continuation" if f[k]["lean_score"] > 50 else "stall" if f[k]["lean_score"] < 50 else "balanced"
                  for k in self.o["qualified"]}
        self.assertEqual(dict(zip(audit.ticker, audit.lean)), labels)


if __name__ == "__main__":
    unittest.main()
