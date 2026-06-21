#!/usr/bin/env bash
# Resume Qwen3.6-27B main batch (skips files already on disk via hf download)
set -euo pipefail
exec /opt/spark/scripts/spark-download-qwen36-27b.sh