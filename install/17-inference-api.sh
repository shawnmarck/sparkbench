#!/usr/bin/env bash
# Inference control API for portal + gateway (Phase 5).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
TARGET="${SPARK_ROOT}"
UNIT="/etc/systemd/system/spark-inference-api.service"

chmod +x "${TARGET}/scripts/spark-inference-api"
chmod +x "${TARGET}/scripts/spark-inference-api.py"
chmod +x "${TARGET}/scripts/spark-inference"
chmod +x "${TARGET}/scripts/spark-inference.py"
chmod +x "${TARGET}/scripts/spark-eugr"
chmod +x "${TARGET}/scripts/spark-llama"

# CLI: install/20-spark-cli.sh (single spark binary on PATH)

cat > "${UNIT}" <<EOF
[Unit]
Description=Spark portal inference control API
After=network.target docker.service

[Service]
Type=simple
User=${SPARK_USER}
Group=${SPARK_USER}
WorkingDirectory=${TARGET}
ExecStart=${TARGET}/scripts/spark-inference-api --serve
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable spark-inference-api.service
# Dev/manual runs can leave :8767 occupied — free it before systemd start.
fuser -k 8767/tcp 2>/dev/null || true
sleep 1
systemctl restart spark-inference-api.service

write_nginx_portal_site

sleep 1
curl -fsS "http://127.0.0.1/api/inference/status" >/dev/null
echo "OK: inference API at http://sparky/api/inference/status"

bash "${SCRIPT_DIR}/18-inference-api-watch.sh"
bash "${SCRIPT_DIR}/20-spark-cli.sh"