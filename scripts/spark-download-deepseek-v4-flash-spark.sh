#!/usr/bin/env bash
# DeepSeek-V4-Flash Spark GGUF (0xSero REAP quant for GB10)
set -euo pipefail

HF="/opt/spark/venv/bin/hf"
LOG_DIR="/opt/spark/logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/deepseek-v4-flash-spark-download-${TS}.log"

exec > >(tee -a "$LOG") 2>&1

DEST="/models/0xsero/deepseek-v4-flash-spark/gguf"

echo "==> DeepSeek-V4-Flash-Spark GGUF download started $(date -Is)"
echo "Log: $LOG"
df -h /models

mkdir -p "$DEST"
"$HF" download 0xSero/DeepSeek-V4-Flash-Spark-GGUF --local-dir "$DEST"

echo
echo "==> Finished $(date -Is)"
du -sh "$DEST"/* 2>/dev/null | sort -hr || du -sh "$DEST"
df -h /models

if command -v spark-inventory-build >/dev/null; then
  spark-inventory-build || true
elif [[ -x /opt/spark/scripts/spark-inventory-build.py ]]; then
  /opt/spark/venv/bin/python /opt/spark/scripts/spark-inventory-build.py || true
fi

echo
echo "==> Queue: starting Qwen3.6-27B MoQ GGUF"
/opt/spark/scripts/spark-download-qwen36-27b-moq.sh