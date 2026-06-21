# Inference smoke test (Phase 3)

Temporary stack to validate vLLM on GB10 before the vLLM Studio vs Rookery bake-off.

## Stack

| Layer | Tool | URL |
|-------|------|-----|
| Engine | vLLM cu130 nightly | http://sparky:8000/v1 |
| Chat UI | Open WebUI | http://sparky:3000 |

Open WebUI is **only for basic chat testing**. It is not part of the Phase 4 orchestrator bake-off.

## Model

- Path: `/models/nvidia/qwen3.6-35b-a3b/nvfp4`
- Served name: `qwen3.6-35b-a3b-nvfp4`
- Format: NVFP4 (vLLM `compressed-tensors` only — not llama.cpp)


## Current status (2026-06-21)

- **Open WebUI** is up at http://sparky:3000 — create a local account on first visit.
- **Stock `vllm/vllm-openai:cu130-nightly`** fails to load `nvidia/Qwen3.6-35B-A3B-NVFP4` with `KeyError: layers.0.mlp.experts.w2_input_scale` (MoE treated as unquantized while checkpoint has NVFP4 scale tensors). This is a known vLLM + ModelOpt loader gap on Spark.
- **Next engine fix:** use [eugr/spark-vllm-docker](https://github.com/eugr/spark-vllm-docker) recipe `qwen3.6-35b-a3b-nvfp4` (Spark-patched vLLM), or try the RedHatAI NVFP4 checkpoint (`compressed-tensors` format).

## Commands

```bash
# Start (pulls images on first run — large download)
spark-inference up

# Logs (first vLLM boot may take 5–15 min for CUDA graph compile)
spark-inference logs

# Status
spark-inference status

# Stop
spark-inference down
```

## First chat in Open WebUI

1. Open http://sparky:3000
2. Create a local account (first user becomes admin)
3. New chat → pick model `qwen3.6-35b-a3b-nvfp4`
4. If no models appear, wait for vLLM to finish loading (`curl http://sparky:8000/v1/models`)

## API test (no UI)

```bash
curl http://sparky:8000/v1/models
curl http://sparky:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-35b-a3b-nvfp4","messages":[{"role":"user","content":"Hello!"}],"max_tokens":64}'
```

## Troubleshooting

- **Open WebUI shows no models** — vLLM still loading; check `docker logs spark-vllm-qwen36`
- **FlashInfer / NVFP4 errors** — see ROADMAP Phase 3 fallbacks (eugr, avarok images)
- **OOM** — lower `--gpu-memory-utilization` or `--max-model-len` in compose.yaml
