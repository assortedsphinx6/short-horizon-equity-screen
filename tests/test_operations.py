"""Dated-archive contract: an archived Thursday is never overwritten, and a rerun never fails because of it."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import pandas as pd

from types import SimpleNamespace

from main import record_failure
from src.pipeline import SNAPSHOT_FILES, archive_current_run


ROOT = Path(__file__).resolve().parents[1]


def snapshot(folder):
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


class DatedArchiveTests(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())
        for name in SNAPSHOT_FILES:
            if (ROOT / "outputs" / name).exists():
                (self.out / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / "outputs" / name, self.out / name)

    def tearDown(self):
        shutil.rmtree(self.out)

    def rerun_with_revised_history(self):
        """Simulate a later fresh run of the same Thursday on re-adjusted Yahoo prices."""
        history = pd.read_csv(self.out / "data" / "historical_thursday_screens.csv", float_precision="round_trip")
        history.loc[0, "thursday_close"] *= 1.0001
        history.to_csv(self.out / "data" / "historical_thursday_screens.csv", index=False)
        meta = json.loads((self.out / "data" / "run_metadata.json").read_text())
        meta["thursday_decisions_sha256"] = hashlib.sha256(
            (self.out / "data" / "historical_thursday_screens.csv").read_bytes()).hexdigest()
        (self.out / "data" / "run_metadata.json").write_text(json.dumps(meta, indent=2))

    def test_new_decision_date_is_archived(self):
        dated = archive_current_run(self.out)
        self.assertEqual(dated, self.out / "runs" / "2026-09-24")
        self.assertEqual((dated / "data" / "current_thursday_screen.csv").read_bytes(),
                         (self.out / "data" / "current_thursday_screen.csv").read_bytes())

    def test_same_date_same_hash_reuses_archive(self):
        dated = archive_current_run(self.out)
        frozen = snapshot(dated)
        self.assertEqual(archive_current_run(self.out), dated)
        self.assertEqual(snapshot(dated), frozen)
        self.assertEqual(json.loads((self.out / "data" / "run_metadata.json").read_text())["archive_status"],
                         "existing_snapshot_identical")

    def test_same_date_revised_vintage_preserves_archive_without_failing(self):
        dated = archive_current_run(self.out)
        frozen = snapshot(dated)
        self.rerun_with_revised_history()
        self.assertEqual(archive_current_run(self.out), dated)  # no exception
        self.assertEqual(snapshot(dated), frozen)
        self.assertEqual(json.loads((self.out / "data" / "run_metadata.json").read_text())["archive_status"],
                         "existing_snapshot_preserved")

    def test_tampered_archive_still_fails_loudly(self):
        dated = archive_current_run(self.out)
        with open(dated / "data" / "historical_thursday_screens.csv", "a") as fh:
            fh.write("tampered\n")
        with self.assertRaisesRegex(ValueError, "failed its decision hash"):
            archive_current_run(self.out)



class FailureReportTests(unittest.TestCase):
    def test_failure_report_has_traceback_and_leaves_deliverables_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            try:
                raise RuntimeError("Yahoo SPY download failed")
            except RuntimeError as error:
                record_failure(SimpleNamespace(output_dir=str(out)), error)
            report = (out / "RUN_FAILED.txt").read_text()
            self.assertIn("RuntimeError: Yahoo SPY download failed", report)
            self.assertIn("Traceback (most recent call last)", report)
            self.assertFalse((out / "deliverables").exists())


if __name__ == "__main__":
    unittest.main()
