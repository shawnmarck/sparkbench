#!/usr/bin/env bash
# Deploy updated shelf push + HF login helpers.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

echo "==> Sync scripts from staging"
rsync -a "${STAGING}/scripts/" "${SPARK_ROOT}/scripts/"
rsync -a "${STAGING}/docs/" "${SPARK_ROOT}/docs/"
chown -R techno:techno "${SPARK_ROOT}/scripts" "${SPARK_ROOT}/docs"

mkdir -p "${SPARK_ROOT}/run" "${SPARK_ROOT}/logs"
chown techno:techno "${SPARK_ROOT}/run" "${SPARK_ROOT}/logs"

echo "==> Install CLI tools"
install -m 755 "${SPARK_ROOT}/scripts/spark-shelf-push" /usr/local/bin/spark-shelf-push
install -m 755 "${SPARK_ROOT}/scripts/spark-shelf-pull" /usr/local/bin/spark-shelf-pull
install -m 755 "${SPARK_ROOT}/scripts/spark-hf-login" /usr/local/bin/spark-hf-login
cat >/usr/local/bin/hf <<'EOF'
#!/usr/bin/env bash
exec /opt/spark/venv/bin/hf "$@"
EOF
chmod 755 /usr/local/bin/hf

echo "Done. Try: spark-shelf-push --help | spark-hf-login --whoami"
