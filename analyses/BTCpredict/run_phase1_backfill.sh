#!/usr/bin/env bash
# Full Phase 1 backfill — safe to run in background:
#   nohup ./analyses/BTCpredict/run_phase1_backfill.sh &
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
LOG="analyses/BTCpredict/data/logs/phase1_full_ingest.log"
mkdir -p analyses/BTCpredict/data/logs
echo "=== Phase 1 full backfill $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LOG"
PYTHONUNBUFFERED=1 .venv/bin/python analyses/BTCpredict/run_phase1_ingest.py 2>&1 | tee -a "$LOG"
INGEST_EXIT=${PIPESTATUS[0]}
if [[ "$INGEST_EXIT" -eq 0 ]]; then
  PYTHONUNBUFFERED=1 .venv/bin/python analyses/BTCpredict/run_phase1_qa.py 2>&1 | tee -a "$LOG"
  QA_EXIT=${PIPESTATUS[0]}
else
  QA_EXIT=1
fi
echo "=== Done ingest=$INGEST_EXIT qa=$QA_EXIT $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LOG"
exit $(( INGEST_EXIT != 0 ? INGEST_EXIT : QA_EXIT ))
