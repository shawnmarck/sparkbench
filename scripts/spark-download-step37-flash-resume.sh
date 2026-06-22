#!/usr/bin/env bash
# Resume Step-3.7 IQ4_XS shards only (mmproj already on disk)
set -euo pipefail

HF="/opt/spark/venv/bin/hf"
DEST="/models/stepfun-ai/step-3.7-flash/gguf"
LOG="/opt/spark/logs/step37-flash-resume-$(date +%Y%m%d-%H%M%S).log"

exec > >(tee -a "$LOG") 2>&1

echo "==> Step-3.7 IQ4_XS resume $(date -Is)"
mkdir -p "$DEST"

"$HF" download stepfun-ai/Step-3.7-Flash-GGUF \
  --local-dir "$DEST" \
  IQ4_XS/Step-3.7-flash-IQ4_XS-00001-of-00003.gguf \
  IQ4_XS/Step-3.7-flash-IQ4_XS-00002-of-00003.gguf \
  IQ4_XS/Step-3.7-flash-IQ4_XS-00003-of-00003.gguf

echo "==> Done"
du -sh "$DEST" "$DEST"/IQ4_XS 2>/dev/null || du -sh "$DEST"/*