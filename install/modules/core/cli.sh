#!/usr/bin/env bash
# Unified spark CLI — single /usr/local/bin/spark (removes legacy spark-* bins).
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"
TARGET="${SPARK_ROOT}"

SPARK_BIN="${TARGET}/scripts/spark"
chmod +x "${SPARK_BIN}"
chmod +x "${TARGET}/scripts/spark-inventory-build" \
  "${TARGET}/scripts/spark-models-fetch.py" \
  2>/dev/null || true
chmod +x "${TARGET}/scripts/spark-inference" \
  "${TARGET}/scripts/spark-eugr" \
  "${TARGET}/scripts/spark-llama" \
  "${TARGET}/scripts/spark-shelf-pull" \
  "${TARGET}/scripts/spark-shelf-push" \
  "${TARGET}/scripts/spark-hf-login" \
  "${TARGET}/scripts/spark-hf.py" \
  "${TARGET}/scripts/spark-hf-api" \
  "${TARGET}/scripts/spark-hf-api.py" \
  "${TARGET}/scripts/spark-inventory-build" \
  "${TARGET}/scripts/spark-local-rm" \
  "${TARGET}/scripts/spark-gpu-metrics" \
  "${TARGET}/scripts/spark-model-verify" 2>/dev/null || true
chmod +x "${TARGET}/scripts/legacy/"* 2>/dev/null || true

install -m 755 "${SPARK_BIN}" /usr/local/bin/spark

LEGACY_BINS=(
  spark-inference
  spark-eugr
  spark-llama
  spark-shelf-pull
  spark-shelf-push
  spark-hf-login
  spark-inventory-build
  spark-inventory-refresh
)
for bin in "${LEGACY_BINS[@]}"; do
  if [[ -e "/usr/local/bin/${bin}" ]]; then
    rm -f "/usr/local/bin/${bin}"
    echo "Removed legacy /usr/local/bin/${bin}"
  fi
done

if [[ -d /etc/bash_completion.d ]]; then
  install -m 644 "${INSTALL_DIR}/completions/spark.bash" /etc/bash_completion.d/spark
  echo "OK: bash completion → /etc/bash_completion.d/spark"
fi

ZSH_SITE="/usr/local/share/zsh/site-functions"
if [[ -d /usr/share/zsh/vendor-completions ]]; then
  ZSH_SITE="/usr/share/zsh/vendor-completions"
fi
mkdir -p "${ZSH_SITE}"
install -m 644 "${INSTALL_DIR}/completions/_spark" "${ZSH_SITE}/_spark"
echo "OK: zsh completion → ${ZSH_SITE}/_spark"

ZSH_RC="/etc/zsh/zshrc.d"
if [[ -d "${ZSH_RC}" ]]; then
  install -m 644 "${INSTALL_DIR}/completions/spark.zsh" "${ZSH_RC}/spark.zsh"
  echo "OK: zsh noglob + ? help → ${ZSH_RC}/spark.zsh"
fi

"${SPARK_BIN}" --help >/dev/null
"${SPARK_BIN}" inference list >/dev/null
echo "OK: spark CLI at /usr/local/bin/spark"
echo "    Tab-complete: spark <group> …"