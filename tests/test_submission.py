"""Submission-level checks for commands, required artifacts, and dashboard integrity."""
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SubmissionTests(unittest.TestCase):
    def test_required_assignment_artifacts_exist(self):
        required = [
            "README.md", "RESEARCH_SPEC.md", "requirements.txt", "main.py", "run.sh",
            "outputs/current_thursday_screen.csv", "outputs/current_thursday_screen.md",
            "outputs/historical_summary.md", "outputs/historical_thursday_screens.csv",
            "outputs/pm_note_screen.md", "outputs/pm_note_portfolio_alert.md",
            "dashboard/dist/index.html",
        ]
        missing = [name for name in required if not (ROOT / name).is_file()]
        self.assertEqual(missing, [])

    def test_launcher_and_cli_are_valid(self):
        subprocess.run(["bash", "-n", str(ROOT / "run.sh")], check=True)
        result = subprocess.run(
            [str(ROOT / ".venv/bin/python"), "main.py", "--help"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        self.assertIn("--replay", result.stdout)
        self.assertIn("--enrich-only", result.stdout)

    def test_dashboard_has_ten_unique_signals_and_plain_language(self):
        page = (ROOT / "dashboard/dist/index.html").read_text()
        tickers = re.findall(r"\{t:'([A-Z]+)',lean:", page)
        self.assertEqual(len(tickers), 10)
        self.assertEqual(len(set(tickers)), 10)
        self.assertIn("Why it leans this way", page)
        self.assertIn("not a probability or trade recommendation", page)
        self.assertIn("503 S&amp;P 500 constituent securities were loaded", page)
        self.assertIn("APH was excluded", page)

    def test_no_platform_branding_or_developer_paths_in_submission(self):
        searchable = [
            ROOT / "README.md", ROOT / "RESEARCH_SPEC.md", ROOT / "main.py",
            *sorted((ROOT / "src").glob("*.py")),
            ROOT / "dashboard/dist/index.html",
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
