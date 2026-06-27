#!/usr/bin/env bash
# Client activity API (:8769) — reads gateway JSONL, serves /api/activity for portal.
# Sensitivity: LAN-only trust model. No auth; exposes per-client activity data.
set -euo pipefail
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
TARGET="${SPARK_ROOT}"
UNIT="/etc/systemd/system/spark-client-activity.service"

chmod +x "${TARGET}/scripts/spark-client-activity.py"

cat > "${UNIT}" <<UNITEOF
[Unit]
Description=Spark Client Activity API (:8769)
After=network.target spark-inference-gateway.service
Wants=spark-inference-gateway.service

[Service]
Type=simple
User=${SPARK_USER}
Group=${SPARK_USER}
WorkingDirectory=${TARGET}
ExecStart=${TARGET}/scripts/spark-client-activity.py --serve --port 8769
Restart=on-failure
RestartSec=3
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable spark-client-activity.service

# Free port if manually occupied
fuser -k 8769/tcp 2>/dev/null || true
sleep 1
systemctl restart spark-client-activity.service

# Regenerate nginx config (common.sh includes /api/activity location)
maybe_write_nginx_portal_site

sleep 1
curl -fsS "http://127.0.0.1:8769/api/activity" >/dev/null
if ! install_batch_active; then
  curl -fsS "http://127.0.0.1/api/activity?window=1h" >/dev/null
fi
echo "OK: client activity API at http://sparky/api/activity"