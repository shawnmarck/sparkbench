#!/usr/bin/env bash
# Restart the :9000 gateway only. Safe on a live box (does not rewrite nginx).
set -euo pipefail
systemctl restart spark-inference-gateway.service
systemctl is-active spark-inference-gateway.service
echo "OK: spark-inference-gateway restarted"
