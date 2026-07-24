#!/usr/bin/env bash
# Loopback Spark Operator bridge for Portal v2.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
TARGET="${SPARK_ROOT}"
UNIT="/etc/systemd/system/spark-operator-api.service"

chmod +x "${TARGET}/scripts/spark-operator-api.py"
chmod +x "${TARGET}/scripts/spark-operator-mcp.py"
install -d -m 0770 -o "${SPARK_USER}" -g "${SPARK_USER}" "${TARGET}/run/operator"

cat > "${UNIT}" <<EOF
[Unit]
Description=SparkBench Hermes operator bridge
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
WorkingDirectory=${TARGET}
Environment=SPARK_ROOT=${TARGET}
Environment=SPARK_HOST=${SPARK_HOST}
Environment=SPARK_OPERATOR_API_BIND=127.0.0.1
Environment=SPARK_OPERATOR_API_PORT=8772
Environment=SPARK_OPERATOR_SHARED_UID=$(id -u "${SPARK_USER}")
Environment=SPARK_OPERATOR_SHARED_GID=$(id -g "${SPARK_USER}")
ExecStart=/usr/bin/python3 ${TARGET}/scripts/spark-operator-api.py
Restart=on-failure
RestartSec=2
UMask=0077
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable spark-operator-api.service
systemctl restart spark-operator-api.service

maybe_write_nginx_portal_site

sleep 1
curl -fsS "http://127.0.0.1:8772/api/operator/status" >/dev/null
if ! install_batch_active; then
  curl -fsS "http://127.0.0.1/api/operator/status" >/dev/null
fi
echo "OK: operator API at http://${SPARK_HOST}/api/operator/status"
