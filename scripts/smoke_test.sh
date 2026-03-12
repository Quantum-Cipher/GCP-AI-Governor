#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MAIN_APP="${PROJECT_ROOT}/daemon/main.py"
SIMULATOR="${PROJECT_ROOT}/daemon/simulator/simulate_event.py"

if [ -d "${PROJECT_ROOT}/.venv" ]; then
  source "${PROJECT_ROOT}/.venv/bin/activate"
fi

python3 "${MAIN_APP}" > "${PROJECT_ROOT}/smoke_test_server.log" 2>&1 &
SERVER_PID=$!

cleanup() {
  kill "${SERVER_PID}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sleep 3

echo "=== Health Check ==="
curl --fail http://127.0.0.1:8080/health
echo
echo

echo "=== Simulation Run ==="
python3 "${SIMULATOR}"
echo
echo "Smoke test complete."
