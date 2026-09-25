"""Independent, adversarial checks for leakage and saved-output reconciliation."""
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from src.data import normalize, schedule
from src.evaluate import evaluate, summary_tables
from src.features import build_features
from src.screen import rank_and_screen
from test_research import fixture


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"


def decisions(prices, calendar, thursday, tickers=("A", "B", "C")):
    features, excluded = build_features(prices, list(tickers), thursday, calendar)
    screen, candidates, ranked = rank_and_screen(features)
    return excluded, screen, candidates, ranked


class NoLookAheadAuditTests(unittest.TestCase):
    def test_truncated_data_equals_full_data_with_explicit_as_of(self):
        prices, cal, t = fixture()
        full = {symbol: frame.copy() for symbol, frame in prices.items()}
        future_dates = cal.loc[t + pd.Timedelta(days=1):].index[:3]
        for symbol, frame in full.items():
            for i, date in enumerate(future_dates, start=1):
                frame.loc[date] = [100 + i, 102 + i, 99 + i, 101 + i, 10_000 * i, 0, 0]
        truncated = {symbol: frame.loc[:t].copy() for symbol, frame in full.items()}
        for left, right in zip(decisions(truncated, cal, t), decisions(full, cal, t)):
            assert_frame_equal(left, right, check_like=False)

    def test_future_price_volume_and_benchmark_mutations_are_inert(self):
        prices, cal, t = fixture()
        future = cal.loc[t + pd.Timedelta(days=1):].index[:3]
        for frame in prices.values():
            for date in future:
                frame.loc[date] = [100, 102, 98, 100, 100, 0, 0]
        before = decisions(prices, cal, t)
        mutated = {symbol: frame.copy() for symbol, frame in prices.items()}
        for symbol, frame in mutated.items():
            for i, date in enumerate(future, start=1):
                base = (1_000_000 if symbol == "SPY" else 10_000) * i
                frame.loc[date, ["open", "high", "low", "close"]] = [base, base * 1.1, base * .9, base * 1.05]
                frame.loc[date, "volume"] = 1e15 / i
        after = decisions(mutated, cal, t)
        for left, right in zip(before, after):
            assert_frame_equal(left, right)

    def test_removing_friday_and_all_future_data_does_not_break_signal(self):
        prices, cal, t = fixture()
        base = decisions(prices, cal, t)
        stripped = {symbol: frame.loc[:t].copy() for symbol, frame in prices.items()}
        for left, right in zip(base, decisions(stripped, cal, t)):
            assert_frame_equal(left, right)

    def test_outcome_mutation_changes_only_evaluation(self):
        prices, cal, t = fixture()
        _, _, candidates, _ = decisions(prices, cal, t, ("A", "B"))
        friday = t + pd.Timedelta(days=1)
        for frame in prices.values():
            frame.loc[friday] = [108, 109, 107, 108, 100, 0, 0]
        frozen = candidates.copy(deep=True)
        first = evaluate(candidates, prices, cal, pd.Timestamp("2026-09-25 21:00Z"))
        prices["A"].loc[friday, ["open", "high", "low", "close"]] = [50, 51, 49, 50]
        second = evaluate(candidates, prices, cal, pd.Timestamp("2026-09-25 21:00Z"))
        assert_frame_equal(candidates, frozen)
        self.assertEqual(first.loc[0, "outcome"], "continuation")
        self.assertEqual(second.loc[0, "outcome"], "stall")

    def test_missing_friday_stock_is_retained_as_missing_outcome(self):
        prices, cal, t = fixture()
        _, _, candidates, _ = decisions(prices, cal, t, ("A", "B"))
        friday = t + pd.Timedelta(days=1)
        prices["SPY"].loc[friday] = [100, 101, 99, 100, 100, 0, 0]
        outcomes = evaluate(candidates, prices, cal, pd.Timestamp("2026-09-25 21:00Z"))
        self.assertEqual(list(outcomes.ticker), list(candidates.ticker))
        self.assertTrue((outcomes.status == "missing_data").all())

    def test_candidate_order_is_independent_of_input_row_order(self):
        prices, cal, t = fixture()
        features, _ = build_features(prices, ["A", "B", "C"], t, cal)
        features.loc[:, ["excess_return", "rvol", "compression_ratio"]] = [.02, 2, .5]
        a = rank_and_screen(features)[1].reset_index(drop=True)
        b = rank_and_screen(features.sample(frac=1, random_state=17))[1].reset_index(drop=True)
        assert_frame_equal(a, b)

    def test_peer_future_data_cannot_change_cross_sectional_ranks(self):
        prices, cal, t = fixture()
        before = decisions(prices, cal, t)[3]
        friday = t + pd.Timedelta(days=1)
        prices["C"].loc[friday] = [1e8, 2e8, 5e7, 1.5e8, 1e16, 0, 0]
        after = decisions(prices, cal, t)[3]
        assert_frame_equal(before, after)


