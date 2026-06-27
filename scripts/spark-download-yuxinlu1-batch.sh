#!/usr/bin/env bash
# Download yuxinlu1 Gemma4 community GGUF set (Q4_K_M). Logs to /opt/spark/logs/
set -euo pipefail

HF="/opt/spark/venv/bin/hf"
LOG_DIR="/opt/spark/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/yuxinlu1-download.log"

exec >>"$LOG" 2>&1
echo "=== yuxinlu1 download batch started $(date -Is) ==="
df -h /models

download_files() {
  local repo="$1" dest="$2"
  shift 2
  echo
  echo "==> FILES $repo -> $dest ($# files)"
  mkdir -p "$dest"
  "$HF" download "$repo" "$@" --local-dir "$dest"
}

# v2 agentic (tool-use / agentic fine-tune)
download_files yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF \
  /models/yuxinlu1/gemma-4-12b-agentic-v2/gguf \
  gemma4-v2-Q4_K_M.gguf

# Mellum2 MoE coding (12B / 2.5B active)
download_files yuxinlu1/Mellum2-12B-A2.5B-Claude-4.6-4.8-Opus-Thinking-GGUF \
  /models/yuxinlu1/mellum2-12b-opus-thinking/gguf \
  mellum2-claude-Q4_K_M.gguf

# Opus-style general reasoning
download_files yuxinlu1/gemma-4-12B-it-Claude-4.6-4.8-Opus-GGUF \
  /models/yuxinlu1/gemma-4-12b-opus-reasoning/gguf \
  gemma4-opus48-Q4_K_M.gguf

echo
echo "=== yuxinlu1 download batch finished $(date -Is) ==="
du -sh /models/yuxinlu1/gemma-4-12b-agentic-v2 \
  /models/yuxinlu1/mellum2-12b-opus-thinking \
  /models/yuxinlu1/gemma-4-12b-opus-reasoning 2>/dev/null || true

if command -v spark-inventory-refresh >/dev/null; then
  spark-inventory-refresh || spark-inventory-build || true
elif command -v spark-inventory-build >/dev/null; then
  spark-inventory-build || true
fi
