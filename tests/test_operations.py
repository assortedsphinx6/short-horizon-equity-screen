"""Operational contracts for dated archives and outcome-only Friday updates."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import pandas as pd

from src.pipeline import SNAPSHOT_FILES, archive_current_run, update_saved_friday
from main import record_failure


ROOT = Path(__file__).resolve().parents[1]


class WeeklyOperationsTests(unittest.TestCase):
    def copy_saved_run(self, destination):
        for name in SNAPSHOT_FILES:
            source = ROOT / "outputs" / name
            if source.exists():
                shutil.copy2(source, destination / name)

    def test_archive_and_friday_update_preserve_thursday_signal(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            self.copy_saved_run(out)
            dated = archive_current_run(out)
            signal_path = dated / "historical_thursday_screens.csv"
            signal_hash = hashlib.sha256(signal_path.read_bytes()).hexdigest()
            screen_bytes = (dated / "current_thursday_screen.csv").read_bytes()
            self.assertEqual(archive_current_run(out), dated)
            decisions = pd.read_csv(signal_path)
            target = decisions[decisions.decision_date.eq("2026-09-24")]
            friday = pd.Timestamp("2026-09-25")

            def bar(close):
                return pd.DataFrame({
                    "open": [close], "high": [close * 1.01], "low": [close * .99], "close": [close],
                    "volume": [1_000_000.], "stock_splits": [0.], "dividends": [0.],
                }, index=pd.DatetimeIndex([friday], name="date"))

            spy_close = float(target.spy_thursday_close.iloc[0]) * 1.001
            prices = {"SPY": bar(spy_close)}
            for row in target.itertuples():
                prices[row.ticker] = bar(float(row.thursday_close) * 1.01)

            with patch("src.pipeline.download", return_value=(prices, {})):
                update_saved_friday(out, "2026-09-24", pd.Timestamp("2026-09-26T12:00:00Z"))

            self.assertEqual(hashlib.sha256(signal_path.read_bytes()).hexdigest(), signal_hash)
            self.assertEqual((dated / "current_thursday_screen.csv").read_bytes(), screen_bytes)
            outcomes = pd.read_csv(dated / "friday_outcomes.csv")
            updated = outcomes[outcomes.decision_date.eq("2026-09-24")]
            self.assertEqual(len(updated), len(target))
            self.assertTrue(updated.status.eq("completed").all())
            meta = json.loads((dated / "run_metadata.json").read_text())
            self.assertEqual(meta["thursday_decisions_sha256"], signal_hash)
            self.assertIn("outcome_updated_at_utc", meta)
            self.assertEqual((out / "friday_outcomes.csv").read_bytes(),
                             (dated / "friday_outcomes.csv").read_bytes())

    def test_friday_update_rejects_missing_snapshot_and_unfinished_session(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                update_saved_friday(Path(folder), "2026-09-24", pd.Timestamp("2026-09-26T12:00:00Z"))
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            self.copy_saved_run(out)
            archive_current_run(out)
            with self.assertRaises(ValueError):
                update_saved_friday(out, "2026-09-24", pd.Timestamp("2026-09-25T16:00:00Z"))

    def test_friday_failure_does_not_invalidate_saved_core(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            record_failure(SimpleNamespace(output_dir=str(out), update_friday="2026-09-24"),
                           ValueError("Friday is unfinished"))
            self.assertTrue((out / "FRIDAY_UPDATE_FAILED.txt").is_file())
            self.assertFalse((out / "RUN_FAILED.txt").exists())
