"""Synthetic calculation fixtures only; never used as empirical research output."""
import unittest
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from src.data import schedule
from src.features import build_features
from src.screen import rank_and_screen
from src.evaluate import evaluate, classify, session_status, summary_tables


def fixture(date="2026-09-24"):
    t = pd.Timestamp(date)
    cal = schedule(t-pd.Timedelta(days=65), t+pd.Timedelta(days=5))
    dates = cal.loc[:t].index[-29:]
    def bars():
        return pd.DataFrame(dict(open=100., high=102., low=98., close=100., volume=100.,
                                 stock_splits=0., dividends=0.), index=dates)
    spy, a = bars(), bars()
    # 20 baseline sessions; five impulse returns; three compressed pause sessions.
    for i in range(21, 26):
        a.iloc[i] = [100+i-20, 102+i-20, 99+i-20, 101+i-20, 200, 0, 0]
    for i in range(26, 29):
        a.iloc[i] = [106, 107, 105, 106.5, 90, 0, 0]
    b = bars()  # nonqualifier remains in ranks
    c = bars()
    # Qualifying relative decline with invalid retention: SPY loses more.
    return {"SPY": spy, "A": a, "B": b, "C": c}, cal, t


class ResearchTests(unittest.TestCase):
    def test_exact_windows_and_formula(self):
        prices, cal, t = fixture()
        f, ex = build_features(prices, ["A", "B", "SPY"], t, cal)
        a = f.set_index("ticker").loc["A"]
        self.assertTrue(ex.empty)
        self.assertEqual(a.baseline_start, prices["A"].index[1])
        self.assertEqual(a.baseline_end, prices["A"].index[20])
        self.assertEqual(a.impulse_start, prices["A"].index[21])
        self.assertEqual(a.impulse_end, prices["A"].index[25])
        self.assertAlmostEqual(a.stock_impulse_return, .06)
        self.assertEqual(a.rvol, 2)
        self.assertAlmostEqual(a.normal_range, .04)
        self.assertAlmostEqual(a.compression_ratio, (2/106)/.04)
        self.assertAlmostEqual(a.retention_raw, 6.5/7)
        self.assertAlmostEqual(a.close_location, .75)
        self.assertAlmostEqual(a.consolidation_rs, 106.5/106-1)
        # Make the first of exactly 18 baseline range denominators affect the median.
        p = prices["A"].copy()
        p.loc[:, "high"] = np.arange(29) + 102.
        prices["A"] = p
        f, _ = build_features(prices, ["A"], t, cal)
        expected = np.median([(p.high.iloc[j-2:j+1].max()-p.low.iloc[j-2:j+1].min())/p.close.iloc[j-3]
                              for j in range(3, 21)])
        self.assertAlmostEqual(f.iloc[0].normal_range, expected)

    def test_friday_cannot_change_any_thursday_decision(self):
        p, cal, t = fixture()
        before = rank_and_screen(build_features(p, ["A", "B"], t, cal)[0])
        for symbol, f in p.items():
            f.loc[t+pd.Timedelta(days=1)] = [900, 999, 1, 500, 1e10, 0, 0]
        after = rank_and_screen(build_features(p, ["A", "B"], t, cal)[0])
        for a, b in zip(before, after):
            assert_frame_equal(a, b)

    def test_rank_population_pre_filter_and_retention_exclusion(self):
        p, cal, t = fixture()
        f, _ = build_features(p, ["A", "B", "C", "SPY"], t, cal)
        f.loc[f.ticker.eq("C"), ["excess_return", "rvol", "compression_ratio", "consolidation_rs"]] = [.1, 3, .5, .1]
        f.loc[f.ticker.eq("C"), ["retention", "retention_raw"]] = np.nan
        f.loc[f.ticker.eq("C"), "scoring_exclusion"] = "invalid_retention_denominator"
        screen, audit, all_valid = rank_and_screen(f)
        self.assertEqual(len(all_valid), 3)
        self.assertEqual(set(audit.ticker), {"A", "C"})
        self.assertEqual(list(screen.ticker), ["A"])
        a = all_valid.set_index("ticker").loc["A"]
        self.assertAlmostEqual(a.rvol_percentile, 2/3)
        self.assertAlmostEqual(a.consolidation_rs_percentile, 2/3)
        self.assertTrue(pd.isna(audit.set_index("ticker").loc["C", "lean"]))

    def test_strict_filters_ties_and_stable_order(self):
        p, cal, t = fixture()
        f, _ = build_features(p, ["A", "B", "C"], t, cal)
        for col, value in [("excess_return", 0), ("rvol", 1), ("compression_ratio", 1)]:
            g = f.copy()
            g.loc[g.ticker.eq("A"), col] = value
            self.assertTrue(rank_and_screen(g)[1].empty)
        f.loc[:, ["excess_return", "rvol", "compression_ratio", "consolidation_rs"]] = [.02, 2, .5, .01]
        _, _, valid = rank_and_screen(f)
        self.assertTrue((valid.rvol_percentile == 2/3).all())
        self.assertEqual(list(valid.ticker), ["A", "B", "C"])

    def test_bad_windows_flat_pause_empty(self):
        p, cal, t = fixture()
        p["A"].loc[t, "close"] = np.nan
        f, ex = build_features(p, ["A", "B", "MISSING"], t, cal)
        self.assertEqual(len(ex), 2)
        self.assertTrue(rank_and_screen(f)[0].empty)
        f, ex = build_features(p, ["A"], t, cal)
        self.assertTrue(rank_and_screen(f)[0].empty)
        p, cal, t = fixture()
        p["A"].loc[p["A"].index[-3:], ["open", "high", "low", "close"]] = 106
        f, _ = build_features(p, ["A"], t, cal)
        self.assertEqual(f.iloc[0].close_location, .5)
        self.assertTrue(f.iloc[0].flat_consolidation)
        p["A"].loc[p["A"].index[1:21], "volume"] = 0
        self.assertEqual(build_features(p, ["A"], t, cal)[1].iloc[0].reason, "invalid_setup_denominator")

    def test_split_and_missing_spy_session(self):
        p, cal, t = fixture()
        p["A"].loc[t, "stock_splits"] = 2
        self.assertEqual(build_features(p, ["A"], t, cal)[1].iloc[0].reason, "split_in_required_window")
        p["SPY"] = p["SPY"].drop(p["SPY"].index[10])
        with self.assertRaisesRegex(ValueError, "Incomplete SPY"):
            build_features(p, ["A"], t, cal)

    def test_friday_labels_holiday_partial_missing_and_early_close(self):
        self.assertEqual(classify(108, 109, 106, 107), ("continuation", True, True))
        self.assertEqual(classify(106, 109, 106, 107), ("stall", False, True))
        self.assertEqual(classify(107, 109, 106, 107), ("neutral", False, True))
        p, cal, t = fixture()
        decisions = rank_and_screen(build_features(p, ["A", "B"], t, cal)[0])[1]
        friday = t + pd.Timedelta(days=1)
        for ticker in p:
            p[ticker].loc[friday] = [108, 109, 107, 108, 100, 0, 0]
        partial = evaluate(decisions, p, cal, pd.Timestamp("2026-09-25 19:59Z"))
        self.assertEqual(partial.iloc[0].status, "pending")
        self.assertIsNone(partial.iloc[0].friday_return)
        done = evaluate(decisions, p, cal, pd.Timestamp("2026-09-25 20:01Z"))
        self.assertEqual(done.iloc[0].outcome, "continuation")
        p["A"] = p["A"].drop(friday)
        self.assertEqual(evaluate(decisions, p, cal, pd.Timestamp("2026-09-25 20:01Z")).iloc[0].status, "missing_data")
        holiday_cal = schedule("2026-04-01", "2026-04-06")
        self.assertEqual(session_status(pd.Timestamp("2026-04-02"), holiday_cal, pd.Timestamp("2026-04-06 22:00Z")), "holiday")
        early = schedule("2026-11-25", "2026-11-30")
        self.assertEqual(session_status(pd.Timestamp("2026-11-26"), early, pd.Timestamp("2026-11-27 18:01Z")), "completed")

    def test_negative_absolute_impulse_preserved_and_unscorable(self):
        p, cal, t = fixture()
        p["SPY"].loc[p["SPY"].index[21:], ["open", "high", "low", "close"]] = [90, 91, 89, 90]
        p["A"].loc[p["A"].index[21:26], ["open", "high", "low", "close"]] = [95, 96, 94, 95]
        p["A"].loc[p["A"].index[26:], ["open", "high", "low", "close"]] = [95, 96, 94, 95]
        f, _ = build_features(p, ["A", "B"], t, cal)
        screen, audit, _ = rank_and_screen(f)
        a = audit.set_index("ticker").loc["A"]
        self.assertTrue(a.negative_absolute_impulse)
        self.assertFalse(a.scorable)
        self.assertTrue(screen.empty)

    def test_empty_evaluation(self):
        p, cal, t = fixture()
        empty = rank_and_screen(build_features(p, ["B"], t, cal)[0])[1]
        outcomes = evaluate(empty, p, cal, pd.Timestamp("2026-09-25 20:01Z"))
        _, totals, buckets, _ = summary_tables(empty, outcomes)
        self.assertTrue((totals.n == 0).all())
        self.assertEqual(len(buckets), 10)


