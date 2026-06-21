# Shared install helpers — source from install/*.sh (do not execute directly).
SPARK_ROOT="${SPARK_ROOT:-/opt/spark}"
SPARK_STAGING="${SPARK_STAGING:-/home/techno/spark}"
SPARK_HOST="${SPARK_HOST:-sparky}"
SPARK_LAN_IP="${SPARK_LAN_IP:-192.168.0.101}"

write_nginx_portal_site() {
  cat > /etc/nginx/sites-available/spark-portal <<NGINX
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${SPARK_HOST} ${SPARK_LAN_IP} _;

    root ${SPARK_ROOT}/portal;
    index index.html;

    location = /models.json {
        add_header Cache-Control "no-store, no-cache, must-revalidate";
        add_header Pragma "no-cache";
        try_files \$uri =404;
    }

    location /api/models/ {
        proxy_pass http://127.0.0.1:8766/api/models/;
        proxy_http_version 1.1;
        add_header Cache-Control "no-store";
    }

    location /api/shelf/ {
        proxy_pass http://127.0.0.1:8766/api/shelf/;
        proxy_http_version 1.1;
        add_header Cache-Control "no-store";
    }

    location /api/gpu {
        proxy_pass http://127.0.0.1:8765/api/gpu;
        proxy_http_version 1.1;
        add_header Cache-Control "no-store";
    }

    location /api/inference/ {
        proxy_pass http://127.0.0.1:8767/api/inference/;
        proxy_http_version 1.1;
        add_header Cache-Control "no-store";
    }

    location / {
        try_files \$uri \$uri/ =404;
    }
}
NGINX
  nginx -t
  systemctl reload nginx
}