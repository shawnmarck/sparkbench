#!/usr/bin/env bash
# Wait for FP8/NVFP4 downloads, then run Ornith A/B benches.
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
LOG="${ROOT}/logs/ornith-quant-compare.log"
PID_FILE="${ROOT}/run/ornith-quant-compare.pid"
MODEL_ROOT="/models/deepreinforce-ai/ornith-1.0-35b"
COMPARE="${ROOT}/scripts/spark-ornith-quant-compare.sh"

mkdir -p "${ROOT}/logs" "${ROOT}/run"
echo $$ >"$PID_FILE"

log() { echo "[$(date -Is)] ornith-queue: $*" | tee -a "$LOG"; }

wait_dir() {
  local dir=$1 min_gb=$2 label=$3
  log "waiting for ${label} (target ~${min_gb}GB in ${dir})"
  while true; do
    if docker ps --format '{{.Command}}' 2>/dev/null | grep -q "Ornith-1.0-35B"; then
      sleep 60
      continue
    fi
    if [[ -f "${dir}/config.json" ]] && compgen -G "${dir}/*.safetensors" >/dev/null 2>&1; then
      local gb s1 s2
      gb=$(du -sb "$dir" 2>/dev/null | awk '{printf "%.1f", $1/1e9}')
      if awk -v g="$gb" -v m="$min_gb" 'BEGIN{exit !(g>=m*0.95)}'; then
        s1=$(du -sb "$dir" | awk '{print $1}')
        sleep 90
        s2=$(du -sb "$dir" | awk '{print $1}')
        if [[ "$s1" == "$s2" ]]; then
          log "${label} ready ${gb}GB"
          return 0
        fi
      fi
    fi
    sleep 45
  done
}

log "=== ornith quant compare queue pid=$$ ==="
wait_dir "${MODEL_ROOT}/fp8" 35 "FP8"
wait_dir "${MODEL_ROOT}/nvfp4" 22 "NVFP4"
"${COMPARE}" prepare >>"$LOG" 2>&1
"${COMPARE}" bench >>"$LOG" 2>&1
log "=== ornith quant compare queue DONE ==="
rm -f "$PID_FILE"
