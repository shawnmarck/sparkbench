#!/usr/bin/env bash
# Deploy model inventory (catalog, builder, portal page)
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
STAGING="${SPARK_STAGING}"

echo "==> Sync to ${SPARK_ROOT}"
mkdir -p "${SPARK_ROOT}"/{data,scripts,portal,install}
rsync -a "${STAGING}/data/" "${SPARK_ROOT}/data/"
rsync -a "${STAGING}/scripts/spark-inventory-build" "${STAGING}/scripts/spark-inventory-build.py" "${SPARK_ROOT}/scripts/"
mkdir -p "${SPARK_ROOT}/portal/archive/v1"
cp "${STAGING}/portal/archive/v1/models.html" "${SPARK_ROOT}/portal/archive/v1/" 2>/dev/null \
  || cp "${STAGING}/portal/models.html" "${SPARK_ROOT}/portal/archive/v1/"
cp "${STAGING}/scripts/spark-download-models.sh" "${SPARK_ROOT}/scripts/" 2>/dev/null || true
chown -R "${SPARK_USER}:${SPARK_USER}" "${SPARK_ROOT}"

chmod +x "${SPARK_ROOT}/scripts/spark-inventory-build" "${SPARK_ROOT}/scripts/spark-inventory-build.py"
# CLI: install/modules/core/cli.sh → spark models inventory

echo "==> Python deps"
/opt/spark/venv/bin/pip install -q pyyaml

echo "==> Build inventory JSON"
"${SPARK_ROOT}/scripts/spark-inventory-build"

echo
echo "Done."
echo "  Portal:  http://sparky/"
echo "  Models:  http://sparky/models.html"
