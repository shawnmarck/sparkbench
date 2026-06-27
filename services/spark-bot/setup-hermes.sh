#!/usr/bin/env bash
# Optional: bootstrap a Hermes runtime directory outside /opt/spark.
#
# Audience: SparkBench operators who want to run the Hermes chatbot in front
#           of the inference gateway. Hermes itself is NOT part of SparkBench
#           and is not installed by this script — only the runtime layout.
#
# Safe to skip entirely if you only use the CLI / portal / Open WebUI.
set -euo pipefail

SPARK_HOST="${SPARK_HOST:-sparky}"
HERMES_ROOT="${HERMES_ROOT:-/opt/hermes}"
HERMES_USER="${HERMES_USER:-${SUDO_USER:-$USER}}"

cat <<EOF
This will:
  • Create   ${HERMES_ROOT}/{data/spark-bot/data,data/workspace}
  • Chown    to ${HERMES_USER}
  • Print    next steps (clone sparky-hermes, fill secrets, docker compose up)

It will NOT:
  • Install Docker / compose / Hermes itself
  • Write any credentials
  • Touch /opt/spark or your inference profile

Endpoint your bot will use:
  OPENAI_BASE_URL=http://${SPARK_HOST}:9000/v1

Continue? [y/N] EOF
read -r ANS
[[ "${ANS,,}" == "y" || "${ANS,,}" == "yes" ]] || { echo "Aborted."; exit 0; }

sudo mkdir -p "${HERMES_ROOT}/data/spark-bot/data" "${HERMES_ROOT}/data/workspace"
sudo chown -R "${HERMES_USER}:${HERMES_USER}" "${HERMES_ROOT}"

cat <<EOF

OK: ${HERMES_ROOT} is ready.

Next steps:
  1. Clone the Hermes deployment scaffold next to SparkBench:
       git clone https://github.com/shawnmarck/sparky-hermes ~/projects/sparky-hermes
       (repo private/forthcoming — DM the maintainer for early access)

  2. Drop your config + secrets into ${HERMES_ROOT}/data/spark-bot/data/
     (config.yaml, .env, oauth tokens — see the sparky-hermes README)

  3. Bring it up:
       cd ~/projects/sparky-hermes && docker compose up -d

  4. Confirm it can reach the gateway:
       curl -s http://${SPARK_HOST}:9000/v1/models | jq .
EOF
