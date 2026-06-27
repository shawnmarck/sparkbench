#!/usr/bin/env bash
# Wait for in-flight batch, then run queued downloads
set -euo pipefail

echo "==> Download queue tail waiting for spark-download-qwen36-27b-missing.sh ..."
while pgrep -f "spark-download-qwen36-27b-missing.sh" >/dev/null 2>&1; do
  sleep 30
done
echo "==> Prior batch done; starting Step-3.7-Flash"
/opt/spark/scripts/spark-download-step37-flash.sh

echo "==> Starting DeepSeek-V4-Flash-Spark GGUF (+ MoQ queued after)"
exec /opt/spark/scripts/spark-download-deepseek-v4-flash-spark.sh