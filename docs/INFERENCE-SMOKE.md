# Inference smoke test (Phase 3a — vLLM)

**Status: PASSING** (2026-06-21)

Temporary stack to validate vLLM on GB10 before the vLLM Studio vs Rookery bake-off.

## Stack

| Layer | Tool | URL |
|-------|------|-----|
| Engine | eugr spark-vllm-docker | http://sparky:8000/v1 |
| Chat UI | Open WebUI | http://sparky:3000 |

Open WebUI is **only for basic chat testing**. It is not part of the Phase 4 orchestrator bake-off.

## Model

- Path: `/models/nvidia/qwen3.6-35b-a3b/nvfp4`
- Served name: `qwen3.6-35b-a3b-nvfp4`
- Format: NVFP4 (vLLM `compressed-tensors` — not llama.cpp)
- Context: 65K (`--max-model-len 65536`)

## Why eugr, not stock vLLM

Stock `vllm/vllm-openai:cu130-nightly` fails to load this checkpoint:

```
KeyError: layers.0.mlp.experts.w2_input_scale
```

MoE NVFP4 scale tensors aren't handled by the stock ModelOpt loader on Spark. The eugr build + `mods/fix-qwen3.6-chat-template` recipe works.

## Commands

```bash
# Start (build once via install/07-eugr-vllm-qwen36.sh)
spark-eugr up

# Logs (first boot may take 5–15 min for CUDA graph compile)
spark-eugr logs

# Status + /v1/models
spark-eugr status

# Stop (required before llama.cpp smoke — one GPU workload at a time)
spark-eugr down
```

Legacy `spark-inference` / stock compose is stopped; use `spark-eugr` only.

## First chat in Open WebUI

1. Open http://sparky:3000
2. Create a local account (first user becomes admin)
3. New chat → model `qwen3.6-35b-a3b-nvfp4`
4. Admin → Models → enable **Usage** capability for token counts on replies

## API test (no UI)

```bash
curl http://sparky:8000/v1/models
curl http://sparky:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-35b-a3b-nvfp4","messages":[{"role":"user","content":"Hello!"}],"max_tokens":64}'
```

## Key paths

| Item | Path |
|------|------|
| Vendor | `/opt/spark/vendor/spark-vllm-docker` |
| Recipe | `/opt/spark/services/eugr-qwen36-local.yaml` |
| CLI | `/usr/local/bin/spark-eugr` |
| Container | `vllm_node` |

Launch uses `VLLM_SPARK_EXTRA_DOCKER_ARGS="-v /models:/models:ro"` and `--solo --daemon --apply-mod mods/fix-qwen3.6-chat-template`.

## Troubleshooting

- **Open WebUI shows no models** — vLLM still loading; `spark-eugr logs` or `curl http://sparky:8000/v1/models`
- **OOM** — lower gpu-memory-utilization in eugr recipe
- **Switching to llama.cpp** — `spark-eugr down` first

## Next

Phase 3b: llama.cpp GGUF smoke — see `docs/LLAMACPP-SMOKE.md`.
