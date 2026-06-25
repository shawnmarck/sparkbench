#!/usr/bin/env bash
# Deploy sparky-dashboard from techno dev clone → GitHub → sparky:/opt/spark
#
# Usage (from repo root on techno):
#   ./scripts/deploy-sparky.sh              # push main + pull on sparky
#   SKIP_PUSH=1 ./scripts/deploy-sparky.sh  # pull only
#   ./scripts/deploy-sparky.sh --status     # show drift, no changes
#   REGENERATE_INVENTORY=1 ./scripts/deploy-sparky.sh
#
# Code changes: edit on techno → commit → this script.
# Ops (inference up, audits): ssh sparky directly — not via deploy.
set -euo pipefail

SPARK_HOST="${SPARK_HOST:-sparky}"
SPARK_ROOT="${SPARK_ROOT:-/opt/spark}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRANCH="${BRANCH:-main}"

CODE_PATHS=(
  scripts
  services
  recipes
  portal
  docs
  hermes
  bin
  data/golden-recipes.yaml
  AGENT.md
  README.md
)

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \?//'
}

status_only=0
[[ "${1:-}" == "--status" ]] && status_only=1

remote_status() {
  ssh "$SPARK_HOST" bash -s -- "$SPARK_ROOT" "$BRANCH" <<'REMOTE'
set -euo pipefail
ROOT="$1"
BRANCH="$2"
cd "$ROOT"
git fetch origin "$BRANCH" 2>/dev/null || git fetch origin
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"
echo "sparky:$ROOT"
echo "  branch: $(git branch --show-current)"
echo "  local:  $LOCAL $(git log -1 --format='(%cr) %s' "$LOCAL")"
echo "  origin: $REMOTE $(git log -1 --format='(%cr) %s' "origin/$BRANCH")"
if [[ "$LOCAL" != "$REMOTE" ]]; then
  echo "  drift:  BEHIND or AHEAD (not matched)"
else
  echo "  drift:  matched origin/$BRANCH"
fi
DIRTY="$(git status --porcelain | wc -l | tr -d ' ')"
echo "  dirty:  $DIRTY path(s)"
REMOTE
}

if [[ "$status_only" == 1 ]]; then
  echo "==> techno: $REPO_ROOT"
  git fetch origin "$BRANCH" 2>/dev/null || true
  echo "  branch: $(git branch --show-current)"
  echo "  HEAD:   $(git rev-parse --short HEAD) $(git log -1 --format='(%cr) %s')"
  echo ""
  remote_status
  exit 0
fi

cd "$REPO_ROOT"
if [[ "${SKIP_PUSH:-0}" != 1 ]]; then
  echo "==> push origin $BRANCH"
  git push origin "$BRANCH"
else
  echo "==> SKIP_PUSH=1 (no push)"
fi

echo "==> pull on $SPARK_HOST:$SPARK_ROOT"
ssh "$SPARK_HOST" bash -s -- "$SPARK_ROOT" "$BRANCH" "${CODE_PATHS[@]}" <<'REMOTE'
set -euo pipefail
ROOT="$1"
BRANCH="$2"
shift 2
PATHS=("$@")
cd "$ROOT"

git fetch origin "$BRANCH"

# Stash uncommitted code-path changes (keep runtime data/*.yaml on disk)
STASHED=0
if ! git diff --quiet -- "${PATHS[@]}" 2>/dev/null \
  || ! git diff --cached --quiet -- "${PATHS[@]}" 2>/dev/null \
  || [[ -n "$(git ls-files -o --exclude-standard -- "${PATHS[@]}")" ]]; then
  echo "==> stashing local code changes under: ${PATHS[*]}"
  git stash push -u -m "deploy-sparky $(date -Iseconds)" -- "${PATHS[@]}"
  STASHED=1
fi

# Vendor trees often drift from local builds; reset to origin before pull
if [[ -d vendor ]]; then
  git restore --source="origin/$BRANCH" --staged --worktree vendor 2>/dev/null || \
    git checkout "origin/$BRANCH" -- vendor 2>/dev/null || true
fi

git pull --ff-only origin "$BRANCH"

if [[ -x scripts/apply-spark-patches.sh ]]; then
  bash scripts/apply-spark-patches.sh
elif [[ -f scripts/apply-spark-patches.sh ]]; then
  bash scripts/apply-spark-patches.sh
fi

echo "==> deployed $(git rev-parse --short HEAD) — $(git log -1 --format=%s)"
if [[ "$STASHED" == 1 ]]; then
  echo "==> note: previous code edits stashed — list: git stash list"
fi
REMOTE

if [[ "${REGENERATE_INVENTORY:-0}" == 1 ]]; then
  echo "==> spark models inventory"
  ssh "$SPARK_HOST" "cd $SPARK_ROOT && spark models inventory"
fi

if [[ "${SMOKE:-0}" == 1 ]]; then
  echo "==> smoke"
  ssh "$SPARK_HOST" "spark inference status | head -15"
fi

echo "==> done"
