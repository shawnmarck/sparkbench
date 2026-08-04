#!/usr/bin/env bash
# OOM guard for ds4-server: poll MemAvailable; SIGTERM then SIGKILL if under threshold.
set -euo pipefail
ROOT="${SPARK_ROOT:-/opt/spark}"
PID_FILE="${ROOT}/run/ds4-server.pid"
LOG="${ROOT}/logs/ds4-oom-guard.log"
# Kill when available RAM stays below this for STREAK consecutive samples
MIN_AVAIL_MB="${DS4_OOM_MIN_AVAIL_MB:-4096}"
STREAK_NEED="${DS4_OOM_STREAK:-3}"
INTERVAL="${DS4_OOM_INTERVAL_S:-2}"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "$(date -Is) oom-guard start min_avail_mb=$MIN_AVAIL_MB streak=$STREAK_NEED interval=$INTERVAL"
streak=0
while true; do
  if [[ ! -f "$PID_FILE" ]]; then
    sleep "$INTERVAL"; continue
  fi
  pid=$(cat "$PID_FILE" 2>/dev/null || true)
  if [[ -z "${pid:-}" ]] || ! kill -0 "$pid" 2>/dev/null; then
    sleep "$INTERVAL"; continue
  fi
  avail_kb=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
  avail_mb=$((avail_kb / 1024))
  # also bail if swap free collapses hard
  swap_free_kb=$(awk '/SwapFree/ {print $2}' /proc/meminfo)
  if (( avail_mb < MIN_AVAIL_MB )); then
    streak=$((streak + 1))
    echo "$(date -Is) LOW_MEM avail_mb=$avail_mb streak=$streak/$STREAK_NEED pid=$pid swap_free_kb=$swap_free_kb"
    if (( streak >= STREAK_NEED )); then
      echo "$(date -Is) OOM_GUARD_KILL pid=$pid avail_mb=$avail_mb"
      kill -TERM "$pid" 2>/dev/null || true
      sleep 5
      kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
      # clear pid file so control plane knows
      rm -f "$PID_FILE" "${ROOT}/run/ds4.lock" /tmp/ds4.lock 2>/dev/null || true
      streak=0
    fi
  else
    streak=0
  fi
  sleep "$INTERVAL"
done