class ScoreBoundaryTests(unittest.TestCase):
    def test_midpoint_no_rounding_and_final_bin(self):
        p, cal, t = fixture()
        f, _ = build_features(p, ["A", "B", "C"], t, cal)
        f.loc[:, ["excess_return", "rvol", "compression_ratio"]] = [.02, 2., .5]
        f.loc[:, "consolidation_rs"] = [-.1, 0, .1]
        # Rank of A is 1/3. Three components sum to precisely 1.5.
        f.loc[0, ["retention", "close_location"]] = [1., 1/6]
        f.loc[1, ["retention", "close_location"]] = [.5, 1/3-1e-8]
        f.loc[2, ["retention", "close_location"]] = [1., 1.]
        _, audit, _ = rank_and_screen(f)
        by_ticker = audit.set_index("ticker")
        self.assertEqual(by_ticker.loc["A", "lean"], "balanced")
        self.assertEqual(by_ticker.loc["B", "lean"], "stall")
        self.assertEqual(round(by_ticker.loc["B", "lean_score"], 1), 50.)
        friday = t + pd.Timedelta(days=1)
        for bar in p.values():
            bar.loc[friday] = [108, 109, 107, 108, 100, 0, 0]
        outcomes = evaluate(audit, p, cal, pd.Timestamp("2026-09-25 20:01Z"))
        _, _, buckets, _ = summary_tables(audit, outcomes)
        self.assertEqual(buckets[(buckets.population == "all_qualified") & (buckets.bucket == "[80,100]")].iloc[0].n, 1)

    def test_top10_uses_excitement_and_excludes_unscorable(self):
        p, cal, t = fixture()
        f, _ = build_features(p, ["A"], t, cal)
        many = pd.concat([f.assign(ticker=f"T{i:02d}") for i in range(12)], ignore_index=True)
        many.loc[0, "scoring_exclusion"] = "invalid_retention_denominator"
        many.loc[0, "retention"] = np.nan
        screen, audit, valid = rank_and_screen(many)
        self.assertEqual(list(screen.ticker), [f"T{i:02d}" for i in range(1, 11)])
        self.assertEqual(len(audit), 12)
        self.assertTrue((valid.eligible_universe_count == 12).all())


if __name__ == "__main__":
    unittest.main()
