#!/usr/bin/env bash
# SGLang + DFlash2 for RadixArk Qwen3.8-27B-NVFP4 on one DGX Spark.
# Packed NVFP4 target (not BF16-lm_head). Draft is the incoai/z-lab DFlash2
# snapshot already on disk (byte-identical). k=8. Vision tower loaded; image
# pixels capped so a 16M-px dump cannot spike unified memory.
# Cookbook: https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B
#
# Image pin: lmsysorg/sglang:nightly-cu134-20260909-708f51e (main 708f51e44).
# Contains sglang #35255 — streaming disconnect no longer leaves a zombie
# request holding a --max-running-requests slot. Replaces
# lmsysorg/sglang:dev-qwen38-27b-dflash2 (5f55db35e, 2026-08-22).
# Re-pin to v0.5.20 when tagged.
set -euo pipefail

NAME="${SGLANG_NAME:-qwen38-sglang}"
IMAGE="${SGLANG_IMAGE:-lmsysorg/sglang@sha256:00205b89f74691f76a0ffbd6846376d9323971930a5d59bf63a65dadc7d67927}"
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
LANGUAGE_ONLY="${SGLANG_LANGUAGE_ONLY:-0}"
# 1920^2 — 1080p screenshots fit; 4k/16M-px HF default gets downscaled.
IMAGE_MAX_PIXELS="${SGLANG_IMAGE_MAX_PIXELS:-3686400}"
# Do not put JSON braces in ${var:-...} — bash closes the expansion at the first }.
MM_PER_REQUEST="${SGLANG_MM_PER_REQUEST:-}"
if [[ -z "$MM_PER_REQUEST" ]]; then
  MM_PER_REQUEST='{"image":4,"video":1}'
fi

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
  mm_args=()
  if [[ "$LANGUAGE_ONLY" == "1" || "$LANGUAGE_ONLY" == "true" ]]; then
    mm_args+=(--language-only)
  else
    mm_args+=(
      --mm-process-config "{\"image\":{\"max_pixels\":${IMAGE_MAX_PIXELS}},\"video\":{\"max_pixels\":${IMAGE_MAX_PIXELS}}}"
      --limit-mm-data-per-request "$MM_PER_REQUEST"
    )
  fi
  docker run -d --name "$NAME" \
    --gpus all --ipc=host --network host \
    --memory 100g --memory-swap 100g \
    -v "$MODEL:/model:ro" \
    -v "$DRAFT:/draft:ro" \
    --env SGLANG_DISABLE_FA3_PREFILL=1 \
    --env SGLANG_IMAGE_MAX_PIXELS="$IMAGE_MAX_PIXELS" \
    "$IMAGE" \
    sglang serve \
      --trust-remote-code \
      --model-path /model \
      --served-model-name "$SERVED" \
      "${mm_args[@]}" \
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
      --enable-metrics \
      --host 0.0.0.0 \
      --port "$PORT"
  if [[ "$LANGUAGE_ONLY" == "1" || "$LANGUAGE_ONLY" == "true" ]]; then
    echo "started $NAME on :$PORT (model $SERVED, ctx=$CTX, dflash k=$DRAFT_TOKENS, language-only)"
  else
    echo "started $NAME on :$PORT (model $SERVED, ctx=$CTX, dflash k=$DRAFT_TOKENS, vision max_px=$IMAGE_MAX_PIXELS)"
  fi
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
