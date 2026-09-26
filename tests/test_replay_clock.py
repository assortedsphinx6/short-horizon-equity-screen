"""A frozen replay must not depend on the machine's clock: every date window comes from the fixture."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import pandas as pd

from src.pipeline import run_research

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "frozen_2026-09-24"
CLOCKS = ["2026-09-26T12:00:00Z", "2026-12-01T12:00:00Z", "2027-06-01T12:00:00Z"]


def replay_summary(now, months=1):
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        args = SimpleNamespace(as_of=None, months=months, output_dir=str(out), cache_dir=str(FIXTURE), replay=True,
                               enrich_only=False, render_only=False)
        run_research(args, now=pd.Timestamp(now))
        data = out / "data"
        meta = json.loads((data / "run_metadata.json").read_text())
        audit = pd.read_csv(data / "thursday_audit.csv")
        return dict(
            decision_date=meta["decision_date"],
            weeks=audit[["decision_date", "scanned", "friday_status", "eligible_universe_count", "qualified_count"]]
            .to_dict("records"),
            friday_status=pd.read_csv(data / "friday_outcomes.csv").status.value_counts().to_dict(),
            top10=pd.read_csv(data / "current_thursday_screen.csv").ticker.tolist(),
            qualified=len(pd.read_csv(data / "current_thursday_candidates_audit.csv")),
            decision_hash=hashlib.sha256((data / "historical_thursday_screens.csv").read_bytes()).hexdigest(),
        )


class ReplayClockTests(unittest.TestCase):
    def test_replay_is_identical_on_later_wall_clocks(self):
        baseline = replay_summary(CLOCKS[0])
        self.assertEqual(baseline["decision_date"], "2026-09-24")
        self.assertEqual(baseline["top10"],
                         ["WBD", "SWKS", "CIEN", "QCOM", "AMD", "DXCM", "COIN", "FFIV", "CRWD", "INTC"])
        self.assertEqual(baseline["qualified"], 65)
        for clock in CLOCKS[1:]:
            with self.subTest(clock=clock):
                self.assertEqual(replay_summary(clock), baseline)


if __name__ == "__main__":
    unittest.main()
