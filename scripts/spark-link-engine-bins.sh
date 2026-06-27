#!/usr/bin/env bash
# Re-create /opt/spark/bin engine symlinks after git pull (binaries are gitignored since OSS cleanup).
set -euo pipefail
ROOT="/opt/spark"
BIN="${ROOT}/bin"
mkdir -p "${BIN}"

link() {
  local name="$1" src="$2"
  if [[ ! -e "${src}" ]]; then
    echo "WARN missing ${src} — run install/13-llama-cpp-smoke.sh or install/22-ds4-dwarfstar.sh" >&2
    return 1
  fi
  ln -sf "${src}" "${BIN}/${name}"
  echo "linked ${BIN}/${name} -> ${src}"
}

ok=0
link llama-server "${ROOT}/vendor/llama.cpp/build/bin/llama-server" && ok=1 || true
link llama-cli "${ROOT}/vendor/llama.cpp/build/bin/llama-cli" 2>/dev/null || true
link ds4-server "${ROOT}/vendor/ds4/ds4-server" && ok=1 || true
link ds4 "${ROOT}/vendor/ds4/ds4" 2>/dev/null || true
link ds4-bench "${ROOT}/vendor/ds4/ds4-bench" 2>/dev/null || true

if [[ -d "${ROOT}/vendor/spark-vllm-docker/.git" ]] && [[ ! -f "${ROOT}/vendor/spark-vllm-docker/run-recipe.sh" ]]; then
  echo "restoring spark-vllm-docker working tree..."
  git -C "${ROOT}/vendor/spark-vllm-docker" restore . 2>/dev/null || git -C "${ROOT}/vendor/spark-vllm-docker" checkout -f HEAD
fi

[[ "${ok}" -eq 1 ]] || exit 1
