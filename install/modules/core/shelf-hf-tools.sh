#!/usr/bin/env bash
# Deploy updated shelf push + HF login helpers.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"

echo "==> Sync scripts from staging"
STAGING="${SPARK_STAGING}"
rsync -a "${STAGING}/scripts/" "${SPARK_ROOT}/scripts/"
rsync -a "${STAGING}/docs/" "${SPARK_ROOT}/docs/"
chown -R "${SPARK_USER}:${SPARK_USER}" "${SPARK_ROOT}/scripts" "${SPARK_ROOT}/docs"

mkdir -p "${SPARK_ROOT}/run" "${SPARK_ROOT}/logs"
chown "${SPARK_USER}:${SPARK_USER}" "${SPARK_ROOT}/run" "${SPARK_ROOT}/logs"

echo "==> Install CLI tools"
# CLI: install/20-spark-cli.sh → spark shelf / spark hf
cat >/usr/local/bin/hf <<'EOF'
#!/usr/bin/env bash
exec /opt/spark/venv/bin/hf "$@"
EOF
chmod 755 /usr/local/bin/hf

echo "Done. Try: spark shelf push --help | spark hf login --whoami"
