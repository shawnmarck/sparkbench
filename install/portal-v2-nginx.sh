#!/usr/bin/env bash
# Surgically publish Portal v2 without restarting SparkBench services.
set -euo pipefail

SPARK_ROOT="${SPARK_ROOT:-/opt/spark}"
SOURCE_DIST="${1:-${SPARK_ROOT}/portal-v2/dist}"
SOURCE_ROOT="${2:-${SPARK_ROOT}}"
SPARK_PORTAL_V2_DIST="${SPARK_PORTAL_V2_PUBLISH_DIR:-/var/www/spark-portal-v2}"

[[ "${SOURCE_DIST}" == /* && "${SOURCE_DIST}" != *$'\n'* ]] || {
  echo "portal-v2-nginx: source dist path must be absolute" >&2
  exit 2
}
[[ "${SOURCE_ROOT}" == /* && "${SOURCE_ROOT}" != *$'\n'* ]] || {
  echo "portal-v2-nginx: source root must be absolute" >&2
  exit 2
}
[[ -f "${SOURCE_DIST}/index.html" ]] || {
  echo "portal-v2-nginx: missing ${SOURCE_DIST}/index.html" >&2
  exit 2
}
[[ -f "${SOURCE_ROOT}/install/common.sh" ]] || {
  echo "portal-v2-nginx: missing ${SOURCE_ROOT}/install/common.sh" >&2
  exit 2
}

install -d -m 0755 "${SPARK_PORTAL_V2_DIST}"
rsync -a --delete "${SOURCE_DIST}/" "${SPARK_PORTAL_V2_DIST}/"
chmod -R a+rX "${SPARK_PORTAL_V2_DIST}"

export SPARK_ROOT SPARK_PORTAL_V2_DIST
# shellcheck source=common.sh
source "${SOURCE_ROOT}/install/common.sh"
write_nginx_portal_site

echo "OK: Portal v1 at / and Portal v2 at /v2/"
