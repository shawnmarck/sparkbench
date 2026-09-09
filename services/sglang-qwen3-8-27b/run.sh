#!/usr/bin/env bash
# SGLang + DFlash2 for RadixArk Qwen3.8-27B-NVFP4 on one DGX Spark.
# Packed NVFP4 target (not BF16-lm_head). Draft is the incoai/z-lab DFlash2
# snapshot already on disk (byte-identical). k=8.
# Cookbook: https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B
set -euo pipefail

NAME="${SGLANG_NAME:-qwen38-sglang}"
IMAGE="${SGLANG_IMAGE:-lmsysorg/sglang:dev-qwen38-27b-dflash2}"
MODEL="${SGLANG_MODEL:-/models/radixark/qwen3.8-27b/nvfp4}"
DRAFT="${SGLANG_DRAFT:-/models/incoai/qwen3.8-27b-dflash2/dflash}"
PORT="${SGLANG_PORT:-8000}"
MEM_FRAC="${SGLANG_MEM_FRACTION:-0.80}"
MAX_RUNNING="${SGLANG_MAX_RUNNING:-8}"
MAMBA_CACHE="${SGLANG_MAMBA_CACHE:-64}"
CTX="${SGLANG_CTX:-262144}"
CHUNK="${SGLANG_CHUNK:-8192}"
DRAFT_TOKENS="${SGLANG_DRAFT_TOKENS:-8}"
SERVED="${SGLANG_SERVED_NAME:-qwen3.8-27b-dflash2-sglang}"

usage() {
  echo "usage: $0 {up|down|status|logs|pull}"
}

pull() {
  docker pull "$IMAGE"
}

up() {
  if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
    docker rm -f "$NAME" >/dev/null
  fi
  if [[ ! -f "$MODEL/config.json" ]]; then
    echo "missing target weights at $MODEL" >&2
    exit 1
  fi
  if [[ ! -f "$DRAFT/config.json" ]]; then
    echo "missing DFlash2 draft at $DRAFT" >&2
    exit 1
  fi
  docker run -d --name "$NAME" \
    --gpus all --ipc=host --network host \
    --memory 100g --memory-swap 100g \
    -v "$MODEL:/model:ro" \
    -v "$DRAFT:/draft:ro" \
    --env SGLANG_DISABLE_FA3_PREFILL=1 \
    "$IMAGE" \
    sglang serve \
      --trust-remote-code \
      --model-path /model \
      --served-model-name "$SERVED" \
      --language-only \
      --kv-cache-dtype fp8_e4m3 \
      --mem-fraction-static "$MEM_FRAC" \
      --attention-backend flashinfer \
      --chunked-prefill-size "$CHUNK" \
      --disable-prefill-cuda-graph \
      --disable-flashinfer-autotune \
      --mamba-ssm-dtype bfloat16 \
      --mamba-radix-cache-strategy extra_buffer \
      --max-mamba-cache-size "$MAMBA_CACHE" \
      --context-length "$CTX" \
      --max-running-requests "$MAX_RUNNING" \
      --speculative-algorithm DFLASH \
      --speculative-draft-model-path /draft \
      --speculative-draft-model-quantization unquant \
      --speculative-num-draft-tokens "$DRAFT_TOKENS" \
      --reasoning-parser qwen3 \
      --tool-call-parser qwen3_coder \
      --sleep-on-idle \
      --host 0.0.0.0 \
      --port "$PORT"
  echo "started $NAME on :$PORT (model $SERVED, ctx=$CTX, dflash k=$DRAFT_TOKENS)"
}

down() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  echo "stopped $NAME"
}

status() {
  if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "container: up"
    curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/v1/models" || echo "api: not ready"
  else
    echo "container: down"
    return 1
  fi
}

cmd="${1:-status}"
case "$cmd" in
  up) up ;;
  down) down ;;
  status) status ;;
  logs) docker logs --tail 80 "$NAME" ;;
  pull) pull ;;
  *) usage; exit 2 ;;
esac
