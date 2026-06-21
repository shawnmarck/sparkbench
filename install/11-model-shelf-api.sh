#!/usr/bin/env bash
# Shelf transfer API for model inventory (fetch/push per model from portal).
set -euo pipefail

TARGET="/opt/spark"
UNIT="/etc/systemd/system/spark-shelf-api.service"

chmod +x "${TARGET}/scripts/spark-shelf-api"
chmod +x "${TARGET}/scripts/spark-shelf-pull"
chmod +x "${TARGET}/scripts/spark-shelf-push"
chmod +x "${TARGET}/scripts/spark-local-rm"
chmod +x "${TARGET}/scripts/spark-model-verify"
chmod +x "${TARGET}/scripts/spark-removal-purge" 2>/dev/null || true

cat > "${UNIT}" <<EOF
[Unit]
Description=Spark portal shelf transfer API
After=network.target

[Service]
Type=simple
ExecStart=${TARGET}/scripts/spark-shelf-api --serve
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable spark-shelf-api.service
systemctl restart spark-shelf-api.service

NGINX_SITE="/etc/nginx/sites-available/spark-portal"
if ! grep -q 'location /api/shelf' "${NGINX_SITE}"; then
  sed -i '/location \/api\/gpu {/i\
    location /api/shelf/ {\
        proxy_pass http://127.0.0.1:8766/api/shelf/;\
        proxy_http_version 1.1;\
        add_header Cache-Control "no-store";\
    }\
' "${NGINX_SITE}"
fi

if ! grep -q 'location /api/models' "${NGINX_SITE}"; then
  sed -i '/location \/api\/gpu {/i\
    location /api/models/ {\
        proxy_pass http://127.0.0.1:8766/api/models/;\
        proxy_http_version 1.1;\
        add_header Cache-Control "no-store";\
    }\
' "${NGINX_SITE}"
fi

nginx -t
systemctl reload nginx

"${TARGET}/scripts/spark-inventory-build" || "${TARGET}/venv/bin/python" "${TARGET}/scripts/spark-inventory-build.py"

sleep 1
curl -fsS "http://127.0.0.1/api/shelf/status" >/dev/null
echo "OK: shelf API at http://sparky/api/shelf/status"