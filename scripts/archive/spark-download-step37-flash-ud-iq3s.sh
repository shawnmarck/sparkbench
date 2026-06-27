#!/usr/bin/env bash
# unsloth Step-3.7-Flash UD-IQ3_S (~80 GB, 3 shards) — smaller than IQ4_XS golden tier
set -euo pipefail

HF="/opt/spark/venv/bin/hf"
LOG_DIR="/opt/spark/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/step37-flash-ud-iq3s-download.log"

exec >>"$LOG" 2>&1
echo "=== Step-3.7-Flash UD-IQ3_S download started $(date -Is) ==="
df -h /models

DEST="/models/stepfun-ai/step-3.7-flash/gguf"
mkdir -p "$DEST/UD-IQ3_S"

"$HF" download unsloth/Step-3.7-Flash-GGUF \
  --local-dir "$DEST" \
  UD-IQ3_S/Step-3.7-Flash-UD-IQ3_S-00001-of-00003.gguf \
  UD-IQ3_S/Step-3.7-Flash-UD-IQ3_S-00002-of-00003.gguf \
  UD-IQ3_S/Step-3.7-Flash-UD-IQ3_S-00003-of-00003.gguf

echo
echo "=== Finished $(date -Is) ==="
du -sh "$DEST/UD-IQ3_S" 2>/dev/null || true
# mmproj already present from IQ4_XS download
ls -la "$DEST/mmproj-step3.7-flash-f16.gguf" 2>/dev/null || echo "NOTE: mmproj missing — download mmproj-step3.7-flash-f16.gguf for vision"

if command -v spark >/dev/null; then
  spark models inventory || true
elif [[ -x /opt/spark/scripts/spark-inventory-build.py ]]; then
  /opt/spark/venv/bin/python3 /opt/spark/scripts/spark-inventory-build.py || true
fi
