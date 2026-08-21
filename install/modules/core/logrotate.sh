#!/usr/bin/env bash
# Cap /opt/spark/logs so one-shot and engine file logs cannot grow forever.
# copytruncate: llama/ds4 keep an open fd across rotate.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"

CONF="/etc/logrotate.d/spark"
cat > "${CONF}" <<EOF
${SPARK_ROOT}/logs/*.log {
    weekly
    rotate 4
    maxsize 20M
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
    su ${SPARK_USER} ${SPARK_USER}
}
EOF
chmod 644 "${CONF}"
echo "OK: logrotate ${CONF} (weekly / 20M / 4 copies)"
