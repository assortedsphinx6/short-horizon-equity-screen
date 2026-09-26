"""Submission-level checks for commands, required artifacts, and dashboard integrity."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.dashboard import write_dashboard
from src.report import write_pm_note


ROOT = Path(__file__).resolve().parents[1]


class SubmissionTests(unittest.TestCase):
    def test_required_assignment_artifacts_exist(self):
        required = [
            "README.md", "RESEARCH_SPEC.md", "docs/methodology-flow.md",
            "fixtures/frozen_2026-09-24/manifest.json", "fixtures/frozen_2026-09-24/prices.csv.gz",
            "requirements.txt", "main.py", "run.sh",
            "outputs/deliverables/dashboard.html", "outputs/deliverables/current_thursday_screen.md",
            "outputs/deliverables/pm_note_screen.md", "outputs/deliverables/pm_note_portfolio_alert.md",
            "outputs/deliverables/historical_summary.md", "outputs/data/current_thursday_screen.csv",
            "outputs/data/historical_thursday_screens.csv", "task.md",
        ]
        missing = [name for name in required if not (ROOT / name).is_file()]
        self.assertEqual(missing, [])

    def test_readme_links_the_detailed_flow(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("```mermaid", readme)
        self.assertIn("[detailed calculation, timing and exclusion flow](docs/methodology-flow.md)", readme)
        detail = (ROOT / "docs/methodology-flow.md").read_text()
        self.assertIn("```mermaid", detail)
        for threshold in ["Excess return > 0", "RVOL > 1", "Compression < 1"]:
            self.assertIn(threshold, detail)

    def test_launcher_and_cli_are_valid(self):
        subprocess.run(["bash", "-n", str(ROOT / "run.sh")], check=True)
        result = subprocess.run(
            [sys.executable, "main.py", "--help"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        self.assertIn("--replay", result.stdout)
        self.assertIn("--enrich-only", result.stdout)
        self.assertNotIn("--update-friday", result.stdout)

    def test_note_and_dashboard_are_exact_views_of_saved_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            shutil.copytree(ROOT / "outputs" / "data", out / "data")
            write_pm_note(out)
            write_dashboard(out)
            for name in ["pm_note_screen.md", "dashboard.html"]:
                with self.subTest(name=name):
                    self.assertEqual((out / "deliverables" / name).read_text(),
                                     (ROOT / "outputs" / "deliverables" / name).read_text())

    def test_dashboard_lists_saved_screen_without_unsupported_claims(self):
        page = (ROOT / "outputs/deliverables/dashboard.html").read_text()
        screen = pd.read_csv(ROOT / "outputs/data/current_thursday_screen.csv")
        for r in screen.itertuples():
            self.assertIn(f"<span class='t'>{r.ticker}</span>", page)
            self.assertIn(f"lean score {r.lean_score:.1f}", page)
        self.assertEqual(page.count("<span class='t'>"), len(screen))
        self.assertIn("not a probability or a trade recommendation", page)
        self.assertIn("Data-quality status", page)
        self.assertIn("latest completed market bar", page)
        for phrase in ["more likely", "useful signal", "proven edge"]:
            self.assertNotIn(phrase, page.lower())

    def test_dashboard_explains_the_actual_friday_status(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            shutil.copytree(ROOT / "outputs" / "data", out / "data")
            audit = pd.read_csv(out / "data" / "thursday_audit.csv")
            for status, phrase in [("pending", "outcome is pending"), ("completed", "are included in the evidence"),
                                   ("holiday", "Monday is not substituted")]:
                audit.loc[audit.decision_date.eq("2026-09-24"), "friday_status"] = status
                audit.to_csv(out / "data" / "thursday_audit.csv", index=False)
                write_dashboard(out)
                with self.subTest(status=status):
                    self.assertIn(phrase, (out / "deliverables" / "dashboard.html").read_text())

    def test_no_platform_branding_or_developer_paths_in_submission(self):
        searchable = [
            ROOT / "README.md", ROOT / "RESEARCH_SPEC.md", ROOT / "main.py",
            *sorted((ROOT / "src").glob("*.py")),
            ROOT / "outputs/deliverables/dashboard.html",
        ]
        forbidden = (
            "chat" + "gpt", "open" + "ai", "co" + "dex",
            "/users/" + "assorted" + "sphinx",
        )
        for path in searchable:
            text = path.read_text().lower()
            for token in forbidden:
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(token, text)

    def test_pm_notes_meet_format_contract(self):
        screen_lines = [line for line in (ROOT / "outputs/deliverables/pm_note_screen.md").read_text().splitlines() if line.strip()]
        alert_words = (ROOT / "outputs/deliverables/pm_note_portfolio_alert.md").read_text().split()
        self.assertEqual(len(screen_lines), 8)
        self.assertGreaterEqual(len(alert_words), 250)
        self.assertLessEqual(len(alert_words), 450)
        self.assertIn("conceptual", " ".join(alert_words).lower())


if __name__ == "__main__":
    unittest.main()
