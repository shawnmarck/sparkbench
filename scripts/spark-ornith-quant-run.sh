#!/usr/bin/env bash
# Wait for active Ornith profile, bench, then switch to next quant.
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
LOG="${ROOT}/logs/ornith-quant-compare.log"
FP8="deepreinforce-ai-ornith-1-0-35b-fp8-eugr"
NVFP4="deepreinforce-ai-ornith-1-0-35b-nvfp4-eugr"

log() { echo "[$(date -Is)] ornith-run: $*" | tee -a "$LOG"; }

wait_ready() {
  local prof=$1
  log "waiting for ready: ${prof}"
  for _ in $(seq 1 80); do
    if curl -sf "http://127.0.0.1:8767/api/inference/status" | grep -q "\"id\": \"${prof}\""; then
      if curl -sf "http://127.0.0.1:8767/api/inference/status" | grep -qE '"ready"[[:space:]]*:[[:space:]]*true'; then
        log "ready: ${prof}"
        return 0
      fi
    fi
    sleep 15
  done
  log "TIMEOUT waiting for ${prof}"
  return 1
}

run_bench() {
  local prof=$1
  log "bench-agent-v2 ${prof}"
  if BENCH_STANDARD=v2 /usr/local/bin/spark inference bench >>"$LOG" 2>&1; then
    log "OK bench ${prof}"
    /usr/local/bin/spark bench latest "$prof" 2>&1 | tee -a "$LOG"
    return 0
  fi
  log "FAIL bench ${prof}"
  return 1
}

switch_profile() {
  local prof=$1
  log "switch -> ${prof}"
  /usr/local/bin/spark inference down >>"$LOG" 2>&1 || true
  /usr/local/bin/spark recipe testing "$prof" >>"$LOG" 2>&1
  /usr/local/bin/spark inference up "$prof" >>"$LOG" 2>&1
}

log "=== ornith run helper started ==="
if wait_ready "$FP8"; then
  run_bench "$FP8" || true
fi
switch_profile "$NVFP4"
if wait_ready "$NVFP4"; then
  run_bench "$NVFP4" || true
fi
/usr/local/bin/spark inference down >>"$LOG" 2>&1 || true
log "=== summary ==="
for p in deepreinforce-ai-ornith-1-0-35b-llama "$FP8" "$NVFP4"; do
  /usr/local/bin/spark bench latest "$p" 2>&1 | tee -a "$LOG" || true
  echo "---" | tee -a "$LOG"
done
log "=== ornith run helper DONE ==="
