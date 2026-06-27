#!/usr/bin/env bash
# Download Gemma 4 catalog set + MTP drafter. Logs to /opt/spark/logs/
set -euo pipefail

HF="/opt/spark/venv/bin/hf"
LOG_DIR="/opt/spark/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/gemma4-download.log"

exec >>"$LOG" 2>&1
echo "=== Gemma 4 download batch started $(date -Is) ==="
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

# 1. Gemma 4 12B IT (HF / vLLM path)
download_repo google/gemma-4-12B-it /models/google/gemma-4-12b-it/hf

# 2. Gemma 4 26B A4B MoE IT (HF)
download_repo google/gemma-4-26B-A4B-it /models/google/gemma-4-26b-a4b-it/hf

# 3. Community coding GGUF (llama.cpp)
download_files yuxinlu1/gemma-4-12B-coder-fable5-composer2.5-v1-GGUF \
  /models/yuxinlu1/gemma-4-12b-coder-fable5-composer2.5-v1/gguf \
  gemma4-coding-Q4_K_M.gguf

# 4. Official Unsloth GGUF + MTP drafter for speculative decoding
download_files unsloth/gemma-4-12B-it-GGUF /models/google/gemma-4-12b-it/gguf \
  gemma-4-12b-it-Q4_K_M.gguf \
  mtp-gemma-4-12b-it.gguf

echo
echo "=== Gemma 4 download batch finished $(date -Is) ==="
du -sh /models/google/gemma-4-12b-it /models/google/gemma-4-26b-a4b-it \
  /models/yuxinlu1/gemma-4-12b-coder-fable5-composer2.5-v1 2>/dev/null || true

if command -v spark-inventory-refresh >/dev/null; then
  spark-inventory-refresh || spark-inventory-build || true
elif command -v spark-inventory-build >/dev/null; then
  spark-inventory-build || true
fi
