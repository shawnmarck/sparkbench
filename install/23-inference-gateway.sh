#!/usr/bin/env bash
# Unified inference gateway (:9000/v1) — stable front door for Hermes, Open WebUI, harnesses.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
TARGET="${SPARK_ROOT}"
UNIT="/etc/systemd/system/spark-inference-gateway.service"

chmod +x "${TARGET}/scripts/spark-inference-gateway"
chmod +x "${TARGET}/scripts/spark-inference-gateway.py"

cat > "${UNIT}" <<UNITEOF
[Unit]
Description=Spark Inference Gateway (unified :9000/v1)
After=network.target spark-inference-api.service
Wants=spark-inference-api.service

[Service]
Type=simple
User=${SPARK_USER}
Group=${SPARK_USER}
WorkingDirectory=${TARGET}
ExecStart=${TARGET}/scripts/spark-inference-gateway --serve --port 9000
Restart=on-failure
RestartSec=3
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable spark-inference-gateway.service

# Manual dev runs can leave :9000 occupied — free it before systemd start.
fuser -k 9000/tcp 2>/dev/null || true
sleep 1
systemctl restart spark-inference-gateway.service

sleep 1
curl -fsS "http://127.0.0.1:9000/v1/models" >/dev/null
echo "OK: inference gateway at http://sparky:9000/v1"
