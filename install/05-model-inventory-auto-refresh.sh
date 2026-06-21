#!/usr/bin/env bash
# Auto-refresh model inventory: systemd timer + inotify + nginx no-cache
set -euo pipefail

STAGING="/home/techno/spark"
SPARK_ROOT="/opt/spark"

echo "==> Sync portal + scripts"
cp "${STAGING}/portal/models.html" "${SPARK_ROOT}/portal/"
cp "${STAGING}/scripts/spark-inventory-refresh.sh" "${STAGING}/scripts/spark-inventory-watch.sh" "${SPARK_ROOT}/scripts/"
chmod +x "${SPARK_ROOT}/scripts/spark-inventory-refresh.sh" "${SPARK_ROOT}/scripts/spark-inventory-watch.sh"


echo "==> Runtime dir + CLI"
mkdir -p "${SPARK_ROOT}/run"
chmod 1777 "${SPARK_ROOT}/run"
install -m 755 "${SPARK_ROOT}/scripts/spark-inventory-refresh.sh" /usr/local/bin/spark-inventory-refresh
install -m 755 "${STAGING}/scripts/spark-inventory-build" /usr/local/bin/spark-inventory-build

echo "==> nginx: no-cache for models.json"
cat > /etc/nginx/sites-available/spark-portal <<'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name sparky 192.168.0.101 _;

    root /opt/spark/portal;
    index index.html;

    location = /models.json {
        add_header Cache-Control "no-store, no-cache, must-revalidate";
        add_header Pragma "no-cache";
        try_files $uri =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
NGINX
nginx -t
systemctl reload nginx

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
