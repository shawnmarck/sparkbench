#!/usr/bin/env bash
# Live GPU + memory widgets on the Spark portal (port 80).
set -euo pipefail

TARGET="/opt/spark"
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

NGINX_SITE="/etc/nginx/sites-available/spark-portal"
if ! grep -q 'location /api/gpu' "${NGINX_SITE}"; then
  sed -i '/location \/ {/i\
    location /api/gpu {\
        proxy_pass http://127.0.0.1:8765/api/gpu;\
        proxy_http_version 1.1;\
        add_header Cache-Control "no-store";\
    }\
' "${NGINX_SITE}"
fi

nginx -t
systemctl reload nginx

sleep 1
curl -fsS "http://127.0.0.1/api/gpu" >/dev/null
echo "OK: GPU metrics API at http://sparky/api/gpu"