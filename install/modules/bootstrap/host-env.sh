#!/usr/bin/env bash
# Install /etc/spark/host.env from example when missing (host identity, not secrets).
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"

mkdir -p /etc/spark
if [[ -f /etc/spark/host.env ]]; then
  echo "OK: /etc/spark/host.env already exists"
  exit 0
fi

install -m 644 "${INSTALL_DIR}/host.env.example" /etc/spark/host.env
echo "Created /etc/spark/host.env from install/host.env.example"
echo "Edit SPARK_HOST, SPARK_LAN_IP, SPARK_USER before re-running nginx install modules"
