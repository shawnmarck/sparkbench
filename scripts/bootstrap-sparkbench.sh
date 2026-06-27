#!/usr/bin/env bash
# One-shot SparkBench bootstrap: clone (if needed) + spark-install quickstart.
# Usage: curl -fsSL https://raw.githubusercontent.com/shawnmarck/sparkbench/main/scripts/bootstrap-sparkbench.sh | sudo bash
set -euo pipefail

SPARK_ROOT="${SPARK_ROOT:-/opt/spark}"
REPO="${SPARKBENCH_REPO:-https://github.com/shawnmarck/sparkbench.git}"
REF="${SPARKBENCH_REF:-main}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "bootstrap-sparkbench: run with sudo (curl ... | sudo bash)" >&2
  exit 1
fi

REAL_USER="${SUDO_USER:-${SPARK_USER:-spark}}"
export SPARK_USER="$REAL_USER"
export SPARK_HOST="${SPARK_HOST:-$(sudo -u "$REAL_USER" hostname -s 2>/dev/null || hostname -s)}"

if [[ ! -d "${SPARK_ROOT}/.git" ]]; then
  echo "==> cloning ${REPO} -> ${SPARK_ROOT}"
  mkdir -p "$(dirname "${SPARK_ROOT}")"
  git clone "${REPO}" "${SPARK_ROOT}"
  chown -R "${REAL_USER}:$(id -gn "${REAL_USER}" 2>/dev/null || echo "${REAL_USER}")" "${SPARK_ROOT}"
fi

cd "${SPARK_ROOT}"
if [[ "${REF}" != "main" && "${REF}" != "master" ]]; then
  git fetch --tags origin 2>/dev/null || git fetch origin
  git checkout "${REF}"
fi

bash install/spark-install quickstart

echo ""
echo "OK: SparkBench core is up — http://${SPARK_HOST}/"
echo ""
echo "Next (one GPU engine at a time):"
echo "  sudo bash install/spark-install engine eugr   # or llama | ds4"
echo "  sudo bash install/spark-install gateway"
echo ""
echo "Optional: bash scripts/sparky-protect-runtime.sh && spark hf login && spark models inventory"
