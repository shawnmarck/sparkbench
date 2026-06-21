#!/usr/bin/env bash
# Live GPU + memory widgets on the Spark portal (port 80).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
TARGET="${SPARK_ROOT}"
UNIT="/etc/systemd/system/spark-gpu-metrics.service"

chmod +x "${TARGET}/scripts/spark-gpu-metrics"

cat > "${UNIT}" <<EOF
[Unit]
Description=Spark portal GPU metrics API
After=network.target

[Service]
Type=simple
ExecStart=${TARGET}/scripts/spark-gpu-metrics --serve
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable spark-gpu-metrics.service
systemctl restart spark-gpu-metrics.service

write_nginx_portal_site

sleep 1
curl -fsS "http://127.0.0.1/api/gpu" >/dev/null
echo "OK: GPU metrics API at http://sparky/api/gpu"