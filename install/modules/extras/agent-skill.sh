#!/usr/bin/env bash
# Copy SparkBench agent skill into ~/.claude/skills and ~/.cursor/skills for SPARK_USER.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"

SRC="${SPARK_ROOT}/.claude/skills/sparkbench"
[[ -d "$SRC" ]] || {
  echo "spark-install: missing ${SRC} — clone the full repo first" >&2
  exit 1
}

HARNESS="${SPARK_HARNESS:-both}"
case "$HARNESS" in
  claude|cursor|both) ;;
  *)
    echo "spark-install: SPARK_HARNESS must be claude, cursor, or both (got: ${HARNESS})" >&2
    exit 1
    ;;
esac

if [[ "$(id -u)" -eq 0 ]]; then
  user_home="$(getent passwd "$SPARK_USER" | cut -d: -f6 || true)"
  [[ -n "$user_home" && -d "$user_home" ]] || {
    echo "spark-install: no home directory for SPARK_USER=${SPARK_USER}" >&2
    exit 1
  }
  owner="$SPARK_USER"
  group="$(id -gn "$SPARK_USER" 2>/dev/null || echo "$SPARK_USER")"
else
  owner="$(id -un)"
  user_home="${HOME}"
  group="$(id -gn)"
fi

install_tree() {
  local dest_root="$1"
  local dest="${dest_root}/sparkbench"
  local refs="${dest}/references"

  if [[ "$(id -u)" -eq 0 ]]; then
    install -d -o "$owner" -g "$group" "$dest_root" "$dest" "$refs"
    install -o "$owner" -g "$group" -m 644 "${SRC}/SKILL.md" "${dest}/SKILL.md"
    install -o "$owner" -g "$group" -m 644 "${SRC}/references/api.md" "${refs}/api.md"
  else
    mkdir -p "$refs"
    install -m 644 "${SRC}/SKILL.md" "${dest}/SKILL.md"
    install -m 644 "${SRC}/references/api.md" "${refs}/api.md"
  fi
  echo "  ${dest}/SKILL.md"
}

echo "SparkBench agent skill → ${user_home} (HARNESS=${HARNESS})"

case "$HARNESS" in
  claude|both)
    install_tree "${user_home}/.claude/skills"
    ;;
esac

case "$HARNESS" in
  cursor|both)
    install_tree "${user_home}/.cursor/skills"
    ;;
esac

echo "OK: agent skill installed for ${owner}"
echo "  Claude Code: /sparkbench (or auto-load from project skill when cwd is ${SPARK_ROOT})"
echo "  Cursor: skill available after restart when listed in agent skills"
