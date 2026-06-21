#!/usr/bin/env bash
# Deploy model inventory (catalog, builder, portal page)
set -euo pipefail

STAGING="/home/techno/spark"
SPARK_ROOT="/opt/spark"

echo "==> Sync to ${SPARK_ROOT}"
mkdir -p "${SPARK_ROOT}"/{data,scripts,portal,install}
rsync -a "${STAGING}/data/" "${SPARK_ROOT}/data/"
rsync -a "${STAGING}/scripts/spark-inventory-build" "${STAGING}/scripts/spark-inventory-build.py" "${SPARK_ROOT}/scripts/"
cp "${STAGING}/portal/models.html" "${STAGING}/portal/index.html" "${SPARK_ROOT}/portal/"
cp "${STAGING}/install/04-model-inventory.sh" "${SPARK_ROOT}/install/"
cp "${STAGING}/scripts/spark-download-models.sh" "${SPARK_ROOT}/scripts/" 2>/dev/null || true
chown -R techno:techno "${SPARK_ROOT}"

chmod +x "${SPARK_ROOT}/scripts/spark-inventory-build" "${SPARK_ROOT}/scripts/spark-inventory-build.py"
install -m 755 "${SPARK_ROOT}/scripts/spark-inventory-build" /usr/local/bin/spark-inventory-build

echo "==> Python deps"
/opt/spark/venv/bin/pip install -q pyyaml

echo "==> Build inventory JSON"
spark-inventory-build

echo
echo "Done."
echo "  Portal:  http://sparky/"
echo "  Models:  http://sparky/models.html"
