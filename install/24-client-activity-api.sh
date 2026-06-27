#!/usr/bin/env bash
# Compat shim → modules/gateway/client-activity.sh (use install/spark-install instead)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${ROOT}/modules/gateway/client-activity.sh" "$@"
