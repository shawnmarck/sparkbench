#!/usr/bin/env bash
# Surgically install Portal v2 support APIs without touching inference engines.
set -euo pipefail

SPARK_ROOT="${SPARK_ROOT:-/opt/spark}"
SOURCE_ROOT="${1:-${SPARK_ROOT}}"
SPARK_PORTAL_V2_DIST="${SPARK_PORTAL_V2_PUBLISH_DIR:-/var/www/spark-portal-v2}"

[[ "${SOURCE_ROOT}" == /* && "${SOURCE_ROOT}" != *$'\n'* ]] || {
  echo "portal-v2-services: source root must be absolute" >&2
  exit 2
}
for source_file in \
  scripts/spark-install-api.py \
  scripts/spark-operator-api.py \
  scripts/spark-operator-mcp.py \
  install/modules/core/install-api.sh \
  install/modules/core/operator-api.sh; do
  [[ -f "${SOURCE_ROOT}/${source_file}" ]] || {
    echo "portal-v2-services: missing ${SOURCE_ROOT}/${source_file}" >&2
    exit 2
  }
done

install -d -m 0755 "${SPARK_ROOT}/scripts"
install -m 0755 "${SOURCE_ROOT}/scripts/spark-install-api.py" "${SPARK_ROOT}/scripts/spark-install-api.py"
install -m 0755 "${SOURCE_ROOT}/scripts/spark-operator-api.py" "${SPARK_ROOT}/scripts/spark-operator-api.py"
install -m 0755 "${SOURCE_ROOT}/scripts/spark-operator-mcp.py" "${SPARK_ROOT}/scripts/spark-operator-mcp.py"

export SPARK_ROOT SPARK_PORTAL_V2_DIST
bash "${SOURCE_ROOT}/install/modules/core/install-api.sh"
bash "${SOURCE_ROOT}/install/modules/core/operator-api.sh"

echo "OK: Portal v2 support APIs installed without restarting inference"
