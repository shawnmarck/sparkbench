#!/usr/bin/env bash
# Nightly purge of models flagged removal_pending on Spark local disk.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
TARGET="${SPARK_ROOT}"
chmod +x "${TARGET}/scripts/spark-removal-purge"

UNIT="/etc/systemd/system/spark-removal-purge.service"
TIMER="/etc/systemd/system/spark-removal-purge.timer"

cat > "${UNIT}" <<EOF
[Unit]
Description=Purge Spark models queued for local removal

[Service]
Type=oneshot
ExecStart=${TARGET}/scripts/spark-removal-purge
EOF

cat > "${TIMER}" <<EOF
[Unit]
Description=Nightly Spark model removal purge (03:00)

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable spark-removal-purge.timer
systemctl start spark-removal-purge.timer

echo "OK: spark-removal-purge.timer enabled (daily 03:00)"
systemctl list-timers spark-removal-purge.timer --no-pager