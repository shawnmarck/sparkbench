#!/usr/bin/env bash
# Qwen3.6-27B MoQ GGUF (kaitchup) — 3 Spark-friendly tiers for llama.cpp A/B
#   MoQ-4.0  ~14 GB  long-context / agent KV headroom
#   MoQ-4.5  ~16 GB  daily driver (balanced)
#   MoQ-5.0  ~18 GB  max MoQ quality
set -euo pipefail

HF="/opt/spark/venv/bin/hf"
LOG_DIR="/opt/spark/logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/qwen36-27b-moq-download-${TS}.log"

exec > >(tee -a "$LOG") 2>&1

DEST="/models/kaitchup/qwen3.6-27b/moq"

echo "==> Qwen3.6-27B MoQ GGUF download started $(date -Is)"
echo "Log: $LOG"
df -h /models

mkdir -p "$DEST"
"$HF" download kaitchup/Qwen3.6-27B-GGUF-MoQ \
  --local-dir "$DEST" \
  MoQ-4.0.gguf \
  MoQ-4.5.gguf \
  MoQ-5.0.gguf

echo
echo "==> Finished $(date -Is)"
du -sh "$DEST"/* 2>/dev/null | sort -hr || du -sh "$DEST"
df -h /models

if command -v spark-inventory-build >/dev/null; then
  spark-inventory-build || true
elif [[ -x /opt/spark/scripts/spark-inventory-build.py ]]; then
  /opt/spark/venv/bin/python /opt/spark/scripts/spark-inventory-build.py || true
fi