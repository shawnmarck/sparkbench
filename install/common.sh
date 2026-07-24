# Shared install helpers — source from install/modules/*/*.sh (do not execute directly).
# SPARK_INSTALL_BATCH=1 defers nginx until spark-install finalizes a bundled run.
#
# Host identity (optional): /etc/spark/host.env or $SPARK_ROOT/host.env (gitignored).
# Copy install/host.env.example. Secrets stay in /etc/spark/smb-credentials-models.
_SPARK_ROOT="${SPARK_ROOT:-/opt/spark}"
for _host_env in /etc/spark/host.env "${_SPARK_ROOT}/host.env"; do
  if [[ -f "$_host_env" ]]; then
    # shellcheck disable=SC1090
    set -a
    # shellcheck source=/dev/null
    source "$_host_env"
    set +a
    break
  fi
done
unset _host_env _SPARK_ROOT

SPARK_ROOT="${SPARK_ROOT:-/opt/spark}"
if [[ -z "${SPARK_USER:-}" ]]; then
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != root ]]; then
    SPARK_USER="${SUDO_USER}"
  else
    SPARK_USER="${SPARK_RUN_USER:-spark}"
  fi
fi
SPARK_STAGING="${SPARK_STAGING:-${SPARK_ROOT}}"
SPARK_HOST="${SPARK_HOST:-sparky}"
# Set SPARK_LAN_IP to your Spark's LAN IP if you want nginx to also serve on
# that address (server_name). Leave blank to serve on hostname + default_server.
SPARK_LAN_IP="${SPARK_LAN_IP:-}"
SPARK_SHELF_MOUNT="${SPARK_SHELF_MOUNT:-/mnt/model-shelf}"

shelf_mounted() {
  mountpoint -q "${SPARK_SHELF_MOUNT}" 2>/dev/null
}

install_batch_active() {
  [[ "${SPARK_INSTALL_BATCH:-}" == "1" ]]
}

# Defer nginx rewrite when spark-install batches modules (finalize once at end).
maybe_write_nginx_portal_site() {
  if install_batch_active; then
    return 0
  fi
  write_nginx_portal_site
}

write_nginx_portal_site() {
  local portal_root="${SPARK_ROOT}/portal"

  cat > /etc/nginx/sites-available/spark-portal <<NGINX
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${SPARK_HOST} ${SPARK_LAN_IP} _;

    root ${portal_root};
    index index.html;

    location = /models.json {
        alias ${SPARK_ROOT}/portal/models.json;
        add_header Cache-Control "no-store, no-cache, must-revalidate";
        add_header Pragma "no-cache";
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
        proxy_read_timeout 300s;
        proxy_connect_timeout 10s;
        add_header Cache-Control "no-store";
    }

    location /api/hf/ {
        proxy_pass http://127.0.0.1:8768/api/hf/;
        proxy_http_version 1.1;
        proxy_read_timeout 300s;
        proxy_connect_timeout 10s;
        add_header Cache-Control "no-store";
    }

    location /api/activity {
        proxy_pass http://127.0.0.1:8769;
        proxy_http_version 1.1;
        add_header Cache-Control "no-store";
    }

    location /api/benchmaster/ {
        proxy_pass http://127.0.0.1:8770/api/benchmaster/;
        proxy_http_version 1.1;
        proxy_read_timeout 3600s;
        proxy_connect_timeout 10s;
        proxy_buffering off;
        add_header Cache-Control "no-store";
    }

    location /api/install/ {
        proxy_pass http://127.0.0.1:8771/api/install/;
        proxy_http_version 1.1;
        proxy_read_timeout 3600s;
        proxy_connect_timeout 10s;
        proxy_buffering off;
        add_header Cache-Control "no-store";
    }

    location /api/operator/ {
        proxy_pass http://127.0.0.1:8772/api/operator/;
        proxy_http_version 1.1;
        proxy_read_timeout 1200s;
        proxy_connect_timeout 10s;
        proxy_buffering off;
        add_header X-Accel-Buffering "no";
        add_header Cache-Control "no-store";
    }

    location = /v2 {
        return 308 /v2/;
    }

    location ^~ /v2/ {
        alias ${SPARK_ROOT}/portal-v2/dist/;
        try_files \$uri \$uri/ /v2/index.html;
        add_header Cache-Control "no-store";
    }

    location ~* \.css$ {
        add_header Cache-Control "public, max-age=86400";
        try_files \$uri =404;
    }

    location ~* \.js$ {
        add_header Cache-Control "no-store, no-cache, must-revalidate";
        add_header Pragma "no-cache";
        try_files \$uri =404;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINX
  nginx -t
  systemctl reload nginx
}