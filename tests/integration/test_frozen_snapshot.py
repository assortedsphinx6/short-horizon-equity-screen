"""Full pipeline contract against the committed September input vintage."""
import json
import os
from pathlib import Path
import subprocess
import sys
import hashlib
import tempfile
import unittest
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
FROZEN_HASH = "70123e0a0ade226fd23f325d67308263bafe96d4a230ddcdaac89189ff752f86"


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION") == "1", "run with ./run.sh integration")
class FrozenSnapshotIntegrationTest(unittest.TestCase):
    def test_complete_replay_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "outputs"
            subprocess.run([
                sys.executable, str(ROOT / "main.py"), "--replay",
                "--cache-dir", str(ROOT / "fixtures/frozen_2026-09-24"),
                "--output-dir", str(out),
            ], cwd=folder, check=True, capture_output=True, text=True, timeout=180)
            meta = json.loads((out / "data" / "run_metadata.json").read_text())
            screen = pd.read_csv(out / "data" / "current_thursday_screen.csv")
            candidates = pd.read_csv(out / "data" / "current_thursday_candidates_audit.csv")
            audit = pd.read_csv(out / "data" / "thursday_audit.csv")
            row = audit[audit.decision_date.eq(meta["decision_date"])].iloc[0]

            self.assertEqual(meta["decision_date"], "2026-09-24")
            self.assertEqual(meta["universe_count"], 503)
            self.assertEqual(int(row.eligible_universe_count), 502)
            self.assertEqual(len(candidates), 65)
            self.assertEqual(len(screen), 10)
            self.assertEqual(screen.ticker.tolist(),
                             ["WBD", "SWKS", "CIEN", "QCOM", "AMD", "DXCM", "COIN", "FFIV", "CRWD", "INTC"])
            self.assertEqual(meta["thursday_decisions_sha256"], FROZEN_HASH)
            self.assertTrue((out / "runs" / "2026-09-24" / "data" / "current_thursday_screen.csv").is_file())

    def test_full_replay_months_later_reproduces_the_frozen_hash(self):
        from src.pipeline import run_research
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            args = SimpleNamespace(as_of=None, months=12, output_dir=str(out),
                                   cache_dir=str(ROOT / "fixtures/frozen_2026-09-24"), replay=True,
                                   enrich_only=False, render_only=False)
            run_research(args, now=pd.Timestamp("2027-06-01T12:00:00Z"))
            data = out / "data"
            self.assertEqual(hashlib.sha256((data / "historical_thursday_screens.csv").read_bytes()).hexdigest(),
                             FROZEN_HASH)
            audit = pd.read_csv(data / "thursday_audit.csv")
            self.assertEqual((len(audit), int(audit.scanned.sum())), (53, 50))
            self.assertEqual(audit.friday_status[audit.scanned].value_counts().to_dict(),
                             {"completed": 46, "holiday": 3, "pending": 1})
