#!/usr/bin/env bash
# Compat shim → modules/extras/zsh-powerlevel10k.sh (use install/spark-install instead)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${ROOT}/modules/extras/zsh-powerlevel10k.sh" "$@"
