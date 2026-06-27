#!/usr/bin/env bash
# Re-run KV sweep --force for profiles that failed in fleet golden workflow.
set -euo pipefail
LOG=/opt/spark/logs/kv-sweep-retry.log
PY=/opt/spark/venv/bin/python3
SWEEP=/opt/spark/scripts/spark-kv-sweep.py
PROFILES=(
  empero-ai-qwythos-9b-claude-mythos-5-1m-eugr
  google-diffusiongemma-26b-a4b-it-eugr
  google-gemma-4-12b-it-llama
  google-gemma-4-26b-a4b-it-eugr
)

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

log "=== kv sweep retry batch (${#PROFILES[@]} profiles) ==="
/usr/local/bin/spark inference down 2>/dev/null || true

for prof in "${PROFILES[@]}"; do
  log ">>> $prof"
  if "$PY" "$SWEEP" "$prof" --force >>"$LOG" 2>&1; then
    log "OK $prof"
  else
    log "FAIL $prof (exit $?)"
  fi
done

log "=== updating golden-workflow-report.json ==="
"$PY" - <<'PY' >>"$LOG" 2>&1
import json
from pathlib import Path
import yaml

ROOT = Path("/opt/spark")
report_path = ROOT / "run/golden-workflow-report.json"
if not report_path.is_file():
    print("no report file")
    raise SystemExit(0)

report = json.loads(report_path.read_text())
changed = 0
for entry in report.get("models") or []:
    prof = entry.get("golden_profile")
    if not prof:
        continue
    recipe_path = ROOT / "recipes" / f"{prof}.yaml"
    if not recipe_path.is_file():
        continue
    recipe = yaml.safe_load(recipe_path.read_text()) or {}
    ks = (recipe.get("context") or {}).get("kv_sweep") or {}
    results = ks.get("results") or []
    if not results:
        continue
    ok = sum(1 for r in results if r.get("status") == "ok")
    phase = {
        "status": "ok" if ok else "failed",
        "returncode": 0 if ok else 1,
        "kv_results": len(results),
        "kv_ok": ok,
    }
    entry.setdefault("phases", {})["kv_sweep"] = phase
    golden_ok = entry.get("phases", {}).get("golden", {}).get("status") == "ok"
    if golden_ok and ok:
        entry["status"] = "complete"
    elif golden_ok:
        entry["status"] = "partial"
    changed += 1

complete = sum(1 for m in report["models"] if m.get("status") == "complete")
partial = sum(1 for m in report["models"] if m.get("status") == "partial")
failed = sum(1 for m in report["models"] if m.get("status") == "failed")
report["summary"] = {
    "complete": complete,
    "partial": partial,
    "failed": failed,
    "total": len(report["models"]),
}
report_path.write_text(json.dumps(report, indent=2) + "\n")
print(f"updated {changed} report entries: complete={complete} partial={partial}")
PY

log "=== kv sweep retry batch done ==="

log "=== resuming fleet golden workflow ==="
setsid /opt/spark/venv/bin/python3 /opt/spark/scripts/spark-golden-workflow.py \
  --all --skip-shelf --resume >> /opt/spark/logs/golden-workflow.log 2>&1 < /dev/null &
echo $! > /opt/spark/run/golden-workflow.pid
log "fleet workflow pid $(cat /opt/spark/run/golden-workflow.pid)"
