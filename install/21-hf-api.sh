#!/usr/bin/env bash
# HF Explorer API for portal (Phase 5c).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
TARGET="${SPARK_ROOT}"
UNIT="/etc/systemd/system/spark-hf-api.service"

chmod +x "${TARGET}/scripts/spark-hf-api"
chmod +x "${TARGET}/scripts/spark-hf-api.py"
chmod +x "${TARGET}/scripts/spark-hf.py"

mkdir -p "${TARGET}/data"
touch "${TARGET}/data/hf-download-queue.yaml" "${TARGET}/data/hf-explore-queue.yaml"
if [[ ! -s "${TARGET}/data/hf-download-queue.yaml" ]]; then
  printf 'items: []\n' > "${TARGET}/data/hf-download-queue.yaml"
fi
if [[ ! -s "${TARGET}/data/hf-explore-queue.yaml" ]]; then
  printf 'items: []\n' > "${TARGET}/data/hf-explore-queue.yaml"
fi

cat > "${UNIT}" <<EOF
[Unit]
Description=Spark HF Explorer API
After=network.target

[Service]
Type=simple
ExecStart=${TARGET}/scripts/spark-hf-api --serve
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable spark-hf-api.service
systemctl restart spark-hf-api.service

write_nginx_portal_site

sleep 1
curl -fsS "http://127.0.0.1:8768/api/hf/status" >/dev/null
curl -fsS "http://127.0.0.1/api/hf/status" >/dev/null
echo "OK: HF API at http://sparky/api/hf/status"