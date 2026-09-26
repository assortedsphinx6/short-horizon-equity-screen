#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"

usage() {
  echo "Usage: ./run.sh {fresh|replay|update-friday|test|integration|dashboard|setup} [Thursday]"
  echo "  fresh      Download current data and rebuild all outputs"
  echo "  replay     Rebuild from the frozen local data cache"
  echo "  update-friday YYYY-MM-DD  Append outcomes to a saved Thursday run"
  echo "  test       Run the complete deterministic test suite"
  echo "  integration Run the slower frozen end-to-end contract"
  echo "  dashboard  Open the portfolio-manager dashboard locally"
  echo "  setup      Create the virtual environment and install dependencies"
}

require_environment() {
  if [[ ! -x "$PYTHON" ]]; then
    echo "Environment missing. Run ./run.sh setup first." >&2
    exit 1
  fi
}

open_dashboard() {
  require_environment
  local port="${DASHBOARD_PORT:-8765}"
  "$PYTHON" -m webbrowser "http://127.0.0.1:${port}/dashboard.html" >/dev/null 2>&1 &
  echo "Dashboard: http://127.0.0.1:${port}/dashboard.html"
  echo "Press Ctrl-C to stop."
  exec "$PYTHON" -m http.server "$port" --directory "$ROOT/outputs"
}

cd "$ROOT"
case "${1:-}" in
  setup)
    python3 -m venv .venv
    "$PYTHON" -m pip install -r requirements.txt
    ;;
  fresh)
    require_environment
    exec "$PYTHON" main.py
    ;;
  replay)
    require_environment
    cache_dir="$ROOT/cache"
    if [[ ! -f "$cache_dir/manifest.json" ]]; then
      cache_dir="$ROOT/fixtures/frozen_2026-09-24"
    fi
    exec "$PYTHON" main.py --replay --cache-dir "$cache_dir" --output-dir outputs/replay
    ;;
  update-friday)
    require_environment
    if [[ -z "${2:-}" ]]; then
      echo "Usage: ./run.sh update-friday YYYY-MM-DD" >&2
      exit 2
    fi
    exec "$PYTHON" main.py --update-friday "$2"
    ;;
  test)
    require_environment
    exec "$PYTHON" -m unittest discover -s tests -v
    ;;
  integration)
    require_environment
    exec env RUN_INTEGRATION=1 "$PYTHON" -m unittest discover -s tests/integration -v
    ;;
  dashboard)
    open_dashboard
    ;;
  *)
    usage
    exit 2
    ;;
esac
