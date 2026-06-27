#!/usr/bin/env bash
set -euo pipefail
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
cp "${SPARK_STAGING}/services/qwen36-nvfp4/compose.yaml" "${SPARK_ROOT}/services/qwen36-nvfp4/compose.yaml"
cp "${SPARK_STAGING}/portal/index.html" "${SPARK_ROOT}/portal/"
echo "Synced compose + portal"
cp "${SPARK_STAGING}/docs/INFERENCE-SMOKE.md" "${SPARK_ROOT}/docs/"
