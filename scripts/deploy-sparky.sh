#!/usr/bin/env bash
# Deploy sparkbench from techno dev clone → GitHub → sparky:/opt/spark
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
  data/model-catalog.yaml
  data/model-verification.yaml
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
SKIP="$(git ls-files -v | grep '^[S]' | wc -l | tr -d ' ')"
echo "  skip-worktree data: $SKIP file(s)"
if [[ -f run/inference-active.json ]]; then
  active="$(python3 -c "import json; print(json.load(open('run/inference-active.json')).get('profile',''))" 2>/dev/null || true)"
  echo "  inference active: ${active:-none}"
fi
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

# Host-local only — shared cookbook (catalog, verify, recipes) comes from git.
HOST_LOCAL_DATA=(
  data/inference-profiles.yaml
  data/inference-benchmarks.yaml
)
HOST_LOCAL_BACKUP_DIR="$(mktemp -d /tmp/sparky-host-local.XXXXXX)"
for path in "${HOST_LOCAL_DATA[@]}"; do
  if [[ -f "$path" ]]; then
    cp "$path" "$HOST_LOCAL_BACKUP_DIR/$(basename "$path")"
  fi
  if git ls-files --error-unmatch "$path" &>/dev/null; then
    git update-index --skip-worktree "$path" 2>/dev/null || true
  fi
done

# Only stash paths that exist on this install (older checkouts may lack hermes/, etc.)
STASH_PATHS=()
for p in "${PATHS[@]}"; do
  if [[ -e "$p" ]] || git ls-files --error-unmatch "$p" &>/dev/null; then
    STASH_PATHS+=("$p")
  fi
done

# Stash tracked edits only — never stash -u (would remove host-only recipes/services).
STASHED=0
if [[ ${#STASH_PATHS[@]} -gt 0 ]] && (
  ! git diff --quiet -- "${STASH_PATHS[@]}" 2>/dev/null \
  || ! git diff --cached --quiet -- "${STASH_PATHS[@]}" 2>/dev/null
); then
  echo "==> stashing tracked code changes under: ${STASH_PATHS[*]}"
  git stash push -m "deploy-sparky $(date -Iseconds)" -- "${STASH_PATHS[@]}"
  STASHED=1
fi

# Abort if pull would clobber untracked files (commit them on techno first).
if [[ -n "$(git ls-files -o --exclude-standard -- "${STASH_PATHS[@]}")" ]]; then
  echo "ERROR: untracked files under deploy paths — commit on techno before deploy:" >&2
  git ls-files -o --exclude-standard -- "${STASH_PATHS[@]}" | head -20 >&2
  exit 1
fi

# Active inference recipe must exist on disk (not only in stash).
if [[ -f run/inference-active.json ]]; then
  active="$(python3 -c "import json; print(json.load(open('run/inference-active.json')).get('profile',''))" 2>/dev/null || true)"
  if [[ -n "$active" && ! -f "recipes/${active}.yaml" && ! -f "recipes/drafts/${active}.yaml" ]]; then
    echo "ERROR: active profile $active has no recipe yaml — restore or switch before deploy" >&2
    exit 1
  fi
fi

# Vendor trees often drift from local builds; reset to origin before pull
if [[ -d vendor ]]; then
  git restore --source="origin/$BRANCH" --staged --worktree vendor 2>/dev/null || \
    git checkout "origin/$BRANCH" -- vendor 2>/dev/null || true
fi

git pull --ff-only origin "$BRANCH"

for path in "${HOST_LOCAL_DATA[@]}"; do
  base="$(basename "$path")"
  if [[ -f "$HOST_LOCAL_BACKUP_DIR/$base" ]]; then
    cp "$HOST_LOCAL_BACKUP_DIR/$base" "$path"
  fi
done
rm -rf "$HOST_LOCAL_BACKUP_DIR"

if [[ -x scripts/sparky-protect-runtime.sh ]]; then
  bash scripts/sparky-protect-runtime.sh
elif [[ -f scripts/sparky-protect-runtime.sh ]]; then
  bash scripts/sparky-protect-runtime.sh
fi

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
