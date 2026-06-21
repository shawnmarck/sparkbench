#!/usr/bin/env bash
# Spark home lab — Netdata + static portal (idempotent)
set -euo pipefail

STAGING="/home/techno/spark"
TARGET="/opt/spark"
HOST_IP="192.168.0.101"

echo "==> Creating ${TARGET} layout"
mkdir -p "${TARGET}"/{portal,docs,install,services}
rsync -a "${STAGING}/portal/" "${TARGET}/portal/"
rsync -a "${STAGING}/docs/" "${TARGET}/docs/"
rsync -a "${STAGING}/install/" "${TARGET}/install/"
if [ -f "${STAGING}/README.md" ]; then
  rsync -a "${STAGING}/README.md" "${TARGET}/README.md"
elif [ -f "${TARGET}/README.md" ] && [ ! -L "${TARGET}/README.md" ]; then
  : # keep existing real root README
else
  rm -f "${TARGET}/README.md"
  cp "${TARGET}/docs/README.md" "${TARGET}/README.md"
fi
chown -R techno:techno "${TARGET}"

echo "==> Installing Netdata (if missing)"
if ! command -v netdata >/dev/null 2>&1; then
  KICKSTART="/tmp/netdata-kickstart-spark-$$.sh"; rm -f "$KICKSTART"; curl -fsSL https://get.netdata.cloud/kickstart.sh -o "$KICKSTART"
  sh "$KICKSTART" --non-interactive --stable-channel --disable-telemetry
fi
systemctl enable --now netdata

echo "==> Ensuring Netdata listens on LAN"
NETDATA_CONF="/etc/netdata/netdata.conf"
if [ -f "${NETDATA_CONF}" ]; then
  if grep -q "^[[:space:]]*bind to[[:space:]]*=" "${NETDATA_CONF}"; then
    sed -i "s/^[[:space:]]*bind to[[:space:]]*=.*/    bind to = 0.0.0.0/" "${NETDATA_CONF}" || true
  else
    sed -i "/^\[web\]/a\    bind to = 0.0.0.0" "${NETDATA_CONF}" || true
  fi
fi
systemctl restart netdata

echo "==> Installing nginx (if missing)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx rsync

echo "==> Configuring nginx portal"
cat > /etc/nginx/sites-available/spark-portal <<NGINX
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name sparky ${HOST_IP} _;

    root ${TARGET}/portal;
    index index.html;

    location / {
        try_files \$uri \$uri/ =404;
    }
}
NGINX

ln -sfn /etc/nginx/sites-available/spark-portal /etc/nginx/sites-enabled/spark-portal
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "==> Firewall (if ufw active)"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp comment "spark portal"
  ufw allow 19999/tcp comment "netdata"
fi

echo "==> Health checks"
sleep 2
curl -fsS "http://127.0.0.1:19999/api/v1/info" >/dev/null && echo "Netdata: OK"
curl -fsS "http://127.0.0.1/" | grep -q "Sparky" && echo "Portal: OK"

echo
echo "Done."
echo "  Portal:  http://sparky/  (http://${HOST_IP}/)"
echo "  Netdata: http://sparky:19999  (http://${HOST_IP}:19999)"
