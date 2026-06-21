#!/usr/bin/env bash
set -euo pipefail

SPARK_ROOT="/opt/spark"
OPS="/ops/vllm-studio"
REPO="${OPS}/repo"
FRONTEND_PORT=3080
CTRL_PORT=8080
BUN="/home/techno/.bun/bin/bun"

install -m 755 "${SPARK_ROOT}/scripts/spark-vllm-studio" /usr/local/bin/spark-vllm-studio

cat >/etc/systemd/system/spark-vllm-studio-controller.service <<EOF
[Unit]
Description=vLLM Studio controller (Spark bake-off)
After=network.target docker.service

[Service]
Type=simple
User=techno
Group=techno
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
User=techno
Group=techno
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
sleep 3

spark-vllm-studio status || true
echo "vLLM Studio: http://sparky:${FRONTEND_PORT}"
