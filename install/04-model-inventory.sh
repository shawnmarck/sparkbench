#!/usr/bin/env bash
# Deploy model inventory (catalog, builder, portal page)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
STAGING="${SPARK_STAGING}"

echo "==> Sync to ${SPARK_ROOT}"
mkdir -p "${SPARK_ROOT}"/{data,scripts,portal,install}
rsync -a "${STAGING}/data/" "${SPARK_ROOT}/data/"
rsync -a "${STAGING}/scripts/spark-inventory-build" "${STAGING}/scripts/spark-inventory-build.py" "${SPARK_ROOT}/scripts/"
cp "${STAGING}/portal/models.html" "${STAGING}/portal/index.html" "${SPARK_ROOT}/portal/"
cp "${STAGING}/install/04-model-inventory.sh" "${SPARK_ROOT}/install/"
cp "${STAGING}/scripts/spark-download-models.sh" "${SPARK_ROOT}/scripts/" 2>/dev/null || true
chown -R "${SPARK_USER}:${SPARK_USER}" "${SPARK_ROOT}"

chmod +x "${SPARK_ROOT}/scripts/spark-inventory-build" "${SPARK_ROOT}/scripts/spark-inventory-build.py"
# CLI: install/20-spark-cli.sh → spark models inventory

echo "==> Python deps"
/opt/spark/venv/bin/pip install -q pyyaml

echo "==> Build inventory JSON"
"${SPARK_ROOT}/scripts/spark-inventory-build"

echo
echo "Done."
echo "  Portal:  http://sparky/"
echo "  Models:  http://sparky/models.html"
