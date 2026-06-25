# Phase 5 — local spark inference (deferred)

Wire spark-bot to `/opt/spark` OpenAI-compatible APIs when a stable model profile is chosen.

## Prerequisites

- Bench worker not actively swapping models, or accept cloud fallback during swaps
- Pinned recipe e.g. `recipes/hermes-primary.yaml` in `/opt/spark`
- Model loaded: `spark inference up hermes-primary`

## Compose change

Add to `compose.yml` under `spark-bot`:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

## Overlay change

```yaml
model:
  provider: custom
  model: hermes-local          # gateway alias → active profile (or use served_name)
  base_url: http://host.docker.internal:9000/v1   # unified gateway (always)

fallback_providers:
  - provider: zai
    model: glm-5-turbo
  - provider: xai-oauth
    model: grok-4-fast-reasoning
```

| Client endpoint | Port | Notes |
|-----------------|------|-------|
| **Gateway (use this)** | `:9000/v1` | Stable URL; proxies active engine |
| eugr (vLLM) | `:8000/v1` | Direct (debug only) |
| llama.cpp | `:8081/v1` | Direct (debug only) |
| ds4 chat proxy | `:8002/v1` | Open WebUI thinking-off hack |

Service: `systemctl status spark-inference-gateway`
Install: `sudo bash /opt/spark/install/23-inference-gateway.sh`

## Rules

- Never automate `spark inference up/down` from Hermes
- Hermes container stays CPU-only (no `--gpus`)
- One GPU engine at a time on sparky

## Model candidates (production on sparky)

| Profile | Gateway model | Use |
|---------|-----------------|-----|
| `opencode-qwen36-250k` | `qwen3.6-35b-a3b-nvfp4` | Fast MoE coding agents @ 256k |
| `opencode-qwen27-dflash-262k` | `qwen3.6-27b-dflash` | Architecture / design @ 262k |
| `antirez-deepseek-v4-flash-ds4` | (ds4 served name) | DeepSeek V4 Flash via ds4 |

Point OpenCode at `http://sparky:9000/v1` (use model `sparky` or the served name) and run `sync-sparky-models` after profile switches. The gateway always advertises a stable `sparky` model id via `/v1/models`.