#!/usr/bin/env bash
# Compat shim → modules/engines/llama-cpp.sh (use install/spark-install instead)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${ROOT}/modules/engines/llama-cpp.sh" "$@"
