# Inference stack

Control plane for one GPU workload at a time, many logical model names, and a stable client URL.

Portal: http://sparky/ → **Inference**. Gateway: http://sparky:9000/v1.

## Layers

| Layer | Multi-model? | How |
|-------|--------------|-----|
| Gateway / API | Yes | Many ids (`sparky`, `qwen3.6-27b-dflash`, …) |
| Physical GB10 | One heavy slot | One recipe loaded; switch = evict + start |
| Agents | Yes, with swap cost | Request any registered name; cold start returns 503 |

Agents are not locked to one model. They wait out switch time when the requested profile is not active. Prefer model `sparky` so the client always hits whatever is already up.

## Architecture

```text
OpenCode · Grok · Hermes · Open WebUI · curl
        │
        ▼
  Gateway :9000/v1
  (aliases, sparky, activity log)
        │
        ▼
  spark inference API :8767  →  nginx /api/inference/*
        │
        ▼
  One active profile
  eugr :8000  ·  llama.cpp :8081  ·  ds4 :8000
        │
        ▼
  Portal Inference + System activity
```

eugr and ds4 share port 8000. Never run two engines.

## Recipes

One YAML per profile under `recipes/` (drafts in `recipes/drafts/`). Enabled ids live in host-local `data/inference-profiles.yaml`.

```yaml
id: opencode-qwen36-250k
name: Qwen3.6-35B-A3B 250k NVFP4
catalog_id: nvidia/qwen3.6-35b-a3b-nvfp4
inventory_path: nvidia/qwen3.6-35b-a3b
engine: eugr                    # eugr | llamacpp | ds4
tier: heavy
eugr_recipe: /opt/spark/services/eugr-qwen36-local.yaml
served_name: qwen3.6-35b-a3b-nvfp4
port: 8000
lifecycle: works
context:
  default: 256000
  kv_default: fp8
```

Public display names drop client branding. Profile ids keep the `opencode-` prefix so existing `up` commands stay stable.

Scaffold: `spark recipe scaffold <lab/slug> <engine>`. Extend the router in `spark-inference.py` plus catalog `engine` / `capabilities`. Hand-write YAML only for MoE, multimodal, DFlash, ds4, or MTP.

### ds4

Native DeepSeek V4 Flash. Pin: `data/ds4-dwarfstar.yaml`. Production profile: `antirez-deepseek-v4-flash-ds4`.

```yaml
engine: ds4
served_name: deepseek-v4-flash
port: 8000
ds4_args:
  - -c
  - "32768"
  - --dspark
  - /models/antirez/deepseek-v4-flash/gguf/DSpark-drafter-Q2K-Q8-0731.gguf
```

OOM guard: `scripts/ds4-oom-guard.sh`. Casual chat: `:8002/v1` (thinking off) or model id `deepseek-chat` on `:8000`.

## CLI

```bash
spark inference status
spark inference list
spark inference up opencode-qwen36-250k
spark inference down
spark inference logs
spark inference bench
```

Agents: `spark inference help` or `GET /api/inference/status`. Full table: [spark-cli.md](spark-cli.md).

`scripts/spark-inference-api.py` (:8767) reloads `spark-inference.py` each request. Routine logic changes need no restart. Restart the API process only when `spark-inference-api.py` itself changes: `sudo bash install/spark-install restart inference-api`.

## Gateway

Stable URL: `http://sparky:9000/v1` (or `127.0.0.1:9000` on the box).

- Thin proxy: `scripts/spark-inference-gateway.py`
- Forwards `/v1/*` with SSE streaming
- `sparky` / `sparky-think` / `sparky-fast` always use the **active** served model (no auto-switch)
- Named aliases can trigger `start_switch_job()` and return **503 + Retry-After** until ready
- Headers: `X-Spark-Active-Profile`, `X-Spark-Upstream-Port`, `X-Spark-Served-Model`
- Systemd: `spark-inference-gateway.service`
- Activity: each chat/completions POST appends `run/inference-activity.jsonl` (auth stripped; 50 MB / 7d). `spark-client-activity.py` (:8769, `/api/activity`) rolls 1h/24h for the portal and folds token rows into host-local `run/inference-usage.json`

```bash
curl http://sparky:9000/v1/models
curl -X POST http://sparky:9000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"sparky","messages":[{"role":"user","content":"hi"}],"max_tokens":32}'
spark gateway --list-aliases
```

Hardcoded aliases live in `spark-inference-gateway.py` (`hermes-local`, `qwen-local`, …). Extend there.

## Agent production profiles

| Profile ID | Served name | Context | Role |
|------------|-------------|---------|------|
| `opencode-qwen36-250k` | `qwen3.6-35b-a3b-nvfp4` | 256k, fp8 KV | MoE coding / general agents |
| `opencode-qwen27-dflash-262k` | `qwen3.6-27b-dflash` | 262k, DFlash | Dense 27B, design / architecture |
| `qwen36-35b-a3b-mtp-eugr` | NVIDIA NVFP4 + MTP | 256k | Golden companion for `nvidia/qwen3.6-35b-a3b` |

```bash
spark inference up opencode-qwen36-250k
```

Gateway alias `qwen3.6-27b-dflash` maps to `opencode-qwen27-dflash-262k`. Reload at a new ctx: `spark inference down && spark inference up <id>`.

`qwen36-nvfp4` is deprecated. Do not document it as the default.

## Speculative extras

MTP, DFlash, DSpark, Eagle live on the recipe (`speculative:` / `mtp:`), not in portal settings. eugr flags go in the service YAML `command:` block. llama.cpp flags go in `llamacpp_args`.

## Portal

Inference tab: active profile, switch, logs, engine filter (vLLM / llama.cpp / ds4), eugr upgrade banner. System tab: GPU + client activity. Benchmaster tab: overnight queue.

Open WebUI (`:3000`) can point at the gateway or at an engine directly. Gateway is the one URL that survives a profile switch.
