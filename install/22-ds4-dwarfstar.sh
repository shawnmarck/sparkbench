#!/usr/bin/env bash
# Build DwarfStar (ds4) for GB10 and install spark engine helpers.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
TARGET="${SPARK_ROOT}"
STAGING_VENDOR="${SPARK_STAGING}/vendor/ds4"
VENDOR="${TARGET}/vendor/ds4"
BIN_DIR="${TARGET}/bin"
PIN="${TARGET}/data/ds4-dwarfstar.yaml"

echo "==> Sync staging scripts/docs/data"
rsync -a "${SPARK_STAGING}/scripts/" "${TARGET}/scripts/" 2>/dev/null || true
rsync -a "${SPARK_STAGING}/docs/" "${TARGET}/docs/" 2>/dev/null || true
rsync -a "${SPARK_STAGING}/data/ds4-dwarfstar.yaml" "${TARGET}/data/" 2>/dev/null || true
rsync -a "${SPARK_STAGING}/portal/" "${TARGET}/portal/" 2>/dev/null || true

echo "==> Package deps"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git build-essential

echo "==> Clone / update ds4 (Entrpi decode-perf-tuning)"
mkdir -p "${TARGET}/vendor"
COMMIT="5625a99d03d4210b44554708ea3fdb083677a2dc"
if [[ -d "${STAGING_VENDOR}/.git" ]]; then
  rsync -a "${STAGING_VENDOR}/" "${VENDOR}/"
elif [[ ! -d "${VENDOR}/.git" ]]; then
  git clone --depth 1 --branch decode-perf-tuning https://github.com/Entrpi/ds4.git "${VENDOR}"
else
  git -C "${VENDOR}" fetch origin decode-perf-tuning
  git -C "${VENDOR}" checkout -f decode-perf-tuning
fi
chown -R "${SPARK_USER}:${SPARK_USER}" "${VENDOR}"

echo "==> Build cuda-spark"
sudo -u "${SPARK_USER}" bash -lc "cd '${VENDOR}' && make cuda-spark -j\"\$(nproc)\""

mkdir -p "${BIN_DIR}"
install -m 755 "${VENDOR}/ds4-server" "${VENDOR}/ds4" "${VENDOR}/ds4-bench" "${BIN_DIR}/"
chmod +x "${TARGET}/scripts/spark-ds4"
chown -R "${SPARK_USER}:${SPARK_USER}" "${BIN_DIR}" "${TARGET}/scripts/spark-ds4"

mkdir -p "${TARGET}/run" "${TARGET}/logs"
chown "${SPARK_USER}:${SPARK_USER}" "${TARGET}/run" "${TARGET}/logs"

rsync -a "${STAGING}/scripts/bench-queue-discover.py" "${TARGET}/run/" 2>/dev/null || true
rsync -a "${STAGING}/scripts/bench-queue-worker.sh" "${TARGET}/run/" 2>/dev/null || true
chmod +x "${TARGET}/run/bench-queue-worker.sh" 2>/dev/null || true

if [[ -x "${SCRIPT_DIR}/20-spark-cli.sh" ]]; then
  bash "${SCRIPT_DIR}/20-spark-cli.sh"
fi

echo
echo "Done. ds4-server -> ${BIN_DIR}/ds4-server"
echo "Smoke: docs/runbooks/smoke-ds4.md"
echo "  spark engine ds4 up && spark engine ds4 status"
