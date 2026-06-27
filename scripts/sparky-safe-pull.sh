#!/usr/bin/env bash
# Safe git pull on a live Spark box — never stops inference, restores host-local YAML.
#
# Usage (on sparky):
#   bash scripts/sparky-safe-pull.sh
#   BRANCH=main bash scripts/sparky-safe-pull.sh
#
# Does NOT run: spark-install core, inference down/up, nginx reload, gateway restart.
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
BRANCH="${BRANCH:-main}"
cd "$ROOT"

HOST_LOCAL_DATA=(
  data/inference-profiles.yaml
  data/inference-benchmarks.yaml
)

active_profile() {
  python3 -c "import json; print(json.load(open('run/inference-active.json')).get('profile',''))" 2>/dev/null || true
}

echo "==> sparky-safe-pull ($ROOT @ branch $BRANCH)"
BEFORE="$(active_profile)"
if [[ -n "$BEFORE" ]]; then
  echo "    inference active: $BEFORE (will not be stopped)"
else
  echo "    inference: none active"
fi

if [[ -x scripts/sparky-protect-runtime.sh ]]; then
  bash scripts/sparky-protect-runtime.sh
fi

BACKUP_DIR="$(mktemp -d /tmp/sparky-host-local.XXXXXX)"
cleanup() { rm -rf "$BACKUP_DIR"; }
trap cleanup EXIT

for path in "${HOST_LOCAL_DATA[@]}"; do
  if [[ -f "$path" ]]; then
    cp "$path" "$BACKUP_DIR/$(basename "$path")"
  fi
done

git fetch origin "$BRANCH"
git pull --ff-only "origin/$BRANCH"

for path in "${HOST_LOCAL_DATA[@]}"; do
  base="$(basename "$path")"
  if [[ -f "$BACKUP_DIR/$base" ]]; then
    cp "$BACKUP_DIR/$base" "$path"
  fi
done

if [[ -x scripts/migrate-host-local-data.sh ]]; then
  bash scripts/migrate-host-local-data.sh
fi

if [[ -x scripts/spark-link-engine-bins.sh ]]; then
  bash scripts/spark-link-engine-bins.sh || echo "WARN: engine bin symlinks incomplete — run install engine step" >&2
fi

if [[ -x scripts/sparky-protect-runtime.sh ]]; then
  bash scripts/sparky-protect-runtime.sh
fi

if command -v spark >/dev/null 2>&1; then
  spark models inventory >/dev/null 2>&1 || true
fi

AFTER="$(active_profile)"
echo "==> pulled $(git rev-parse --short HEAD) — $(git log -1 --format=%s)"
if [[ -n "$BEFORE" ]]; then
  if [[ "$BEFORE" == "$AFTER" ]]; then
    echo "    inference still active: $BEFORE"
  else
    echo "    WARN: active profile changed during pull: ${BEFORE:-none} -> ${AFTER:-none}"
    echo "    (unexpected — pull should not touch run/inference-active.json)"
  fi
fi
