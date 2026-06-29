#!/usr/bin/env bash
# Finish the 10 golden models still missing bench_matrix / KV / ctx ladder.
#
# Usage:
#   bash scripts/spark-golden-queue-incomplete.sh
#   setsid bash scripts/spark-golden-queue-incomplete.sh </dev/null &>logs/golden-queue-incomplete.log &
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
LOG="${ROOT}/logs/golden-queue-incomplete.log"
PID_FILE="${ROOT}/run/golden-queue-incomplete.pid"
PY="${ROOT}/venv/bin/python3"
WORKFLOW="${ROOT}/scripts/spark-golden-workflow.py"
KV="${ROOT}/scripts/spark-kv-sweep.py"
LADDER="${ROOT}/scripts/spark-ctx-ladder.py"
PUBLISH="${ROOT}/scripts/spark-golden-publish-site.py"
MATRIX="${ROOT}/scripts/spark-golden-matrix-status.py"

# Inventory paths still incomplete after golden-queue-remaining (2026-06-28).
INCOMPLETE=(
  nvidia/qwen3-30b-a3b
  nvidia/qwen3.6-35b-a3b
  qwen/qwen-agentworld-35b-a3b
  qwen/qwen3-coder-next
  qwen/qwen3.6-27b
  rdtand/qwen3.6-27b
  saricles/qwen3-coder-next
  stepfun-ai/step-3.7-flash
  unsloth/qwen3.6-27b
  unsloth/qwen3.6-35b-a3b
)

mkdir -p "${ROOT}/logs" "${ROOT}/run"
echo $$ >"$PID_FILE"

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

wait_for_pipeline() {
  log "=== waiting for pipeline jobs (ctx-ladder / golden-workflow / kv-sweep / bench) ==="
  while true; do
    local busy=0
    pgrep -f '/opt/spark/scripts/spark-ctx-ladder-targeted\.sh' >/dev/null 2>&1 && busy=1
    pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/spark-ctx-ladder\.py' >/dev/null 2>&1 && busy=1
    pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/spark-golden-workflow\.py' >/dev/null 2>&1 && busy=1
    pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/spark-kv-sweep\.py' >/dev/null 2>&1 && busy=1
    pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/golden-inventory-audit\.py' >/dev/null 2>&1 && busy=1
    pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/spark-inference\.py bench' >/dev/null 2>&1 && busy=1
    [[ "$busy" -eq 0 ]] && break
    sleep 30
  done
  log "=== pipeline clear ==="
}

gpu_down() {
  log "gpu_down: stopping managed inference + orphan llama-server"
  /usr/local/bin/spark inference down 2>/dev/null || true
  /opt/spark/scripts/spark-llama down 2>/dev/null || true
  sleep 3
  if pgrep -f '/opt/spark/bin/llama-server' >/dev/null 2>&1; then
    log "WARN: stray llama-server still running after gpu_down"
    pgrep -af '/opt/spark/bin/llama-server' >>"$LOG" 2>&1 || true
  fi
}

run_kv_force() {
  local prof="$1"
  log ">>> kv sweep --force $prof"
  gpu_down
  if "$PY" "$KV" "$prof" --force >>"$LOG" 2>&1; then
    log "OK kv $prof"
    return 0
  fi
  log "FAIL kv $prof (exit $?)"
  return 1
}

run_golden_model() {
  local path="$1"
  log ">>> golden workflow $path (all phases)"
  gpu_down
  local rc=0
  "$PY" "$WORKFLOW" --only "$path" --skip-shelf --force >>"$LOG" 2>&1 || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    log "OK golden workflow $path"
    return 0
  fi
  log "FAIL golden workflow $path (exit $rc)"
  return 1
}

run_ctx_ladder() {
  local prof="$1"
  log ">>> ctx ladder --force $prof"
  gpu_down
  if "$PY" "$LADDER" "$prof" --force --continue-on-fail >>"$LOG" 2>&1; then
    log "OK ctx ladder $prof"
    return 0
  fi
  log "FAIL ctx ladder $prof (exit $?)"
  return 1
}

