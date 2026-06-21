#!/usr/bin/env bash
# Download Qwen3.6-27B variants to /models (Spark GB10)
set -euo pipefail

HF="/opt/spark/venv/bin/hf"
LOG_DIR="/opt/spark/logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/qwen36-27b-download-${TS}.log"

exec > >(tee -a "$LOG") 2>&1

echo "==> Qwen3.6-27B download started $(date -Is)"
echo "Log: $LOG"
df -h /models

download_repo() {
  local repo="$1" dest="$2"
  echo
  echo "==> REPO $repo -> $dest"
  mkdir -p "$dest"
  "$HF" download "$repo" --local-dir "$dest"
}

download_files() {
  local repo="$1" dest="$2"
  shift 2
  echo
  echo "==> FILES $repo -> $dest ($# files)"
  mkdir -p "$dest"
  "$HF" download "$repo" "$@" --local-dir "$dest"
}

download_repo unsloth/Qwen3.6-27B-NVFP4 /models/unsloth/qwen3.6-27b/nvfp4
download_repo Qwen/Qwen3.6-27B-FP8 /models/qwen/qwen3.6-27b/fp8

download_files unsloth/Qwen3.6-27B-GGUF /models/unsloth/qwen3.6-27b/gguf \
  Qwen3.6-27B-UD-Q4_K_XL.gguf \
  Qwen3.6-27B-UD-Q5_K_XL.gguf

download_files unsloth/Qwen3.6-27B-MTP-GGUF /models/unsloth/qwen3.6-27b/mtp-gguf \
  Qwen3.6-27B-UD-Q4_K_XL.gguf

# --- Spark community extras (DFlash drafters + PrismaQuant) ---
download_repo z-lab/Qwen3.6-27B-DFlash /models/z-lab/qwen3.6-27b/dflash
download_repo rdtand/Qwen3.6-27B-PrismaQuant-5.5bit-vllm /models/rdtand/qwen3.6-27b/prismaquant
download_repo z-lab/Qwen3.6-35B-A3B-DFlash /models/z-lab/qwen3.6-35b-a3b/dflash

echo
echo "==> Download finished $(date -Is)"
du -sh /models/unsloth/qwen3.6-27b/* /models/qwen/qwen3.6-27b/* \
  /models/z-lab/qwen3.6-27b/* /models/rdtand/qwen3.6-27b/* \
  /models/z-lab/qwen3.6-35b-a3b/* 2>/dev/null | sort -hr || true
df -h /models

if command -v spark-inventory-build >/dev/null; then
  spark-inventory-build || true
elif [[ -x /opt/spark/scripts/spark-inventory-build.py ]]; then
  /opt/spark/venv/bin/python /opt/spark/scripts/spark-inventory-build.py || true
fi