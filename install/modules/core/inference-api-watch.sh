#!/usr/bin/env bash
# Restart spark-inference-api when inference scripts change (no manual systemctl).
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
TARGET="${SPARK_ROOT}"

PATH_UNIT="/etc/systemd/system/spark-inference-api-watch.path"
SVC_UNIT="/etc/systemd/system/spark-inference-api-watch.service"

cat > "${PATH_UNIT}" <<EOF
[Unit]
Description=Watch Spark inference API scripts for changes
After=spark-inference-api.service

[Path]
PathModified=${TARGET}/scripts/spark-inference-api.py
PathModified=${TARGET}/scripts/spark-inference.py
Unit=spark-inference-api-watch.service

[Install]
WantedBy=multi-user.target
EOF

cat > "${SVC_UNIT}" <<EOF
[Unit]
Description=Restart Spark inference API after script change
After=spark-inference-api.service

[Service]
Type=oneshot
ExecStart=/bin/systemctl restart spark-inference-api.service
EOF

systemctl daemon-reload
systemctl enable spark-inference-api-watch.path
systemctl restart spark-inference-api-watch.path
systemctl restart spark-inference-api.service

echo "OK: inference API auto-reload on changes to:"
echo "  ${TARGET}/scripts/spark-inference-api.py"
echo "  ${TARGET}/scripts/spark-inference.py"