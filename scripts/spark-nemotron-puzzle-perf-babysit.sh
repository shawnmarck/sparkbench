#!/usr/bin/env bash
# Nemotron Puzzle: smoke load → perf_sweep @ safe golden ctx → leave optimal up.
# Never auto-loads at 262k — smoke preset first, production only via ctx_ladder proof.
set -euo pipefail
ROOT=/opt/spark
LOG="$ROOT/logs/nemotron-puzzle-perf-babysit.log"
PROFILE=""
INVENTORY=nvidia/nvidia-nemotron-labs-3-puzzle-75b-a9b
DEST="/models/${INVENTORY}/hf"
JOB_ID=""
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-2400}"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }

download_ready() {
  python3 <<PY
from pathlib import Path
dest = Path("$DEST")
need = [
    "config.json",
    "mtp.safetensors",
    "model.safetensors.index.json",
    "model-00001-of-00005.safetensors",
    "model-00002-of-00005.safetensors",
    "model-00003-of-00005.safetensors",
    "model-00004-of-00005.safetensors",
    "model-00005-of-00005.safetensors",
]
missing = [n for n in need if not (dest / n).is_file()]
if missing:
    raise SystemExit(1)
print("ok")
PY
}

resolve_profile() {
  PROFILE=$(python3 <<PY
import yaml
from pathlib import Path
inv = "$INVENTORY"
for base in (Path("$ROOT/recipes/drafts"), Path("$ROOT/recipes")):
    if not base.is_dir():
        continue
    for p in sorted(base.glob("*.yaml")):
        d = yaml.safe_load(p.read_text()) or {}
        if d.get("inventory_path") == inv and d.get("engine") == "eugr":
            print(d.get("id", ""))
            raise SystemExit(0)
raise SystemExit(1)
PY
)
}

wait_vllm_ready() {
  local timeout="$1"
  local t0
  t0=$(date +%s)
  while true; do
    if curl -sf --max-time 8 http://127.0.0.1:8000/v1/models 2>/dev/null \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("data")' 2>/dev/null; then
      log "vLLM ready"
      return 0
    fi
    if (( $(date +%s) - t0 > timeout )); then
      log "TIMEOUT waiting for vLLM (${timeout}s)"
      docker logs vllm_node 2>&1 | tail -50 | tee -a "$LOG" || true
      return 1
    fi
    sleep 20
  done
}

log "pause benchmaster (no 262k auto-load)"
curl -sf -X POST http://127.0.0.1/api/benchmaster/control \
  -H 'Content-Type: application/json' -d '{"action":"pause"}' >>"$LOG" 2>&1 || true

if ! download_ready 2>/dev/null; then
  log "waiting for download at $DEST"
  while ! download_ready 2>/dev/null; do
    du -sh "$DEST" 2>/dev/null | tee -a "$LOG" || true
    sleep 60
  done
fi
log "download complete"

log "inventory rebuild + scaffold"
"$ROOT/venv/bin/python3" - <<PY >>"$LOG" 2>&1
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("inf", Path("$ROOT/scripts/spark-inference.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
recipe = mod.scaffold_auto("$INVENTORY")
print("scaffolded", recipe.get("id"))
PY

resolve_profile
log "profile=$PROFILE"

log "smoke load (--preset smoke, 32k)"
spark inference down >>"$LOG" 2>&1 || true
spark engine eugr down >>"$LOG" 2>&1 || true
spark inference up "$PROFILE" --preset smoke >>"$LOG" 2>&1

if ! wait_vllm_ready "$SMOKE_TIMEOUT"; then
  log "SMOKE FAILED — inspect: docker logs vllm_node"
  exit 1
fi
log "smoke PASSED"

log "free GPU for perf_sweep (bench uses golden @ 64k, not 262k)"
spark inference down >>"$LOG" 2>&1 || true
spark engine eugr down >>"$LOG" 2>&1 || true

JOB_ID=$(spark benchmaster add "$PROFILE" --type perf_sweep --front 2>&1 | python3 -c "import json,sys; print(json.load(sys.stdin)['item']['id'])")
log "queued perf_sweep $JOB_ID"
curl -sf -X POST http://127.0.0.1/api/benchmaster/control \
  -H 'Content-Type: application/json' -d '{"action":"resume"}' >>"$LOG" 2>&1 || true

last_msg=""
while true; do
  read -r state msg <<<$(python3 -c "
import yaml
for it in yaml.safe_load(open('$ROOT/run/benchmaster/queue.yaml'))['items']:
    if it.get('id')=='$JOB_ID':
        p=it.get('progress') or {}
        print(it.get('state',''), p.get('message',''))
        break
" 2>/dev/null)
  if [[ -n "$msg" && "$msg" != "$last_msg" ]]; then
    log "phase: $msg"
    last_msg="$msg"
  fi
  if [[ "$state" == "done" ]]; then
    log "perf_sweep PASSED — optimize + best tested preset up"
    "$ROOT/venv/bin/python3" "$ROOT/scripts/spark-benchmaster-optimize-recipe.py" "$PROFILE" >>"$LOG" 2>&1
    if spark inference up "$PROFILE" --preset optimal >>"$LOG" 2>&1; then
      log "ready: http://sparky:9000/v1 (preset=optimal)"
    else
      spark inference up "$PROFILE" --preset golden >>"$LOG" 2>&1
      log "ready: http://sparky:9000/v1 (preset=golden fallback)"
    fi
    curl -sf -X POST http://127.0.0.1/api/benchmaster/control \
      -H 'Content-Type: application/json' -d '{"action":"pause"}' >>"$LOG" 2>&1 || true
    exit 0
  fi
  if [[ "$state" == "failed" ]]; then
    log "FAILED — see $ROOT/run/benchmaster/runs/$JOB_ID/summary.json"
    exit 1
  fi
  sleep 30
done