class ArithmeticAndInputAuditTests(unittest.TestCase):
    def test_price_and_volume_scale_invariance(self):
        prices, cal, t = fixture()
        before = build_features(prices, ["A"], t, cal)[0].iloc[0]
        scaled = {symbol: frame.copy() for symbol, frame in prices.items()}
        scaled["A"].loc[:, ["open", "high", "low", "close"]] *= 7.25
        scaled["A"].loc[:, "volume"] *= 13
        after = build_features(scaled, ["A"], t, cal)[0].iloc[0]
        for field in ["stock_impulse_return", "excess_return", "rvol", "current_range",
                      "normal_range", "compression_ratio", "retention", "close_location",
                      "consolidation_rs"]:
            self.assertAlmostEqual(before[field], after[field], places=12, msg=field)

    def test_old_single_volume_spike_does_not_move_median_baseline(self):
        prices, cal, t = fixture()
        baseline = build_features(prices, ["A"], t, cal)[0].iloc[0]
        prices["A"].iloc[5, prices["A"].columns.get_loc("volume")] = 1e12
        changed = build_features(prices, ["A"], t, cal)[0].iloc[0]
        self.assertEqual(baseline.baseline_volume, changed.baseline_volume)
        self.assertEqual(baseline.rvol, changed.rvol)

    def test_each_required_missing_bar_excludes_instead_of_shortening(self):
        for position in range(29):
            with self.subTest(position=position):
                prices, cal, t = fixture()
                prices["A"].iloc[position, prices["A"].columns.get_loc("close")] = np.nan
                features, excluded = build_features(prices, ["A"], t, cal)
                self.assertTrue(features.empty)
                self.assertEqual(excluded.iloc[0].reason, "missing_or_nonfinite_ohlcv")

    def test_invalid_ohlc_and_nonfinite_or_negative_volume_are_excluded(self):
        changes = [
            ("high", 90), ("low", 110), ("close", 103),
            ("volume", -1), ("volume", np.inf), ("volume", np.nan),
        ]
        for column, value in changes:
            with self.subTest(column=column, value=value):
                prices, cal, t = fixture()
                prices["A"].loc[t, column] = value
                features, excluded = build_features(prices, ["A"], t, cal)
                self.assertTrue(features.empty)
                self.assertEqual(len(excluded), 1)

    def test_normalization_sorts_dates_and_rejects_duplicates(self):
        prices, _, _ = fixture()
        shuffled = prices["A"].sample(frac=1, random_state=2)
        normalized = normalize(shuffled, "A")
        self.assertTrue(normalized.index.is_monotonic_increasing)
        duplicate = pd.concat([prices["A"], prices["A"].iloc[[0]]])
        with self.assertRaisesRegex(ValueError, "Duplicate dates"):
            normalize(duplicate, "A")


class SavedOutputAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.decisions = pd.read_csv(OUTPUTS / "historical_thursday_screens.csv")
        cls.outcomes = pd.read_csv(OUTPUTS / "friday_outcomes.csv")

    def test_frozen_hash_unique_keys_and_date_contract(self):
        import hashlib
        meta = json.loads((OUTPUTS / "run_metadata.json").read_text())
        digest = hashlib.sha256((OUTPUTS / "historical_thursday_screens.csv").read_bytes()).hexdigest()
        self.assertEqual(digest, meta["thursday_decisions_sha256"])
        self.assertFalse(self.decisions.duplicated(["decision_date", "ticker"]).any())
        self.assertFalse(self.outcomes.duplicated(["decision_date", "ticker"]).any())
        d = pd.to_datetime(self.outcomes.decision_date)
        o = pd.to_datetime(self.outcomes.outcome_date)
        self.assertTrue(((o - d) == pd.Timedelta(days=1)).all())
        self.assertTrue((d.dt.weekday == 3).all())
        self.assertTrue((o.dt.weekday == 4).all())

    def test_saved_summary_is_independently_recomputed(self):
        _, totals, buckets, sanity = summary_tables(self.decisions, self.outcomes)
        expected = {
            "outcome_summary.csv": totals,
            "lean_buckets.csv": buckets,
            "lean_sanity.csv": sanity,
        }
        for filename, computed in expected.items():
            with self.subTest(filename=filename):
                saved = pd.read_csv(OUTPUTS / filename)
                assert_frame_equal(saved, computed, check_dtype=False, check_exact=False, rtol=1e-13, atol=1e-15)

    def test_counts_reconcile_and_incomplete_outcomes_have_no_labels(self):
        completed = self.outcomes[self.outcomes.status.eq("completed")]
        self.assertEqual(len(completed), completed.outcome.isin(["continuation", "neutral", "stall"]).sum())
        incomplete = self.outcomes[~self.outcomes.status.eq("completed")]
        self.assertTrue(incomplete.outcome.isna().all())
        self.assertTrue(incomplete.friday_return.isna().all())
        for population, frame in [("all_qualified", completed),
                                  ("pm_top10", completed.merge(self.decisions[["decision_date", "ticker", "pm_visible"]],
                                                               on=["decision_date", "ticker"], validate="one_to_one")
                                   .query("pm_visible == True"))]:
            row = pd.read_csv(OUTPUTS / "outcome_summary.csv").set_index("population").loc[population]
            self.assertEqual(int(row.n), len(frame))
            self.assertEqual(int(row.continuation_count + row.neutral_count + row.stall_count), len(frame))

    def test_pm_note_and_score_bounds(self):
        lines = [line for line in (OUTPUTS / "pm_note_screen.md").read_text().splitlines() if line.strip()]
        self.assertEqual(len(lines), 8)
        self.assertTrue(self.decisions.excitement_score.between(0, 100).all())
        scored = self.decisions[self.decisions.scorable.astype(bool)]
        self.assertTrue(scored.lean_score.between(0, 100).all())
        self.assertTrue(np.isfinite(scored[["excitement_score", "lean_score"]].to_numpy()).all())


if __name__ == "__main__":
    unittest.main()
