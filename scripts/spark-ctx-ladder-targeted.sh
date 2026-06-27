#!/usr/bin/env bash
# Targeted ctx ladders for qwythos (ladder down), qwopus (128k), mellum2 (64k/128k refresh).
set -euo pipefail
LOG=/opt/spark/logs/ctx-ladder-targeted.log
PY=/opt/spark/venv/bin/python3
LADDER=/opt/spark/scripts/spark-ctx-ladder.py

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

log "=== targeted ctx ladder batch ==="
/usr/local/bin/spark inference down 2>/dev/null || true

run() {
  local prof="$1"
  shift
  log ">>> $prof $*"
  if "$PY" "$LADDER" "$prof" --force --continue-on-fail "$@" >>"$LOG" 2>&1; then
    log "OK $prof"
  else
    log "FAIL $prof"
  fi
}

run empero-ai-qwythos-9b-claude-mythos-5-1m-eugr
run jackrong-qwopus3-6-27b-coder-compat-llama
# mellum2: 64k/128k ladder already ok — presets come from ctx_ladder via API

log "=== targeted ctx ladder batch done ==="
/usr/local/bin/spark models inventory >>"$LOG" 2>&1 || true
