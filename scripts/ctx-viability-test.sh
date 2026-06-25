#!/usr/bin/env bash
# Viability: load profile at target ctx, wait for /v1/models, optional tiny completion.
set -euo pipefail

PROFILE="${1:?profile id}"
CTX="${2:?ctx tokens}"
KV="${3:-fp8}"
READY_SECS="${4:-3600}"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

refresh_native() {
  local profile="$1"
  python3 <<PY
import json, yaml
from pathlib import Path
p = Path("/opt/spark/recipes/${profile}.yaml")
r = yaml.safe_load(p.read_text()) or {}
inv = r.get("inventory_path", "")
cfg = json.loads(Path(f"/models/{inv}/hf/config.json").read_text())
native = 16384
for src in (cfg, cfg.get("text_config") or {}):
    if isinstance(src, dict):
        v = src.get("max_position_embeddings")
        if isinstance(v, (int, float)) and v > native:
            native = int(v)
block = r.setdefault("context", {})
block["native"] = native
p.write_text(yaml.safe_dump(r, sort_keys=False, default_flow_style=False))
print(f"native={native}")
PY
}

wait_ready() {
  local port="${1:-8000}"
  local deadline=$((SECONDS + READY_SECS))
  while (( SECONDS < deadline )); do
    if curl -sf "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
      return 0
    fi
    sleep 10
  done
  return 1
}

smoke_completion() {
  local model="$1"
  curl -sf "http://127.0.0.1:8000/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${model}\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK in one word.\"}],\"max_tokens\":8}" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'][:80])"
}

log "=== viability ${PROFILE} ctx=${CTX} kv=${KV} ==="
refresh_native "${PROFILE}"
spark inference down >/dev/null 2>&1 || true
log "starting inference up..."
if ! spark inference up "${PROFILE}" --ctx "${CTX}" --kv "${KV}" 2>&1 | tail -3; then
  log "FAIL: inference up returned error"
  docker logs vllm_node 2>&1 | tail -20
  exit 1
fi

log "waiting for /v1/models (up to ${READY_SECS}s)..."
if ! wait_ready 8000; then
  log "FAIL: not ready within ${READY_SECS}s"
  docker logs vllm_node 2>&1 | tail -25
  exit 1
fi

SERVED=$(curl -sf http://127.0.0.1:8000/v1/models | python3 -c "import json,sys; print(json.load(sys.stdin)['data'][0]['id'])")
MAX_LEN=$(curl -sf http://127.0.0.1:8000/v1/models | python3 -c "import json,sys; print(json.load(sys.stdin)['data'][0].get('max_model_len','?'))")
log "ready served=${SERVED} max_model_len=${MAX_LEN}"
if [[ "${MAX_LEN}" != "${CTX}" ]]; then
  log "FAIL: requested ctx=${CTX} but max_model_len=${MAX_LEN}"
  exit 1
fi

if smoke_completion "${SERVED}" >/tmp/ctx-viability-smoke.txt 2>&1; then
  log "smoke ok: $(cat /tmp/ctx-viability-smoke.txt)"
else
  log "WARN: smoke completion failed (load still ok)"
fi

log "OK ${PROFILE} ctx=${CTX}"
