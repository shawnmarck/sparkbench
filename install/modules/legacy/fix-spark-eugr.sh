#!/usr/bin/env bash
set -euo pipefail
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
cp "${SPARK_STAGING}/scripts/spark-eugr" "${SPARK_ROOT}/scripts/spark-eugr"
chmod +x "${SPARK_ROOT}/scripts/spark-eugr"
# CLI: install/20-spark-cli.sh → spark engine eugr
sudo -u "${SPARK_USER}" "${SPARK_ROOT}/scripts/spark-eugr" up
