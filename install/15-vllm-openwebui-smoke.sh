#!/usr/bin/env bash
# Compat shim → modules/legacy/vllm-openwebui-smoke.sh (use install/spark-install instead)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${ROOT}/modules/legacy/vllm-openwebui-smoke.sh" "$@"
