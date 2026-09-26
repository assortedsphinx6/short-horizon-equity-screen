"""Submission-level checks for commands, required artifacts, and dashboard integrity."""
import shutil
import subprocess
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
            ".github/workflows/weekly-screen.yml", "validation/README.md", "validation/prospective_log.csv",
            "fixtures/frozen_2026-09-24/manifest.json", "fixtures/frozen_2026-09-24/prices.csv.gz",
            "requirements.txt", "main.py", "run.sh",
            "outputs/current_thursday_screen.csv", "outputs/current_thursday_screen.md",
            "outputs/historical_summary.md", "outputs/historical_thursday_screens.csv",
            "outputs/pm_note_screen.md", "outputs/pm_note_portfolio_alert.md",
            "outputs/dashboard.html", "task.md",
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
            [str(ROOT / ".venv/bin/python"), "main.py", "--help"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        self.assertIn("--replay", result.stdout)
        self.assertIn("--enrich-only", result.stdout)
        self.assertIn("--update-friday", result.stdout)

    def test_note_and_dashboard_are_exact_views_of_saved_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            for path in (ROOT / "outputs").glob("*"):
                if path.suffix in {".csv", ".json"}:
                    shutil.copy(path, out / path.name)
            write_pm_note(out)
            write_dashboard(out)
            for name in ["pm_note_screen.md", "dashboard.html"]:
                with self.subTest(name=name):
                    self.assertEqual((out / name).read_text(), (ROOT / "outputs" / name).read_text())

    def test_dashboard_lists_saved_screen_without_unsupported_claims(self):
        page = (ROOT / "outputs/dashboard.html").read_text()
        screen = pd.read_csv(ROOT / "outputs/current_thursday_screen.csv")
        for r in screen.itertuples():
            self.assertIn(f"<span class='t'>{r.ticker}</span>", page)
            self.assertIn(f"lean score {r.lean_score:.1f}", page)
        self.assertEqual(page.count("<span class='t'>"), len(screen))
        self.assertIn("not a probability or a trade recommendation", page)
        self.assertIn("Data-quality status", page)
        self.assertIn("latest completed market bar", page)
        for phrase in ["more likely", "useful signal", "proven edge"]:
            self.assertNotIn(phrase, page.lower())

    def test_no_platform_branding_or_developer_paths_in_submission(self):
        searchable = [
            ROOT / "README.md", ROOT / "RESEARCH_SPEC.md", ROOT / "main.py",
            *sorted((ROOT / "src").glob("*.py")),
            ROOT / "outputs/dashboard.html",
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
        screen_lines = [line for line in (ROOT / "outputs/pm_note_screen.md").read_text().splitlines() if line.strip()]
        alert_words = (ROOT / "outputs/pm_note_portfolio_alert.md").read_text().split()
        self.assertEqual(len(screen_lines), 8)
        self.assertGreaterEqual(len(alert_words), 250)
        self.assertLessEqual(len(alert_words), 450)
        self.assertIn("conceptual", " ".join(alert_words).lower())


if __name__ == "__main__":
    unittest.main()
