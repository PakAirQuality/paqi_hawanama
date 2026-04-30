#!/usr/bin/env bash
# Backfill LLM briefs for historical prediction dates.
# Calls GET /briefs/{date}?regenerate=true once per date (bearer auth).
# Each call is a single Gemini round-trip (~3-10s), so Cloud Run never gets
# blocked by one huge sequential request.
#
# Already-cached dates skip instantly (no LLM call); safe to re-run.
#
# Usage:
#   export TASKS_API_SECRET=<your secret>
#   bash scripts/backfill_briefs.sh
#
# Optional overrides:
#   DAYS_BACK=365   bash scripts/backfill_briefs.sh
#   SLEEP_SECS=2    bash scripts/backfill_briefs.sh   # seconds between dates

set -euo pipefail

API_BASE="${API_BASE:-https://hawanama-152782825429.asia-south1.run.app}"
SECRET="${TASKS_API_SECRET:?TASKS_API_SECRET env var must be set}"
DAYS_BACK="${DAYS_BACK:-365}"
SLEEP_SECS="${SLEEP_SECS:-1}"

echo "Starting backfill: days_back=${DAYS_BACK}"
echo "Target: ${API_BASE}/api/v1/ops/pipeline/briefs/{date}?regenerate=true"
echo ""

generated=0
skipped=0
errors=0

for i in $(seq 0 $((DAYS_BACK - 1))); do
  date=$(python3 -c "from datetime import date, timedelta; print((date.today() - timedelta(days=$i)).strftime('%Y-%m-%d'))")

  http_code=$(curl -s -o /dev/null -w "%{http_code}" \
    -X GET \
    -H "Authorization: Bearer ${SECRET}" \
    "${API_BASE}/api/v1/ops/pipeline/briefs/${date}")

  if [ "$http_code" = "200" ]; then
    echo "[${date}] OK (${http_code})"
    generated=$((generated + 1))
  elif [ "$http_code" = "404" ]; then
    echo "[${date}] SKIP (no prediction data for this date)"
    skipped=$((skipped + 1))
  else
    echo "[${date}] ERROR HTTP ${http_code}" >&2
    errors=$((errors + 1))
  fi

  sleep "${SLEEP_SECS}"
done

echo ""
echo "Done. generated=${generated} skipped=${skipped} errors=${errors}"
if [ "${errors}" -gt 0 ]; then
  exit 1
fi
