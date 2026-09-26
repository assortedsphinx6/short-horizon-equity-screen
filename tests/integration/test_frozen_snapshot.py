"""Full pipeline contract against the committed September input vintage."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION") == "1", "run with ./run.sh integration")
class FrozenSnapshotIntegrationTest(unittest.TestCase):
    def test_complete_replay_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "outputs"
            subprocess.run([
                str(ROOT / ".venv/bin/python"), str(ROOT / "main.py"), "--replay",
                "--cache-dir", str(ROOT / "fixtures/frozen_2026-09-24"),
                "--output-dir", str(out),
            ], cwd=folder, check=True, capture_output=True, text=True, timeout=180)
            meta = json.loads((out / "run_metadata.json").read_text())
            screen = pd.read_csv(out / "current_thursday_screen.csv")
            candidates = pd.read_csv(out / "current_thursday_candidates_audit.csv")
            audit = pd.read_csv(out / "thursday_audit.csv")
            row = audit[audit.decision_date.eq(meta["decision_date"])].iloc[0]

            self.assertEqual(meta["decision_date"], "2026-09-24")
            self.assertEqual(meta["universe_count"], 503)
            self.assertEqual(int(row.eligible_universe_count), 502)
            self.assertEqual(len(candidates), 65)
            self.assertEqual(len(screen), 10)
            self.assertEqual(screen.ticker.tolist(),
                             ["WBD", "SWKS", "CIEN", "QCOM", "AMD", "DXCM", "COIN", "FFIV", "CRWD", "INTC"])
            self.assertEqual(meta["thursday_decisions_sha256"],
                             "70123e0a0ade226fd23f325d67308263bafe96d4a230ddcdaac89189ff752f86")
            self.assertTrue((out / "runs" / "2026-09-24" / "current_thursday_screen.csv").is_file())
