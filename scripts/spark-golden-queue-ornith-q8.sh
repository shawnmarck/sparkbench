#!/usr/bin/env bash
# Wait for Ornith Q8_0 GGUF download, switch recipe, then run golden workflow
# after the main golden-queue-remaining batch finishes.
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
LOG="${ROOT}/logs/golden-queue-ornith-q8.log"
PID_FILE="${ROOT}/run/golden-queue-ornith-q8.pid"
MAIN_QUEUE_PID="${ROOT}/run/golden-queue-remaining.pid"
PY="${ROOT}/venv/bin/python3"
WORKFLOW="${ROOT}/scripts/spark-golden-workflow.py"
PUBLISH="${ROOT}/scripts/spark-golden-publish-site.py"

INV="deepreinforce-ai/ornith-1.0-35b"
PROF="deepreinforce-ai-ornith-1-0-35b-llama"
GGUF="/models/deepreinforce-ai/ornith-1.0-35b/hf/ornith-1.0-35b-Q8_0.gguf"
RECIPE="${ROOT}/recipes/${PROF}.yaml"

mkdir -p "${ROOT}/logs" "${ROOT}/run"
echo $$ >"$PID_FILE"

log() { echo "[$(date -Is)] ornith-q8: $*" | tee -a "$LOG"; }

wait_for_download() {
  log "waiting for $GGUF"
  while [[ ! -f "$GGUF" ]]; do
    if pgrep -f 'hf download.*Ornith-1.0-35B-GGUF' >/dev/null 2>&1; then
      sleep 45
      continue
    fi
    sleep 30
  done
  log "file appeared — waiting for download process to exit"
  while pgrep -f 'hf download.*Ornith-1.0-35B-GGUF' >/dev/null 2>&1; do
    sleep 30
  done
  log "waiting for stable file size"
  local s1 s2
  while true; do
    s1=$(stat -c%s "$GGUF" 2>/dev/null || echo 0)
    sleep 90
    s2=$(stat -c%s "$GGUF" 2>/dev/null || echo 0)
    if pgrep -f 'hf download.*ornith' >/dev/null 2>&1; then
      continue
    fi
    if [[ "$s1" == "$s2" && "$s2" -gt 5000000000 ]]; then
      log "download stable size=$(( s2 / 1024 / 1024 / 1024 ))GiB"
      break
    fi
    log "still growing ${s1} -> ${s2}"
  done
}

update_recipe_q8() {
  log "pointing recipe at Q8_0 GGUF"
  "$PY" - <<'PY'
import yaml
from pathlib import Path

recipe_path = Path("/opt/spark/recipes/deepreinforce-ai-ornith-1-0-35b-llama.yaml")
gguf = "/models/deepreinforce-ai/ornith-1.0-35b/hf/ornith-1.0-35b-Q8_0.gguf"
recipe = yaml.safe_load(recipe_path.read_text()) or {}
recipe["model"] = gguf
notes = str(recipe.get("notes") or "")
if "Q8_0" not in notes:
    recipe["notes"] = (notes.rstrip() + "\nSwitched to Q8_0 GGUF for golden re-bench.\n").strip()
recipe_path.write_text(yaml.safe_dump(recipe, sort_keys=False, default_flow_style=False))
print("updated", recipe_path)
PY
  /usr/local/bin/spark models inventory >>"$LOG" 2>&1 || true
}

wait_for_main_queue() {
  if [[ -f "$MAIN_QUEUE_PID" ]]; then
    local mpid
    mpid=$(cat "$MAIN_QUEUE_PID")
    if [[ -n "$mpid" ]] && kill -0 "$mpid" 2>/dev/null; then
      log "waiting for main queue pid=$mpid"
      while kill -0 "$mpid" 2>/dev/null; do sleep 60; done
    fi
  fi
  log "waiting for GPU idle"
  while pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/spark-ctx-ladder\.py' >/dev/null 2>&1 \
     || pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/spark-golden-workflow\.py' >/dev/null 2>&1 \
     || pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/spark-kv-sweep\.py' >/dev/null 2>&1 \
     || pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/golden-inventory-audit\.py' >/dev/null 2>&1 \
     || pgrep -f '/opt/spark/venv/bin/python3 /opt/spark/scripts/spark-inference\.py bench' >/dev/null 2>&1; do
    sleep 45
  done
}

log "=== ornith Q8_0 queue started pid=$$ ==="
wait_for_download
update_recipe_q8
wait_for_main_queue

log ">>> golden workflow $INV (Q8_0 full re-bench)"
/usr/local/bin/spark inference down 2>/dev/null || true
if "$PY" "$WORKFLOW" --only "$INV" --skip-shelf --force >>"$LOG" 2>&1; then
  log "OK golden workflow $INV"
else
  log "FAIL golden workflow $INV"
fi

"$PY" "$PUBLISH" --only "$INV" >>"$LOG" 2>&1 || true
/usr/local/bin/spark models inventory >>"$LOG" 2>&1 || true
log "=== ornith Q8_0 queue DONE ==="
rm -f "$PID_FILE"
