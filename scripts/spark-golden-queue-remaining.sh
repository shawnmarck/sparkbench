#!/usr/bin/env bash
# Queue remaining golden pipeline work after the current ctx-ladder batch finishes.
#
# Phases (sequential, GPU-bound):
#   1. Wait for spark-ctx-ladder-targeted.sh / spark-ctx-ladder.py
#   2. KV sweep --force for eligible profiles with stale/empty kv results
#   3. Golden workflow per model still missing bench_matrix.golden_cell (no fleet blast)
#   4. Ctx ladder --force where native > golden and rungs incomplete
#   5. KV sweep --force again for any still incomplete
#   6. Site publish + inventory rebuild + matrix summary
#
# Usage:
#   bash scripts/spark-golden-queue-remaining.sh          # foreground
#   setsid bash scripts/spark-golden-queue-remaining.sh </dev/null &>logs/golden-queue-remaining.log &
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
LOG="${ROOT}/logs/golden-queue-remaining.log"
PID_FILE="${ROOT}/run/golden-queue-remaining.pid"
PY="${ROOT}/venv/bin/python3"
WORKFLOW="${ROOT}/scripts/spark-golden-workflow.py"
KV="${ROOT}/scripts/spark-kv-sweep.py"
LADDER="${ROOT}/scripts/spark-ctx-ladder.py"
PUBLISH="${ROOT}/scripts/spark-golden-publish-site.py"
MATRIX="${ROOT}/scripts/spark-golden-matrix-status.py"

mkdir -p "${ROOT}/logs" "${ROOT}/run"
echo $$ >"$PID_FILE"

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

wait_for_gpu_jobs() {
  log "=== waiting for ctx-ladder / golden-workflow / kv-sweep / audit / bench ==="
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
  log "=== GPU job queue clear — starting remaining work ==="
}

run_kv_force() {
  local prof="$1"
  log ">>> kv sweep --force $prof"
  if "$PY" "$KV" "$prof" --force >>"$LOG" 2>&1; then
    log "OK kv $prof"
    return 0
  fi
  log "FAIL kv $prof"
  return 1
}

run_golden_model() {
  local path="$1"
  log ">>> golden workflow $path (all phases, no resume)"
  if "$PY" "$WORKFLOW" --only "$path" --skip-shelf --force >>"$LOG" 2>&1; then
    log "OK golden workflow $path"
    return 0
  fi
  log "FAIL golden workflow $path (exit $?)"
  return 1
}

run_ctx_ladder() {
  local prof="$1"
  log ">>> ctx ladder --force $prof"
  if "$PY" "$LADDER" "$prof" --force --continue-on-fail >>"$LOG" 2>&1; then
    log "OK ctx ladder $prof"
    return 0
  fi
  log "FAIL ctx ladder $prof"
  return 1
}

discover_work() {
  "$PY" - <<'PY'
import importlib.util
import yaml
from pathlib import Path

ROOT = Path("/opt/spark")
golden = yaml.safe_load((ROOT / "data/golden-recipes.yaml").read_text()) or {}
gmap = golden.get("golden") or {}
exclude = set(golden.get("leaderboard_exclude") or [])

spec = importlib.util.spec_from_file_location("gb", ROOT / "scripts/spark-golden-bench.py")
gb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gb)

spec2 = importlib.util.spec_from_file_location("gw", ROOT / "scripts/spark-golden-workflow.py")
gw = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(gw)

kv_retry: list[str] = []
golden_retry: list[str] = []
ladder_retry: list[str] = []

for inv, prof in sorted(gmap.items()):
    if inv in exclude:
        continue
    path = ROOT / "recipes" / f"{prof}.yaml"
    if not path.is_file():
        golden_retry.append(inv)
        continue
    recipe = yaml.safe_load(path.read_text()) or {}
    cell = ((recipe.get("context") or {}).get("bench_matrix") or {}).get("golden_cell") or {}
    has_golden = bool(cell.get("tok_s"))

    if not has_golden:
        golden_retry.append(inv)
        continue

    if gb.kv_sweep_eligible(recipe, inventory_path=inv):
        ks = (recipe.get("context") or {}).get("kv_sweep") or {}
        results = ks.get("results") if isinstance(ks, dict) else []
        ok = sum(1 for row in (results or []) if row.get("status") == "ok")
        if ok == 0:
            kv_retry.append(prof)

    if gw.needs_ctx_ladder(prof):
        ladder_retry.append(prof)

