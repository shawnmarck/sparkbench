#!/usr/bin/env bash
# Auto-refresh model inventory: systemd timer + inotify + nginx no-cache
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

echo "==> Sync portal + scripts"
cp "${STAGING}/portal/models.html" "${SPARK_ROOT}/portal/"
cp "${STAGING}/scripts/spark-inventory-refresh.sh" "${STAGING}/scripts/spark-inventory-watch.sh" "${SPARK_ROOT}/scripts/"
chmod +x "${SPARK_ROOT}/scripts/spark-inventory-refresh.sh" "${SPARK_ROOT}/scripts/spark-inventory-watch.sh"


echo "==> Runtime dir + CLI"
mkdir -p "${SPARK_ROOT}/run"
chmod 1777 "${SPARK_ROOT}/run"
# CLI: install/20-spark-cli.sh → spark models inventory

echo "==> nginx: portal + API proxies (via common.sh)"
write_nginx_portal_site

echo "==> Install inotify-tools (optional watcher)"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq inotify-tools

echo "==> systemd: periodic refresh (every 2 min)"
cat > /etc/systemd/system/spark-inventory-refresh.service <<'UNIT'
[Unit]
Description=Rebuild Spark model inventory JSON
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/spark/scripts/spark-inventory-refresh.sh
Nice=10
IOSchedulingClass=idle
UNIT

cat > /etc/systemd/system/spark-inventory-refresh.timer <<'TIMER'
[Unit]
Description=Refresh Spark model inventory every 2 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=2min
AccuracySec=30s
Persistent=true

[Install]
WantedBy=timers.target
TIMER

echo "==> systemd: inotify watcher (debounced on /models changes)"
cat > /etc/systemd/system/spark-inventory-watch.service <<'WATCH'
[Unit]
Description=Watch /models and rebuild inventory (debounced)
After=network.target

[Service]
Type=simple
Restart=always
RestartSec=5
ExecStart=/opt/spark/scripts/spark-inventory-watch.sh
Nice=10
IOSchedulingClass=idle

[Install]
WantedBy=multi-user.target
WATCH

systemctl daemon-reload
systemctl enable --now spark-inventory-refresh.timer
systemctl enable --now spark-inventory-watch.service

spark-inventory-refresh || true

echo
echo "Done."
echo "  Timer:  spark-inventory-refresh.timer (every 2 min)"
echo "  Watch:  spark-inventory-watch.service (/models inotify)"
echo "  Page:   http://sparky/models.html (polls JSON every 30s)"
