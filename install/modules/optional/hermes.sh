#!/usr/bin/env bash
# Hermes-backed Spark operator. Preserves all host-local state and credentials.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../common.sh
source "${INSTALL_DIR}/common.sh"

HERMES_ROOT="${SPARK_HERMES_ROOT:-/opt/hermes}"
DATA_DIR="${HERMES_ROOT}/data/spark-bot/data"
WORKSPACE_DIR="${HERMES_ROOT}/data/workspace"
STATE_DIR="${SPARK_ROOT}/run/operator"
MANAGED_COMPOSE="${HERMES_ROOT}/sparkbench-compose.yml"
SOURCE="${SPARK_STAGING}/services/spark-bot"
PYTHON="${SPARK_ROOT}/venv/bin/python"

command -v docker >/dev/null 2>&1 || {
  echo "spark-install: Docker is required for the Hermes add-on" >&2
  exit 1
}
[[ -x "${PYTHON}" ]] || {
  echo "spark-install: ${PYTHON} is missing; run spark-install core first" >&2
  exit 1
}

echo "==> Prepare preservation-safe Hermes runtime"
install -d -m 0750 -o "${SPARK_USER}" -g "${SPARK_USER}" \
  "${HERMES_ROOT}" "${DATA_DIR}" "${WORKSPACE_DIR}"
install -d -m 0770 -o "${SPARK_USER}" -g "${SPARK_USER}" "${STATE_DIR}"
chown -R "${SPARK_USER}:${SPARK_USER}" "${STATE_DIR}"
install -m 0644 "${SOURCE}/compose.yml" "${MANAGED_COMPOSE}"
chown "${SPARK_USER}:${SPARK_USER}" "${MANAGED_COMPOSE}"

touch "${DATA_DIR}/.env"
chmod 0600 "${DATA_DIR}/.env"
chown "${SPARK_USER}:${SPARK_USER}" "${DATA_DIR}/.env"

ensure_env() {
  local key="$1"
  local value="$2"
  if ! grep -q "^${key}=" "${DATA_DIR}/.env"; then
    printf '%s=%s\n' "${key}" "${value}" >> "${DATA_DIR}/.env"
  fi
}

ensure_env HERMES_DASHBOARD_BASIC_AUTH_USERNAME spark
if ! grep -q '^HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=' "${DATA_DIR}/.env"; then
  dashboard_password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  ensure_env HERMES_DASHBOARD_BASIC_AUTH_PASSWORD "${dashboard_password}"
  printf 'username=spark\npassword=%s\n' "${dashboard_password}" > "${HERMES_ROOT}/dashboard-credentials"
  chmod 0600 "${HERMES_ROOT}/dashboard-credentials"
  chown "${SPARK_USER}:${SPARK_USER}" "${HERMES_ROOT}/dashboard-credentials"
  unset dashboard_password
fi

echo "==> Merge typed SparkBench MCP configuration"
install -m 0644 "${SOURCE}/config-operator-overlay.yaml" "${HERMES_ROOT}/config-operator-overlay.yaml"
"${PYTHON}" "${SOURCE}/apply-config.py" \
  --config "${DATA_DIR}/config.yaml" \
  --overlay "${HERMES_ROOT}/config-operator-overlay.yaml"
chown "${SPARK_USER}:${SPARK_USER}" "${DATA_DIR}/config.yaml"

if [[ ! -f "${DATA_DIR}/SOUL.md" ]]; then
  install -m 0644 "${SOURCE}/SOUL.md" "${DATA_DIR}/SOUL.md"
fi
if [[ ! -f "${DATA_DIR}/AGENTS.md" ]]; then
  install -m 0644 "${SOURCE}/AGENTS.md" "${DATA_DIR}/AGENTS.md"
fi
install -d -m 0750 "${DATA_DIR}/skills/sparkbench"
install -m 0644 "${SOURCE}/skills/sparkbench/SKILL.md" "${DATA_DIR}/skills/sparkbench/SKILL.md"
chown -R "${SPARK_USER}:${SPARK_USER}" "${DATA_DIR}/skills/sparkbench"

echo "==> Pull and recreate spark-bot (persistent data is retained)"
export HERMES_DATA_DIR="${DATA_DIR}"
export HERMES_WORKSPACE_DIR="${WORKSPACE_DIR}"
export SPARK_OPERATOR_STATE="${STATE_DIR}"
export SPARK_ROOT
export HERMES_UID
export HERMES_GID
HERMES_UID="$(id -u "${SPARK_USER}")"
HERMES_GID="$(id -g "${SPARK_USER}")"

docker compose -f "${MANAGED_COMPOSE}" pull spark-bot
docker rm -f spark-bot >/dev/null 2>&1 || true
docker compose -f "${MANAGED_COMPOSE}" up -d spark-bot

systemctl restart spark-operator-api.service 2>/dev/null || true

echo "==> Wait for Hermes"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:9119/api/status" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

curl -fsS "http://127.0.0.1:8772/api/operator/status" >/dev/null
echo "OK: Spark operator runtime is available"
echo "    Portal: http://${SPARK_HOST}/operator"
echo "    Hermes advanced dashboard: http://${SPARK_HOST}:9119/"
echo "    Dashboard credentials: ${HERMES_ROOT}/dashboard-credentials (when generated)"
