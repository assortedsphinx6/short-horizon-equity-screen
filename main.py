"""Command-line entry point for the Deeter Thursday screen."""
import argparse
from pathlib import Path
import sys

from config import MONTHS
from src.pipeline import run_research
from src.report import PORTFOLIO_NOTE


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", help="Completed Thursday YYYY-MM-DD")
    parser.add_argument("--months", type=int, default=MONTHS)
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--replay", action="store_true", help="Use the frozen local data vintage")
    parser.add_argument("--enrich-only", action="store_true", help="Refresh context without changing signals")
    return parser.parse_args()


def record_failure(args, error):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    message = f"{type(error).__name__}: {error}\nRun failed; existing outputs may belong to an older run.\n"
    (output_dir / "RUN_FAILED.txt").write_text(message)
    (output_dir / "pm_note_portfolio_alert.md").write_text(PORTFOLIO_NOTE)
    print(message, file=sys.stderr)


def main():
    args = parse_args()
    try:
        run_research(args)
    except Exception as error:
        record_failure(args, error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
