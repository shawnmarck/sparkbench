#!/usr/bin/env bash
# Download curated model set to /models (Spark-first). Logs to /opt/spark/logs/
set -euo pipefail

HF="/opt/spark/venv/bin/hf"
LOG_DIR="/opt/spark/logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/model-download-${TS}.log"

exec > >(tee -a "$LOG") 2>&1

echo "==> Model download batch started $(date -Is)"
echo "Log: $LOG"
df -h /models

download_repo() {
  local repo="$1" dest="$2"
  shift 2
  echo
  echo "==> REPO $repo -> $dest"
  mkdir -p "$dest"
  "$HF" download "$repo" "$@" --local-dir "$dest"
}

download_files() {
  local repo="$1" dest="$2"
  shift 2
  echo
  echo "==> FILES $repo -> $dest ($# files)"
  mkdir -p "$dest"
  "$HF" download "$repo" "$@" --local-dir "$dest"
}

# --- User requested ---
download_repo nvidia/Qwen3.6-35B-A3B-NVFP4 /models/nvidia/qwen3.6-35b-a3b/nvfp4

# GGUF: practical quants only (full repo is ~550GB)
download_files unsloth/Qwen3.6-35B-A3B-GGUF /models/unsloth/qwen3.6-35b-a3b/gguf \
  Qwen3.6-35B-A3B-UD-Q4_K_M.gguf \
  Qwen3.6-35B-A3B-MXFP4_MOE.gguf

# --- Curated Hermes / Spark agentic set (~230GB) ---
download_repo nvidia/Qwen3-30B-A3B-NVFP4 /models/nvidia/qwen3-30b-a3b/nvfp4

download_repo NousResearch/Hermes-4-14B /models/nousresearch/hermes-4-14b/hf

download_repo microsoft/phi-4 /models/microsoft/phi-4/hf

download_files unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF /models/unsloth/qwen3-coder-30b-a3b-instruct/gguf \
  Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf \
  Qwen3-Coder-30B-A3B-Instruct-Q5_K_M.gguf

download_repo deepseek-ai/DeepSeek-R1-Distill-Qwen-32B /models/deepseek-ai/deepseek-r1-distill-qwen-32b/hf

download_repo NousResearch/Hermes-3-Llama-3.1-8B /models/nousresearch/hermes-3-llama-3.1-8b/hf

download_repo google/gemma-3-27b-it /models/google/gemma-3-27b-it/hf

echo
echo "==> Download batch finished $(date -Is)"
du -sh /models/*/* 2>/dev/null | sort -hr || true
df -h /models

echo
echo "==> Refreshing model inventory dashboard"
if command -v spark-inventory-build >/dev/null; then
  spark-inventory-build || true
elif [[ -x /opt/spark/scripts/spark-inventory-build ]]; then
  /opt/spark/scripts/spark-inventory-build || true
fi
