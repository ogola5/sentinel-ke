#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
API_KEY="${HUB_API_KEY:-}"
START_AT="${START_AT:-}"
END_AT="${END_AT:-}"
SECTION_CODE="${SECTION_CODE:-}"
LIMIT="${LIMIT:-1000}"
CONCURRENCY="${CONCURRENCY:-20}"
RATE_PER_SEC="${RATE_PER_SEC:-120}"

if [[ -z "${API_KEY}" || -z "${START_AT}" || -z "${END_AT}" ]]; then
  echo "Usage:"
  echo "  HUB_API_KEY=<source_raw_api_key> START_AT=<iso> END_AT=<iso> [SECTION_CODE=telecom] \\"
  echo "  [BASE_URL=http://localhost:8000] [LIMIT=1000] [CONCURRENCY=20] [RATE_PER_SEC=120] \\"
  echo "  bash backend/scripts/replay_incident.sh"
  exit 2
fi

CMD=(
  python -m app.demo.replay
  --base-url "${BASE_URL}"
  --api-key "${API_KEY}"
  --start-at "${START_AT}"
  --end-at "${END_AT}"
  --limit "${LIMIT}"
  --concurrency "${CONCURRENCY}"
  --rate-per-sec "${RATE_PER_SEC}"
)

if [[ -n "${SECTION_CODE}" ]]; then
  CMD+=(--section-code "${SECTION_CODE}")
fi

PYTHONPATH=backend "${CMD[@]}"
