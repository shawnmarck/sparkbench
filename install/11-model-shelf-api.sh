#!/usr/bin/env bash
# Compat shim → modules/core/shelf-api.sh (use install/spark-install instead)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${ROOT}/modules/core/shelf-api.sh" "$@"
