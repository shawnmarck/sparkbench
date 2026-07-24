#!/usr/bin/env bash
# Privileged install agent API for portal Setup / Add-ons.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
TARGET="${SPARK_ROOT}"
UNIT="/etc/systemd/system/spark-install-api.service"
SCRIPT="${TARGET}/scripts/spark-install-api.py"

chmod +x "${SCRIPT}"

# Ensure token exists (agent creates it on first start as well).
install -d -m 0755 /etc/spark
if [[ ! -f /etc/spark/install-token ]]; then
  python3 - <<'PY'
import secrets
from pathlib import Path
p = Path("/etc/spark/install-token")
p.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8")
p.chmod(0o600)
print(f"wrote {p}")
PY
fi

cat > "${UNIT}" <<EOF
[Unit]
Description=SparkBench install agent API
After=network.target

[Service]
Type=simple
Environment=SPARK_ROOT=${TARGET}
ExecStart=/usr/bin/python3 ${SCRIPT}
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable spark-install-api.service
systemctl restart spark-install-api.service

maybe_write_nginx_portal_site

sleep 1
curl -fsS "http://127.0.0.1:8771/api/install/status" >/dev/null
if ! install_batch_active; then
  curl -fsS "http://127.0.0.1/api/install/status" >/dev/null || true
fi
echo "OK: install API at http://${SPARK_HOST}/api/install/status"
echo "    token: /etc/spark/install-token"
