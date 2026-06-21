#!/usr/bin/env bash
set -euo pipefail

SPARK_ROOT="/opt/spark"
STAGING="/home/techno/spark"

echo "==> Sync staging"
rsync -a "${STAGING}/docs/" "${SPARK_ROOT}/docs/" 2>/dev/null || true
rsync -a "${STAGING}/install/" "${SPARK_ROOT}/install/" 2>/dev/null || true

echo "==> Create /ops layout"
mkdir -p /ops/rookery /ops/vllm-studio/data
chown -R techno:techno /ops

if [[ ! -f /ops/README.md ]]; then
  install -m 644 "${SPARK_ROOT}/docs/OPS-LAYOUT.md" /ops/README.md 2>/dev/null || true
fi

echo "Done. /ops ready for rookery + vllm-studio installs."
