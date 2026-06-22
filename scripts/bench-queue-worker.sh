#!/usr/bin/env bash
# Dynamic benchmark queue — discovers unbenched models after each download batch.
# Supports benchmark history notes + optional refire of pre-history import runs.
set -euo pipefail
AUDIT=/opt/spark/benchmark-audit.log
LOG=/opt/spark/logs/bench-queue-worker.log
DISCOVER=/opt/spark/run/bench-queue-discover.py
GGUF_PICK=/opt/spark/run/gguf_pick.py
READY_WAIT_SECS=2400
BENCH_TIMEOUT=900
HEARTBEAT_SECS=300
LOCK=/opt/spark/run/bench-queue-worker.lock
# Re-bench models whose only history entry is migrated import (pre-feature runs).
BENCH_REFIRE_IMPORTED="${BENCH_REFIRE_IMPORTED:-1}"

emit() {
  local event="$1" detail="$2"
  echo "AGENT_BENCH_EVENT {\"event\":\"$event\",\"detail\":$detail,\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" | tee -a "$LOG"
}

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$AUDIT" "$LOG"; }

model_downloading() {
  local inv="$1"
  python3 -c "
import subprocess, sys
inv = sys.argv[1]
needles = (f'/models/{inv}', inv)
try:
    out = subprocess.check_output(['pgrep', '-af', 'download'], text=True, stderr=subprocess.DEVNULL)
except subprocess.CalledProcessError:
    sys.exit(1)
for line in out.splitlines():
    if 'bench-queue' in line: continue
    if not any(n in line for n in needles): continue
    if 'hf download' in line or 'spark-download' in line:
        sys.exit(0)
sys.exit(1)
" "$inv" 2>/dev/null
}

llama_load_failed() {
  [[ -f /opt/spark/logs/llama-server.log ]] || return 1
  tail -30 /opt/spark/logs/llama-server.log 2>/dev/null | grep -qE \
    'exiting due to model loading error|unknown model architecture|failed to load model'
}

eugr_container_gone() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qx vllm_node && return 1
  docker ps -a --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -q vllm_node && return 0
  # never started or already removed
  spark engine eugr status 2>/dev/null | grep -q 'not ready' && return 0
  return 1
}

eugr_load_failed() {
  docker logs vllm_node 2>&1 | tail -40 | grep -qE \
    'RuntimeError|CUDA out of memory|Engine core initialization failed|failed to load model|Traceback'
}

wait_ready() {
  local port="$1" engine="${2:-eugr}" model_path="${3:-}" i=0 max_wait="$READY_WAIT_SECS"
  [[ "$engine" == "eugr-dflash" ]] && engine="eugr"
  if [[ "$engine" == "llamacpp" && -n "$model_path" && -f "$GGUF_PICK" ]]; then
    max_wait=$(python3 "$GGUF_PICK" ready_secs "$model_path" 2>/dev/null || echo "$READY_WAIT_SECS")
    log "llamacpp ready window ${max_wait}s for $(basename "$model_path")"
  fi
  while (( i < max_wait / 15 )); do
    curl -sf "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1 && return 0
    if [[ "$engine" == "llamacpp" ]]; then
      if ! spark engine llama status 2>/dev/null | grep -q '^Running'; then
        if llama_load_failed; then
          log "FAIL llama-server died during load (check llama-server.log)"
          return 1
        fi
      fi
    elif [[ "$engine" == "ds4" ]]; then
      if ! spark engine ds4 status 2>/dev/null | grep -q "^Running"; then
        if [[ -f /opt/spark/logs/ds4-server.log ]] && tail -30 /opt/spark/logs/ds4-server.log 2>/dev/null | grep -qiE "error|failed|traceback"; then
          log "FAIL ds4-server died during load (check ds4-server.log)"
          return 1
        fi
      fi
    elif [[ "$engine" == "eugr" ]]; then
      if eugr_container_gone; then
        log "FAIL vllm_node container exited during load"
        docker logs vllm_node 2>&1 | tail -15 | tee -a "$LOG" || true
        return 1
      fi
      if eugr_load_failed; then
        log "FAIL vLLM error during load (check docker logs vllm_node)"
        docker logs vllm_node 2>&1 | tail -15 | tee -a "$LOG" || true
        return 1
      fi
    fi
    sleep 15; ((++i)) || true
  done
  return 1
}

recipe_gguf_path() {
  local profile="$1"
  local draft="/opt/spark/recipes/drafts/${profile}.yaml"
  local prod="/opt/spark/recipes/${profile}.yaml"
  local f=""
  if [[ -f "$draft" ]]; then f="$draft"; elif [[ -f "$prod" ]]; then f="$prod"; else return 1; fi
  python3 -c "
import yaml, sys
from pathlib import Path
data = yaml.safe_load(Path(sys.argv[1]).read_text()) or {}
print(data.get('model') or '')
" "$f" 2>/dev/null
}

