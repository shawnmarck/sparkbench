#!/bin/bash
# Portal routing now lives in install/common.sh (write_nginx_portal_site).
# React app is built to portal/ root; legacy UIs live under portal/archive/.
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
# shellcheck source=common.sh
source "${ROOT}/install/common.sh"

write_nginx_portal_site
echo "nginx reloaded — portal at /, archive under /archive/, /v2/* → /"