profile_for() {
  local path="$1"
  "$PY" - "$path" <<'PY'
import sys, yaml
from pathlib import Path
path = sys.argv[1]
golden = yaml.safe_load((Path("/opt/spark") / "data/golden-recipes.yaml").read_text()) or {}
print((golden.get("golden") or {}).get(path, ""))
PY
}

needs_golden_bench() {
  local path="$1" prof
  prof="$(profile_for "$path")"
  [[ -n "$prof" ]] || return 0
  "$PY" - "$prof" <<'PY'
import sys, yaml
from pathlib import Path
prof = sys.argv[1]
recipe = yaml.safe_load((Path("/opt/spark") / "recipes" / f"{prof}.yaml").read_text()) or {}
cell = ((recipe.get("context") or {}).get("bench_matrix") or {}).get("golden_cell") or {}
raise SystemExit(0 if cell.get("tok_s") else 1)
PY
}

needs_kv() {
  local path="$1" prof
  prof="$(profile_for "$path")"
  [[ -n "$prof" ]] || return 1
  "$PY" - "$path" "$prof" <<'PY'
import sys, importlib.util, yaml
from pathlib import Path
path, prof = sys.argv[1], sys.argv[2]
ROOT = Path("/opt/spark")
recipe = yaml.safe_load((ROOT / "recipes" / f"{prof}.yaml").read_text()) or {}
spec = importlib.util.spec_from_file_location("gb", ROOT / "scripts/spark-golden-bench.py")
gb = importlib.util.module_from_spec(spec); spec.loader.exec_module(gb)
if not gb.kv_sweep_eligible(recipe, inventory_path=path):
    raise SystemExit(1)
ks = (recipe.get("context") or {}).get("kv_sweep") or {}
results = ks.get("results") if isinstance(ks, dict) else []
ok = sum(1 for row in (results or []) if row.get("status") == "ok")
raise SystemExit(0 if ok == 0 else 1)
PY
}

needs_ladder() {
  local prof="$1"
  "$PY" - "$prof" <<'PY'
import sys, importlib.util
from pathlib import Path
prof = sys.argv[1]
spec = importlib.util.spec_from_file_location("gw", Path("/opt/spark") / "scripts/spark-golden-workflow.py")
gw = importlib.util.module_from_spec(spec); spec.loader.exec_module(gw)
raise SystemExit(0 if gw.needs_ctx_ladder(prof) else 1)
PY
}

log "=== golden queue incomplete started pid=$$ (${#INCOMPLETE[@]} targets) ==="
wait_for_pipeline
gpu_down

log "=== phase 1: golden workflow (models missing bench_matrix golden_cell) ==="
for path in "${INCOMPLETE[@]}"; do
  if needs_golden_bench "$path"; then
    log "skip golden $path (already has golden_cell)"
    continue
  fi
  run_golden_model "$path" || true
done

log "=== phase 2: kv sweep ==="
for path in "${INCOMPLETE[@]}"; do
  prof="$(profile_for "$path")"
  [[ -n "$prof" ]] || continue
  if needs_kv "$path"; then
    run_kv_force "$prof" || true
  else
    log "skip kv $path (complete or not eligible)"
  fi
done

log "=== phase 3: ctx ladder ==="
for path in "${INCOMPLETE[@]}"; do
  prof="$(profile_for "$path")"
  [[ -n "$prof" ]] || continue
  if needs_ladder "$prof"; then
    run_ctx_ladder "$prof" || true
  else
    log "skip ladder $prof"
  fi
done

log "=== phase 4: kv sweep final pass ==="
for path in "${INCOMPLETE[@]}"; do
  prof="$(profile_for "$path")"
  [[ -n "$prof" ]] || continue
  if needs_kv "$path"; then
    run_kv_force "$prof" || true
  fi
done

log "=== phase 5: site publish + inventory ==="
"$PY" "$PUBLISH" --all >>"$LOG" 2>&1 || log "WARN site publish had errors"
/usr/local/bin/spark models inventory >>"$LOG" 2>&1 || true

log "=== final matrix status ==="
"$PY" "$MATRIX" --wide >>"$LOG" 2>&1 || true
"$PY" "$MATRIX" >>"$LOG" 2>&1 || true

log "=== golden queue incomplete DONE ==="
rm -f "$PID_FILE"
