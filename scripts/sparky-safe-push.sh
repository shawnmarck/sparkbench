#!/usr/bin/env bash
# Safe git push from a live Spark box — commits shared cookbook only; never stages host-local.
#
# Usage:
#   bash scripts/sparky-safe-push.sh -m "your message"
#   DRY_RUN=1 bash scripts/sparky-safe-push.sh -m "preview"
#
# Agent workflow: edit shared files → this script → push. Custom per-host files go in local/ (gitignored).
set -euo pipefail

ROOT="${SPARK_ROOT:-/opt/spark}"
BRANCH="${BRANCH:-main}"
DRY_RUN="${DRY_RUN:-0}"
cd "$ROOT"

MSG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message) MSG="${2:-}"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$MSG" ]]; then
  echo "usage: $0 -m \"commit message\"" >&2
  exit 2
fi

NEVER_STAGE=(
  local/
  run/
  logs/
  portal/models.json
  data/inference-profiles.yaml
  data/inference-benchmarks.yaml
  data/hf-download-queue.yaml
  data/hf-explore-queue.yaml
  data/inference-benchmark-history.yaml
  host.env
  .env
  vendor/
  bin/
)

if [[ -x scripts/sparky-protect-runtime.sh ]]; then
  bash scripts/sparky-protect-runtime.sh
fi

# Refuse if host-local files have staged changes (skip-worktree can still be explicitly added).
for path in data/inference-profiles.yaml data/inference-benchmarks.yaml; do
  if git diff --cached --quiet -- "$path" 2>/dev/null; then
    :
  else
    echo "ERROR: $path is staged — unstage (host-local must not be committed)" >&2
    exit 1
  fi
done

if [[ -n "$(git status --porcelain -- local/ 2>/dev/null | head -1)" ]]; then
  echo "==> local/ has custom files (gitignored — will not be committed)"
fi

CHANGED="$(git status --porcelain | grep -v '^.. local/' | grep -v '^?? local/' || true)"
if [[ -z "$CHANGED" ]]; then
  echo "==> nothing to commit"
  exit 0
fi

echo "==> staging shared changes (excluding host-local)"
git add -A
for path in "${NEVER_STAGE[@]}"; do
  git reset -q HEAD -- "$path" 2>/dev/null || true
done

if git diff --cached --quiet; then
  echo "==> nothing left to commit after excluding host-local"
  exit 0
fi

echo "==> staged:"
git diff --cached --stat

if [[ "$DRY_RUN" == 1 ]]; then
  echo "==> DRY_RUN=1 — not committing"
  git reset -q HEAD
  exit 0
fi

git commit -m "$MSG"
echo "==> pushing origin $BRANCH"
git push origin "$BRANCH"
echo "==> done $(git rev-parse --short HEAD)"
