#!/usr/bin/env bash
# Finish interrupted Qwen3.6-27B batch + Coder-Next downloads
set -euo pipefail

HF="/opt/spark/venv/bin/hf"
LOG_DIR="/opt/spark/logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/qwen-download-missing-${TS}.log"

exec > >(tee -a "$LOG") 2>&1

echo "==> Missing downloads started $(date -Is)"
echo "Log: $LOG"
df -h /models

download_files() {
  local repo="$1" dest="$2"
  shift 2
  echo
  echo "==> FILES $repo -> $dest ($# files)"
  mkdir -p "$dest"
  "$HF" download "$repo" "$@" --local-dir "$dest"
}

download_repo() {
  local repo="$1" dest="$2"
  echo
  echo "==> REPO $repo -> $dest"
  mkdir -p "$dest"
  "$HF" download "$repo" --local-dir "$dest"
}

# Interrupted from main batch
download_files unsloth/Qwen3.6-27B-MTP-GGUF /models/unsloth/qwen3.6-27b/mtp-gguf \
  Qwen3.6-27B-UD-Q4_K_XL.gguf

# Coder-Next pair (user requested both)
download_repo Qwen/Qwen3-Coder-Next-FP8 /models/qwen/qwen3-coder-next/fp8
download_repo saricles/Qwen3-Coder-Next-NVFP4-GB10 /models/saricles/qwen3-coder-next/nvfp4

# Queued next: scripts/spark-download-step37-flash.sh (via spark-download-queue-tail.sh)

echo
echo "==> Finished $(date -Is)"
du -sh /models/unsloth/qwen3.6-27b/mtp-gguf \
  /models/qwen/qwen3-coder-next/fp8 \
  /models/saricles/qwen3-coder-next/nvfp4 2>/dev/null | sort -hr || true
df -h /models

if command -v spark-inventory-build >/dev/null; then
  spark-inventory-build || true
elif [[ -x /opt/spark/scripts/spark-inventory-build.py ]]; then
  /opt/spark/venv/bin/python /opt/spark/scripts/spark-inventory-build.py || true
fi