fix_recipe_gguf_if_needed() {
  local inv="$1" engine="$2" profile="$3"
  [[ "$engine" == "llamacpp" ]] || return 0
  [[ -f "$GGUF_PICK" ]] || return 0
  local model_path reason
  model_path=$(recipe_gguf_path "$profile" || true)
  [[ -n "${model_path:-}" ]] || return 0
  reason=$(python3 "$GGUF_PICK" check "$inv" "$model_path" 2>/dev/null || true)
  [[ -n "${reason:-}" ]] || return 0
  log "FIX $inv — $reason"
  emit fix "$(python3 -c "import json; print(json.dumps({'inventory':'$inv','reason':'''${reason//\'/}'''}))")"
  rm -f "/opt/spark/recipes/drafts/${profile}.yaml"
  spark recipe scaffold "$inv" llamacpp 2>&1 | tee -a "$LOG" || {
    log "FAIL rescaffold $inv after gguf fix"; return 1
  }
  return 0
}

find_profile() {
  local inv="$1" engine="$2"
  local spec_grep=""
  if [[ "$engine" == "eugr-dflash" ]]; then
    spec_grep="speculative:"
    engine="eugr"
  fi
  spark recipe list 2>/dev/null | while read -r pid _; do
    [[ -f "/opt/spark/recipes/drafts/${pid}.yaml" ]] || continue
    grep -q "inventory_path: ${inv}" "/opt/spark/recipes/drafts/${pid}.yaml" 2>/dev/null || continue
    grep -q "engine: ${engine}" "/opt/spark/recipes/drafts/${pid}.yaml" 2>/dev/null || continue
    if [[ -n "$spec_grep" ]]; then
      grep -q "$spec_grep" "/opt/spark/recipes/drafts/${pid}.yaml" 2>/dev/null || continue
    elif grep -q "speculative:" "/opt/spark/recipes/drafts/${pid}.yaml" 2>/dev/null; then
      continue
    fi
    echo "$pid" && break
  done
  spark recipe list 2>/dev/null | while read -r pid _; do
    [[ -f "/opt/spark/recipes/${pid}.yaml" ]] || continue
    grep -q "inventory_path: ${inv}" "/opt/spark/recipes/${pid}.yaml" 2>/dev/null || continue
    grep -q "engine: ${engine}" "/opt/spark/recipes/${pid}.yaml" 2>/dev/null || continue
    if [[ -n "$spec_grep" ]]; then
      grep -q "$spec_grep" "/opt/spark/recipes/${pid}.yaml" 2>/dev/null || continue
    elif grep -q "speculative:" "/opt/spark/recipes/${pid}.yaml" 2>/dev/null; then
      continue
    fi
    echo "$pid" && break
  done
}

annotate_bench_run() {
  local profile="$1" inv="$2" engine="$3" refire="${4:-0}"
  local run_id note
  run_id=$(spark inference bench latest "$profile" --json 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('latest', {}).get('latest_run_id', '') or '')
except Exception:
    print('')
" || true)
  [[ -n "$run_id" ]] || return 0
  if [[ "$refire" == "1" ]]; then
    note="agent-queue refire $(date -u +%Y-%m-%d); inventory=$inv; engine=$engine; replaces import-only history"
  elif [[ "$engine" == "eugr-dflash" ]]; then
    note="agent-queue $(date -u +%Y-%m-%d); inventory=$inv; engine=$engine; DFlash sidecar speculative decode"
  else
    note="agent-queue $(date -u +%Y-%m-%d); inventory=$inv; engine=$engine"
  fi
  spark inference bench note "$profile" "$run_id" "$note" 2>&1 | tee -a "$LOG" || true
  log "NOTE $profile/$run_id: $note"
}

