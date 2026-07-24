#!/usr/bin/env bash
# Add the SparkBench MCP overlay to an existing Hermes deployment safely.
set -euo pipefail

SPARK_ROOT="${SPARK_ROOT:-/opt/spark}"
SOURCE_ROOT="${1:-${SPARK_ROOT}}"
SPARK_PORTAL_V2_DIST="${SPARK_PORTAL_V2_PUBLISH_DIR:-/var/www/spark-portal-v2}"

[[ "${SOURCE_ROOT}" == /* && "${SOURCE_ROOT}" != *$'\n'* ]] || {
  echo "portal-v2-hermes: source root must be absolute" >&2
  exit 2
}
[[ -f "${SOURCE_ROOT}/install/modules/optional/hermes.sh" ]] || {
  echo "portal-v2-hermes: missing Hermes installer under ${SOURCE_ROOT}" >&2
  exit 2
}

export SPARK_ROOT SPARK_STAGING="${SOURCE_ROOT}" SPARK_PORTAL_V2_DIST
bash "${SOURCE_ROOT}/install/modules/optional/hermes.sh"
