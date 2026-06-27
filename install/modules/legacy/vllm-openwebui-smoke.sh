#!/usr/bin/env bash
# Phase 3 smoke test: vLLM (Qwen3.6 NVFP4) + Open WebUI
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
STAGING="${SPARK_STAGING}"

echo "==> Sync docs, portal, services, scripts"
mkdir -p "${SPARK_ROOT}/services/qwen36-nvfp4"
cp "${STAGING}/docs/INFERENCE-SMOKE.md" "${SPARK_ROOT}/docs/"
cp "${STAGING}/portal/index.html" "${SPARK_ROOT}/portal/"
cp "${STAGING}/services/qwen36-nvfp4/compose.yaml" "${SPARK_ROOT}/services/qwen36-nvfp4/"
cp "${STAGING}/scripts/spark-inference" "${SPARK_ROOT}/scripts/"
chmod +x "${SPARK_ROOT}/scripts/spark-inference"
# CLI: install/20-spark-cli.sh → spark inference

echo "==> Docker: add ${SPARK_USER} to docker group"
usermod -aG docker "${SPARK_USER}"

echo "==> Verify NVIDIA container runtime"
if ! docker info 2>/dev/null | grep -qi nvidia; then
  echo "Note: nvidia runtime may need docker restart after first GPU container"
fi

echo "==> Pull images (large — vLLM cu130 nightly ~15–20 GB)"
docker compose -f "${SPARK_ROOT}/services/qwen36-nvfp4/compose.yaml" pull

echo "==> Start stack"
docker compose -f "${SPARK_ROOT}/services/qwen36-nvfp4/compose.yaml" up -d

echo
echo "Done."
echo "  Chat UI:  http://sparky:3000"
echo "  vLLM API: http://sparky:8000/v1"
echo "  Logs:     spark inference logs"
echo "  Status:   spark inference status"
echo
echo "First vLLM boot may take 5–15 minutes (CUDA graph compile)."