bench_one() {
  local inv="$1" engine="$2" refire="${3:-0}"
  local profile bench_out

  if [[ "$refire" == "1" ]]; then
    log "REFIRE: $inv ($engine) — import-only history"
  else
    log "START: $inv ($engine)"
  fi
  if model_downloading "$inv"; then
    log "SKIP $inv — download in progress"
    emit skip "\"$inv downloading\""
    return 0
  fi

  profile=$(find_profile "$inv" "$engine" | head -1 || true)
  if [[ -z "${profile:-}" ]]; then
    if [[ "$engine" == "eugr-dflash" ]]; then
      spark recipe scaffold-dflash "$inv" 2>&1 | tee -a "$LOG" || {
        log "FAIL scaffold-dflash $inv"; emit fail "\"scaffold-dflash $inv\""; return 1
      }
    else
      spark recipe scaffold "$inv" "$engine" 2>&1 | tee -a "$LOG" || {
        log "FAIL scaffold $inv"; emit fail "\"scaffold $inv\""; return 1
      }
    fi
    profile=$(find_profile "$inv" "$engine" | head -1 || spark recipe list 2>/dev/null | awk 'NR==2{print $1}')
  fi

  if fix_recipe_gguf_if_needed "$inv" "$engine" "$profile"; then
    profile=$(find_profile "$inv" "$engine" | head -1 || true)
  fi
  [[ -n "${profile:-}" ]] || { log "FAIL no profile for $inv"; emit fail "\"no profile $inv\""; return 1; }

  local model_path=""
  if [[ "$engine" == "llamacpp" ]]; then
    model_path=$(recipe_gguf_path "$profile" || true)
  fi

  if [[ "$engine" == "eugr-dflash" ]] && grep -q "blocked: true" "/opt/spark/recipes/drafts/${profile}.yaml" 2>/dev/null; then
    reason=$(grep -A1 "blocked_reason:" "/opt/spark/recipes/drafts/${profile}.yaml" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//')
    log "SKIP $inv DFlash blocked: ${reason:-incompatible target}"
    emit skip "\"dflash blocked $inv\""
    return 0
  fi

  spark recipe testing "$profile" 2>&1 | tee -a "$LOG" || true
  spark inference down 2>&1 | tee -a "$LOG" || true
  spark inference up "$profile" 2>&1 | tee -a "$LOG" || {
    log "FAIL up $profile"; emit fail "\"up $profile\""; return 1
  }

  local port=8000
  if [[ "$engine" == "llamacpp" ]]; then
    port=8081
  fi
  local ready_engine="$engine"
  [[ "$ready_engine" == "eugr-dflash" ]] && ready_engine="eugr"
  [[ "$ready_engine" == "ds4" ]] && ready_engine="ds4"
  if ! wait_ready "$port" "$ready_engine" "$model_path"; then
    log "FAIL ready timeout $profile"
    emit fail "\"ready timeout $profile\""
    spark inference down 2>&1 || true
    return 1
  fi

  nvidia-smi --query-gpu=utilization.gpu,power.draw --format=csv,noheader,nounits 2>/dev/null | head -1 | while read -r u p; do
    log "GPU pre-bench: util=${u}% power=${p}W ($profile)"
  done

  if bench_out=$(timeout "$BENCH_TIMEOUT" spark inference bench 2>&1); then
    log "DONE $inv: $bench_out"
    annotate_bench_run "$profile" "$inv" "$engine" "$refire"
    spark recipe works "$profile" 2>&1 | tee -a "$LOG" || true
    spark inference bench history "$profile" --limit 3 2>&1 | tee -a "$LOG" || true
    spark models inventory >/dev/null 2>&1 || true
    emit done "$(python3 -c "import json; print(json.dumps({'inventory':'$inv','engine':'$engine','refire':$refire,'output':'''${bench_out//\'/}'''}))")"
  else
    log "FAIL bench $profile: $bench_out"
    emit fail "\"bench $profile\""
  fi
  spark inference down 2>&1 | tee -a "$LOG" || true
}

run_pass() {
  local mode="$1" refire_flag="${2:-0}"
  local n=0 line inv eng
  spark models inventory >/dev/null 2>&1 || true
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    inv="${line%% *}"; eng="${line##* }"
    bench_one "$inv" "$eng" "$refire_flag" || true
    ((++n)) || true
  done < <(python3 "$DISCOVER" --mode "$mode")
  echo "$n"
}

queue_count() {
  python3 "$DISCOVER" --mode unbenched | wc -l
}

refire_count() {
  python3 "$DISCOVER" --mode refire-import | wc -l
}

mkdir -p /opt/spark/logs /opt/spark/run
exec 9>"$LOCK"
flock -n 9 || { log "another worker holds lock; exiting"; exit 0; }

log "=== bench-queue-worker started (dynamic discover + history notes) ==="
emit started "\"dynamic discover; refire_import=$BENCH_REFIRE_IMPORTED\""

while true; do
  count=$(run_pass unbenched 0)
  remaining=$(queue_count)
  refire_pending=0
  if (( remaining == 0 )) && [[ "$BENCH_REFIRE_IMPORTED" == "1" ]]; then
    refire_pending=$(refire_count)
    if (( refire_pending > 0 )); then
      log "=== unbenched queue empty; refiring $refire_pending import-only profiles ==="
      run_pass refire-import 1 >/dev/null || true
      refire_pending=$(refire_count)
    fi
  fi
  if (( remaining == 0 )) && (( refire_pending == 0 )); then
    log "=== queue empty — sleeping ${HEARTBEAT_SECS}s for new downloads ==="
    emit heartbeat "\"queue empty, watching for new models\""
  else
    log "=== pass done ($count jobs); $remaining unbenched, $refire_pending refire pending — retry in ${HEARTBEAT_SECS}s ==="
    emit heartbeat "\"$remaining unbenched, $refire_pending refire pending\""
  fi
  sleep "$HEARTBEAT_SECS"
done
