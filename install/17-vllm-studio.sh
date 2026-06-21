#!/usr/bin/env bash
set -euo pipefail

SPARK_ROOT="/opt/spark"
OPS="/ops/vllm-studio"
REPO="${OPS}/repo"
FRONTEND_PORT=3080
CTRL_PORT=8080
BUN="/home/techno/.bun/bin/bun"
TECHNO="techno"

echo "==> Stop Rookery (GB10 NVML gap — disqualified for bake-off)"
systemctl stop spark-rookery.service 2>/dev/null || true
systemctl disable spark-rookery.service 2>/dev/null || true

echo "==> Free GPU ports (spark-llama / rookery profiles)"
sudo -u "$TECHNO" spark-llama down 2>/dev/null || true
sudo -u "$TECHNO" rookery stop 2>/dev/null || true

echo "==> Install bun (user techno)"
if [[ ! -x "$BUN" ]]; then
  sudo -u "$TECHNO" bash -lc 'curl -fsSL https://bun.sh/install | bash'
fi
[[ -x "$BUN" ]] || { echo "bun missing at $BUN"; exit 1; }

echo "==> Install Node 22 (NodeSource — Next.js 16 / undici 8)"
if ! node --version 2>/dev/null | grep -qE '^v22'; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -qq nodejs
fi
node --version
npm --version

echo "==> Clone vLLM Studio"
mkdir -p "$OPS"
chown -R "$TECHNO:$TECHNO" "$OPS"
if [[ ! -d "$REPO/.git" ]]; then
  sudo -u "$TECHNO" git clone --depth 1 https://github.com/sybil-solutions/vllm-studio.git "$REPO"
fi

cat >"${OPS}/.env.local" <<EOF
VLLM_STUDIO_HOST=0.0.0.0
VLLM_STUDIO_PORT=${CTRL_PORT}
VLLM_STUDIO_ALLOW_UNAUTHENTICATED=true
VLLM_STUDIO_MODELS_DIR=/models
VLLM_STUDIO_DATA_DIR=${OPS}/data
VLLM_STUDIO_INFERENCE_PORT=8000
VLLM_STUDIO_LLAMA_BIN=/opt/spark/bin/llama-server
VLLM_STUDIO_CORS_ORIGINS=http://sparky:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT},http://localhost:${FRONTEND_PORT}
EOF
chown "$TECHNO:$TECHNO" "${OPS}/.env.local"

echo "==> Controller deps"
sudo -u "$TECHNO" bash -lc "
  cd '${REPO}/controller'
  '${BUN}' install
"

echo "==> Frontend build (may take several minutes)"
sudo -u "$TECHNO" bash -lc "
  cd '${REPO}/frontend'
  npm ci 2>/dev/null || npm install
  npm run build
"

install -m 755 "${SPARK_ROOT}/scripts/spark-vllm-studio" /usr/local/bin/spark-vllm-studio

cat >/etc/systemd/system/spark-vllm-studio-controller.service <<EOF
[Unit]
Description=vLLM Studio controller (Spark bake-off)
After=network.target docker.service

[Service]
Type=simple
User=${TECHNO}
Group=${TECHNO}
WorkingDirectory=${REPO}/controller
EnvironmentFile=${OPS}/.env.local
ExecStart=${BUN} src/main.ts
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/spark-vllm-studio-frontend.service <<EOF
[Unit]
Description=vLLM Studio frontend (Spark bake-off)
After=spark-vllm-studio-controller.service
Requires=spark-vllm-studio-controller.service

[Service]
Type=simple
User=${TECHNO}
Group=${TECHNO}
WorkingDirectory=${REPO}/frontend
Environment=PORT=${FRONTEND_PORT}
Environment=HOSTNAME=0.0.0.0
Environment=NEXT_PUBLIC_API_URL=http://127.0.0.1:${CTRL_PORT}
ExecStart=/usr/bin/npm run start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable spark-vllm-studio-controller.service spark-vllm-studio-frontend.service
systemctl restart spark-vllm-studio-controller.service
sleep 5
systemctl restart spark-vllm-studio-frontend.service

echo
echo "vLLM Studio: http://sparky:${FRONTEND_PORT}"
echo "Controller:  http://sparky:${CTRL_PORT}"
echo "Models dir:  /models"
echo "llama bin:   /opt/spark/bin/llama-server"
echo "Manage:      spark-vllm-studio status"