print("KV_RETRY", " ".join(kv_retry))
print("GOLDEN_RETRY", " ".join(golden_retry))
print("LADDER_RETRY", " ".join(ladder_retry))
PY
}

log "=== golden queue remaining started pid=$$ ==="

wait_for_gpu_jobs

mapfile -t lines < <(discover_work)
KV_LIST=()
GOLDEN_LIST=()
LADDER_LIST=()
for line in "${lines[@]}"; do
  key=${line%% *}
  rest=${line#* }
  case "$key" in
    KV_RETRY) read -ra KV_LIST <<<"$rest" ;;
    GOLDEN_RETRY) read -ra GOLDEN_LIST <<<"$rest" ;;
    LADDER_RETRY) read -ra LADDER_LIST <<<"$rest" ;;
  esac
done

log "plan: kv=${#KV_LIST[@]} golden=${#GOLDEN_LIST[@]} ladder=${#LADDER_LIST[@]}"
log "  kv: ${KV_LIST[*]:-none}"
log "  golden: ${GOLDEN_LIST[*]:-none}"
log "  ladder: ${LADDER_LIST[*]:-none}"

log "=== phase 2: kv sweep retry ==="
/usr/local/bin/spark inference down 2>/dev/null || true
for prof in "${KV_LIST[@]}"; do
  [[ -n "$prof" ]] || continue
  run_kv_force "$prof" || true
done

log "=== phase 3: golden retry (one model at a time) ==="
for path in "${GOLDEN_LIST[@]}"; do
  [[ -n "$path" ]] || continue
  run_golden_model "$path" || true
done

log "=== phase 4: ctx ladder retry ==="
/usr/local/bin/spark inference down 2>/dev/null || true
mapfile -t lines2 < <(discover_work)
LADDER_LIST=()
for line in "${lines2[@]}"; do
  [[ "$line" == LADDER_RETRY* ]] || continue
  read -ra LADDER_LIST <<<"${line#* }"
done
for prof in "${LADDER_LIST[@]}"; do
  [[ -n "$prof" ]] || continue
  run_ctx_ladder "$prof" || true
done

log "=== phase 5: kv sweep final pass ==="
mapfile -t lines3 < <(discover_work)
KV_LIST=()
for line in "${lines3[@]}"; do
  [[ "$line" == KV_RETRY* ]] || continue
  read -ra KV_LIST <<<"${line#* }"
done
/usr/local/bin/spark inference down 2>/dev/null || true
for prof in "${KV_LIST[@]}"; do
  [[ -n "$prof" ]] || continue
  run_kv_force "$prof" || true
done

log "=== phase 6: site publish + inventory ==="
"$PY" "$PUBLISH" --all >>"$LOG" 2>&1 || log "WARN site publish had errors"
/usr/local/bin/spark models inventory >>"$LOG" 2>&1 || true

# Optional extra jobs appended while this queue runs (see run/golden-queue-pending.txt)
PENDING="${ROOT}/run/golden-queue-pending.txt"
if [[ -f "$PENDING" ]]; then
  log "=== phase 7: pending extras from $PENDING ==="
  while IFS= read -r extra || [[ -n "${extra:-}" ]]; do
    [[ -z "${extra:-}" || "$extra" =~ ^# ]] && continue
    log ">>> pending golden workflow $extra"
    run_golden_model "$extra" || true
  done <"$PENDING"
fi

log "=== final matrix status ==="
"$PY" "$MATRIX" --wide >>"$LOG" 2>&1 || true
"$PY" "$MATRIX" >>"$LOG" 2>&1 || true

log "=== golden queue remaining DONE ==="
rm -f "$PID_FILE"
