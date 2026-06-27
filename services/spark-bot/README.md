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

### Option B — Hermes (the agent we run in our own lab)

Hermes is **not part of SparkBench**. We run it as a separate service in our homelab.
A reference compose + deploy script lives at the link below — clone it next to SparkBench
and follow its README:

> **https://github.com/shawnmarck/sparky-hermes** *(repo not yet public; see ./setup-hermes.sh below for a local-only bootstrap)*

### Option C — bring your own

`OPENAI_BASE_URL` + `OPENAI_API_KEY` is all you need. The gateway accepts
`/v1/chat/completions` (streaming and non-streaming) and `/v1/completions`.

## Helper: `setup-hermes.sh`

Optional script that scaffolds a local Hermes deployment outside `/opt/spark`
(defaults to `/opt/hermes`). It will:

1. Prompt for confirmation
2. Create the runtime dir + data layout
3. Pull a starter `compose.yml`
4. Print next-step instructions

It does **not** ship secrets, OAuth tokens, or persona files — those are
deployment-specific and you generate them yourself.

```bash
bash services/spark-bot/setup-hermes.sh
```
