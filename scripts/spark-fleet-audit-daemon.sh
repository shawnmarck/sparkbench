#!/usr/bin/env bash
# Run golden audit one model at a time (survives agent disconnect; logs per model).
set -euo pipefail
ROOT="${SPARK_ROOT:-/opt/spark}"
PY="${ROOT}/venv/bin/python3"
AUDIT="${ROOT}/scripts/golden-inventory-audit.py"
LOG="${ROOT}/logs/fleet-audit-daemon.log"
PIDFILE="${ROOT}/run/fleet-audit-daemon.pid"

MODELS=(
  "jackrong/qwopus3.6-27b-coder-compat"
  "empero-ai/qwythos-9b-claude-mythos-5-1m"
  "qwen/qwen-agentworld-35b-a3b"
)

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

if [[ "${1:-}" == "--status" ]]; then
  if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "fleet-audit-daemon running pid=$(cat "$PIDFILE")"
    tail -15 "$LOG"
  else
    echo "fleet-audit-daemon not running"
    tail -15 "$LOG" 2>/dev/null || true
  fi
  exit 0
fi

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "already running pid=$(cat "$PIDFILE")" >&2
  exit 1
fi

run_queue() {
  log "=== fleet audit daemon started ==="
  /usr/local/bin/spark inference down 2>/dev/null || true
  pkill -f 'llama-server.*--port 8081' 2>/dev/null || true
  sleep 2
  for inv in "${MODELS[@]}"; do
    log ">>> audit $inv"
    if ! "$PY" "$AUDIT" --only "$inv" --skip-shelf --resume >> "$LOG" 2>&1; then
      log "!!! audit failed for $inv (continuing)"
    fi
    /usr/local/bin/spark inference down 2>/dev/null || true
    sleep 3
  done
  log "=== golden audits done; starting fleet remediate phases ==="
  "$PY" "${ROOT}/scripts/spark-fleet-remediate.py" --only-phase ladder --skip-shelf >> "$LOG" 2>&1 || true
  "$PY" "${ROOT}/scripts/spark-fleet-remediate.py" --only-phase drafts --skip-shelf >> "$LOG" 2>&1 || true
  "$PY" "${ROOT}/scripts/spark-fleet-remediate.py" --only-phase shelf >> "$LOG" 2>&1 || true
  /usr/local/bin/spark models inventory >> "$LOG" 2>&1 || true
  log "=== fleet audit daemon finished ==="
  rm -f "$PIDFILE"
}

if [[ "${1:-}" == "--foreground" ]]; then
  echo $$ >"$PIDFILE"
  run_queue
else
  nohup bash "$0" --foreground >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  echo "Started fleet-audit-daemon pid=$(cat "$PIDFILE")"
  echo "Log: $LOG"
fi
