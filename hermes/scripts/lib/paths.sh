# Shared sparky Hermes paths. Source from deploy/backup/migrate scripts.
SPARKY_HOST="${SPARKY_HOST:-sparky}"
HOST="${SPARKY_HOST}"
SPARKY_HERMES_ROOT="${SPARKY_HERMES_ROOT:-/opt/hermes}"
SPARKY_REPO_ROOT="${SPARKY_REPO_ROOT:-/opt/spark}"
REMOTE_DATA="${SPARKY_HERMES_ROOT}/data/spark-bot/data"
REMOTE_WORKSPACE="${SPARKY_HERMES_ROOT}/data/workspace"

# Legacy location (pre-split). Used only by migrate-hermes-out-of-spark.sh.
LEGACY_HERMES_ROOT="/opt/spark/hermes"