#!/usr/bin/env bash
# eugr/spark-vllm-docker + Qwen3.6 NVFP4 local recipe
set -euo pipefail

STAGING="/home/techno/spark"
SPARK_ROOT="/opt/spark"
REPO="${SPARK_ROOT}/vendor/spark-vllm-docker"
REPO_URL="https://github.com/eugr/spark-vllm-docker.git"

echo "==> Sync services, scripts, docs"
mkdir -p "${SPARK_ROOT}/vendor" "${SPARK_ROOT}/services"
cp "${STAGING}/services/eugr-qwen36-local.yaml" "${SPARK_ROOT}/services/"
cp "${STAGING}/scripts/spark-eugr" "${SPARK_ROOT}/scripts/"
chmod +x "${SPARK_ROOT}/scripts/spark-eugr"
install -m 755 "${SPARK_ROOT}/scripts/spark-eugr" /usr/local/bin/spark-eugr

echo "==> Stop stock vLLM container (if running)"
docker stop spark-vllm-qwen36 2>/dev/null || true
docker rm spark-vllm-qwen36 2>/dev/null || true

echo "==> Clone or update eugr/spark-vllm-docker"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq git python3-pip
if [[ -d "${REPO}/.git" ]]; then
  git -C "${REPO}" pull --ff-only
else
  git clone --depth 1 "${REPO_URL}" "${REPO}"
fi
chown -R techno:techno "${REPO}"

echo "==> Build vllm-node image (downloads prebuilt wheels when available)"
sudo -u techno bash -lc "cd  && ./build-and-copy.sh"

echo "==> Start Qwen3.6 NVFP4 via eugr recipe (daemon)"
sudo -u techno spark-eugr up

echo
echo "Done."
echo "  Build/run logs: spark-eugr logs"
echo "  Status:         spark-eugr status"
echo "  Chat UI:        http://sparky:3000"
echo "  vLLM API:       http://sparky:8000/v1"
