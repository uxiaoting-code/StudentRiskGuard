#!/usr/bin/env bash
set -Eeuo pipefail

export API_PORT="${API_PORT:-8000}"
export RISKGUARD_API_URL="${RISKGUARD_API_URL:-http://127.0.0.1:${API_PORT}}"
export AUTH_DB_PATH="${AUTH_DB_PATH:-/tmp/studentriskguard/auth.db}"

mkdir -p "$(dirname "${AUTH_DB_PATH}")"

python -m uvicorn riskguard.api.main:app \
  --app-dir src \
  --host 127.0.0.1 \
  --port "${API_PORT}" &
api_pid=$!

cleanup() {
  kill "${api_pid}" 2>/dev/null || true
  wait "${api_pid}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

python - <<'PY'
import os
import sys
import time
import urllib.request

port = int(os.getenv("API_PORT", "8000"))
health_url = f"http://127.0.0.1:{port}/health"

for _ in range(60):
    try:
        with urllib.request.urlopen(health_url, timeout=1) as response:
            if response.status == 200:
                print("FastAPI is ready.", flush=True)
                raise SystemExit(0)
    except Exception:
        time.sleep(1)

print(f"FastAPI did not become ready: {health_url}", file=sys.stderr, flush=True)
raise SystemExit(1)
PY

streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port 7860 \
  --server.headless true \
  --browser.gatherUsageStats false
