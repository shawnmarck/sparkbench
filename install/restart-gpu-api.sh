#!/usr/bin/env bash
# Passwordless on sparky via /opt/spark/install/*.sh sudoers.
set -euo pipefail
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/modules/core/gpu-api-restart.sh"
