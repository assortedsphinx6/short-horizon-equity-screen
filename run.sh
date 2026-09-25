#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"

usage() {
  echo "Usage: ./run.sh {fresh|replay|test|dashboard|setup}"
  echo "  fresh      Download current data and rebuild all outputs"
  echo "  replay     Rebuild from the frozen local data cache"
  echo "  test       Run the complete deterministic test suite"
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
  "$PYTHON" -m webbrowser "http://127.0.0.1:${port}/" >/dev/null 2>&1 &
  echo "Dashboard: http://127.0.0.1:${port}/"
  echo "Press Ctrl-C to stop."
  exec "$PYTHON" -m http.server "$port" --directory "$ROOT/dashboard/dist"
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
    exec "$PYTHON" main.py --replay --output-dir outputs/replay
    ;;
  test)
    require_environment
    exec "$PYTHON" -m unittest discover -s tests -v
    ;;
  dashboard)
    open_dashboard
    ;;
  *)
    usage
    exit 2
    ;;
esac
