#!/usr/bin/env bash
# Install SparkInfer helper + pull the pinned GHCR image. Does not download weights.
set -euo pipefail
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
TARGET="${SPARK_ROOT}"
LAUNCHER="${TARGET}/services/sparkinfer-mia"
PIN="${TARGET}/data/sparkinfer-mia.yaml"

echo "==> Sync SparkInfer launcher + helper"
rsync -a "${SPARK_STAGING}/scripts/spark-sparkinfer" "${TARGET}/scripts/spark-sparkinfer"
chmod +x "${TARGET}/scripts/spark-sparkinfer"
rsync -a "${SPARK_STAGING}/data/sparkinfer-mia.yaml" "${TARGET}/data/" 2>/dev/null || true
mkdir -p "${LAUNCHER}"
rsync -a --exclude cache --exclude compose.yml --exclude data --exclude hf-hub \
  "${SPARK_STAGING}/services/sparkinfer-mia/" "${LAUNCHER}/"
chmod +x "${LAUNCHER}/start.sh" "${LAUNCHER}/download.sh" "${LAUNCHER}/stop.sh" 2>/dev/null || true

WEIGHTS="/models/0xsero/deepseek-v4-flash-0731-spark"
mkdir -p "${WEIGHTS}/data" "${WEIGHTS}/hf-hub" "${LAUNCHER}/cache"
if [[ ! -L "${LAUNCHER}/data" ]]; then
  rm -rf "${LAUNCHER}/data" 2>/dev/null || true
  ln -sfn "${WEIGHTS}/data" "${LAUNCHER}/data"
fi

IMAGE="ghcr.io/0xsero/deepseek-v4-flash-0731-spark-sparkinfer@sha256:2e077489a83a0360952828051fe7f7a32c1801e5ce8436d85f7267583d614ff4"
if [[ -f "${PIN}" ]]; then
  digest="$(python3 -c "import yaml; print(((yaml.safe_load(open('${PIN}')) or {}).get('source') or {}).get('image_digest') or '')" 2>/dev/null || true)"
  repo="$(python3 -c "import yaml; print(((yaml.safe_load(open('${PIN}')) or {}).get('source') or {}).get('image') or '')" 2>/dev/null || true)"
  if [[ -n "${digest}" && -n "${repo}" ]]; then
    IMAGE="${repo}@${digest}"
  fi
fi

echo "==> Pull pinned image (no GPU)"
docker pull "${IMAGE}"

if [[ -f "${INSTALL_DIR}/modules/core/cli.sh" ]]; then
  bash "${INSTALL_DIR}/modules/core/cli.sh"
fi

echo
echo "Done. spark engine sparkinfer → ${TARGET}/scripts/spark-sparkinfer"
echo "Weights gate: ${WEIGHTS}/data/tp1/rank-sliced-tp1-manifest.json"
echo "Smoke: docs/runbooks/smoke-sparkinfer.md"
