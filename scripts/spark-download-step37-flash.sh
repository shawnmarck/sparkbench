#!/usr/bin/env bash
# Step-3.7-Flash GGUF for single GB10 (llama.cpp path)
# IQ4_XS (~105 GB) + mmproj — Spark-benchmarked quant tier
set -euo pipefail

HF="/opt/spark/venv/bin/hf"
LOG_DIR="/opt/spark/logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/step37-flash-download-${TS}.log"

exec > >(tee -a "$LOG") 2>&1

DEST="/models/stepfun-ai/step-3.7-flash/gguf"

echo "==> Step-3.7-Flash GGUF download started $(date -Is)"
echo "Log: $LOG"
df -h /models

mkdir -p "$DEST"

# IQ4_XS: best size/quality for 128 GB unified memory (per StepFun DGX Spark benches)
"$HF" download stepfun-ai/Step-3.7-Flash-GGUF \
  --local-dir "$DEST" \
  IQ4_XS/Step-3.7-flash-IQ4_XS-00001-of-00003.gguf \
  IQ4_XS/Step-3.7-flash-IQ4_XS-00002-of-00003.gguf \
  IQ4_XS/Step-3.7-flash-IQ4_XS-00003-of-00003.gguf \
  mmproj-step3.7-flash-f16.gguf

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
echo "==> Queue: starting DeepSeek-V4-Flash-Spark GGUF"
/opt/spark/scripts/spark-download-deepseek-v4-flash-spark.sh