#!/usr/bin/env bash
# Benchmaster control API for portal + remote orchestrator.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
TARGET="${SPARK_ROOT}"
UNIT="/etc/systemd/system/spark-benchmaster-api.service"

chmod +x "${TARGET}/scripts/spark-benchmaster-api"
chmod +x "${TARGET}/scripts/spark-benchmaster-api.py"
chmod +x "${TARGET}/scripts/spark-benchmaster.py"

mkdir -p "${TARGET}/run/benchmaster/runs"
mkdir -p "${TARGET}/logs"
chown -R "${SPARK_USER}:${SPARK_USER}" "${TARGET}/run/benchmaster" "${TARGET}/logs" 2>/dev/null || true

cat > "${UNIT}" <<EOF
[Unit]
Description=Spark Benchmaster control API
After=network.target docker.service

[Service]
Type=simple
User=${SPARK_USER}
Group=${SPARK_USER}
WorkingDirectory=${TARGET}
ExecStart=${TARGET}/scripts/spark-benchmaster-api --serve
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable spark-benchmaster-api.service
fuser -k 8770/tcp 2>/dev/null || true
sleep 1
systemctl restart spark-benchmaster-api.service

maybe_write_nginx_portal_site

sleep 1
curl -fsS "http://127.0.0.1:8770/api/benchmaster/status" >/dev/null
if ! install_batch_active; then
  curl -fsS "http://127.0.0.1/api/benchmaster/status" >/dev/null
fi
echo "OK: benchmaster API at http://sparky/api/benchmaster/status"
