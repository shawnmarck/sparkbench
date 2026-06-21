#!/usr/bin/env bash
# Experimental — disqualified in docs/BAKE-OFF.md. Prefer install/17-vllm-studio.sh.
# Re-running this after vLLM Studio install may re-enable Rookery.
set -euo pipefail

SPARK_ROOT="/opt/spark"
VERSION="${ROOKERY_VERSION:-v0.1.5}"
TARGET="aarch64-unknown-linux-gnu"
URL="https://github.com/lance0/rookery/releases/download/${VERSION}/rookery-${TARGET}.tar.gz"
CONFIG="/ops/rookery/config.toml"
SERVICE="/etc/systemd/system/spark-rookery.service"

echo "==> Install rookery ${VERSION} (${TARGET})"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$URL" | tar xz -C "$TMP"
install -m 755 "$TMP/rookery" "$TMP/rookeryd" /usr/local/bin/

mkdir -p /ops/rookery
if [[ -f "${SPARK_ROOT}/data/rookery-config.toml" ]]; then
  install -m 644 "${SPARK_ROOT}/data/rookery-config.toml" "$CONFIG"
elif [[ ! -f "$CONFIG" ]]; then
  install -m 644 "${SPARK_ROOT}/data/rookery-config.toml" "$CONFIG" 2>/dev/null || true
fi
[[ -f "$CONFIG" ]] || { echo "Missing $CONFIG"; exit 1; }
chown techno:techno "$CONFIG"

cat >"$SERVICE" <<EOF
[Unit]
Description=Rookery inference orchestrator (Spark bake-off)
After=network.target docker.service

[Service]
Type=simple
User=techno
Group=techno
Environment=HF_HOME=/home/techno/.cache/huggingface
ExecStart=/usr/local/bin/rookeryd
WorkingDirectory=/ops/rookery
# rookery reads ~/.config/rookery/config.toml — symlink from /ops
ExecStartPre=/bin/mkdir -p /home/techno/.config/rookery
ExecStartPre=/bin/ln -sf ${CONFIG} /home/techno/.config/rookery/config.toml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable spark-rookery.service
systemctl restart spark-rookery.service

sleep 2
systemctl is-active spark-rookery.service
echo "Rookery: http://sparky:3131"
echo "CLI: rookery status | spark-rookery status"
