#!/usr/bin/env bash
# Compat shim → modules/core/removal-cron.sh (use install/spark-install instead)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${ROOT}/modules/core/removal-cron.sh" "$@"
