# Optional: chatbot in front of SparkBench

SparkBench ships an **OpenAI-compatible gateway on `:9000`** (`spark-inference-gateway.py`).
Anything that speaks that protocol can talk to your active profile, including:

| UI / bot          | What it gives you                                   |
| ----------------- | --------------------------------------------------- |
| **Open WebUI**    | Drop-in ChatGPT clone, multi-user, no code          |
| **Hermes**        | Self-hosted persistent agent (Discord/Slack-style)  |
| **LibreChat**     | Extensible chat with tool-use UI                    |
| Your own client   | Any OpenAI SDK pointed at `http://<host>:9000/v1`   |

None of these are required — `spark inference` is fully usable from the CLI and portal.

## Quickstart: pick one

```bash
# Spark gateway endpoint (used by every bot)
export OPENAI_BASE_URL="http://${SPARK_HOST:-sparky}:9000/v1"
export OPENAI_API_KEY="any-string-the-gateway-doesnt-check"
```

### Option A — Open WebUI (recommended for first-time setup)

Bundled installer: `sudo bash install/spark-install openwebui`. Browse to `http://<host>:3000`
once it's up and point it at the gateway URL above.

### Option B — Spark operator (Hermes)

Portal v2 includes **Spark**, an embedded operator backed by the official
Hermes Agent image and an out-of-band provider:

```bash
sudo bash install/spark-install hermes
```

The installer preserves existing `/opt/hermes` sessions, memory, OAuth tokens,
provider configuration, and secrets. It adds typed SparkBench MCP tools and
the `/operator` portal experience. Spark can perform reads immediately;
inference, queue, recipe, shelf, install, provider, and scheduler changes only
run after an explicit portal confirmation.

Advanced Hermes dashboard: `http://<host>:9119/`. Newly generated dashboard
credentials are stored mode `0600` at `/opt/hermes/dashboard-credentials`.

### Option C — bring your own

`OPENAI_BASE_URL` + `OPENAI_API_KEY` is all you need. The gateway accepts
`/v1/chat/completions` (streaming and non-streaming) and `/v1/completions`.

## Helper: `setup-hermes.sh`

Legacy helper that scaffolds a local Hermes deployment outside `/opt/spark`
(defaults to `/opt/hermes`). It will:

1. Prompt for confirmation
2. Create the runtime dir + data layout
3. Print next-step instructions

New Portal v2 installs should use `spark-install hermes`; this helper remains
for external-compose deployments.

```bash
bash services/spark-bot/setup-hermes.sh
```
