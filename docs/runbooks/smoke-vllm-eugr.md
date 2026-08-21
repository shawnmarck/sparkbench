# vLLM (eugr) smoke

Confirm eugr can load Qwen3.6-35B-A3B NVFP4 and answer on `/v1`.

**Profile:** `opencode-qwen36-250k`  
**Weights:** `/models/nvidia/qwen3.6-35b-a3b/nvfp4`  
**Served name:** `qwen3.6-35b-a3b-nvfp4`

## Why eugr, not stock vLLM

Stock `vllm/vllm-openai` fails this checkpoint (`KeyError: layers.0.mlp.experts.w2_input_scale`). MoE NVFP4 scale tensors need the [eugr/spark-vllm-docker](https://github.com/eugr/spark-vllm-docker) build.

## Prereqs

```bash
sudo bash /opt/spark/install/spark-install engine eugr
sudo bash /opt/spark/install/spark-install gateway   # optional but recommended
spark engine llama down
spark engine ds4 down
```

## Smoke via Model Lab (preferred)

```bash
spark inference up opencode-qwen36-250k
spark inference status          # wait until ready (first boot: 5–15 min, CUDA graphs)
curl -sf http://127.0.0.1:8000/v1/models
curl -sf http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-35b-a3b-nvfp4","messages":[{"role":"user","content":"Hello!"}],"max_tokens":64}'
```

Through the gateway (model `sparky` follows whatever is active):

```bash
curl -sf http://127.0.0.1:9000/v1/models
curl -sf http://127.0.0.1:9000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"sparky","messages":[{"role":"user","content":"Hello!"}],"max_tokens":64}'
```

```bash
spark inference down
```

## Engine-only (bypass profiles)

```bash
spark engine eugr up
spark engine eugr logs
spark engine eugr status
spark engine eugr down
```

Recipe used by the everyday profile: `/opt/spark/services/eugr-qwen36-local.yaml`. Container: `vllm_node`. Vendor: `/opt/spark/vendor/spark-vllm-docker`.

## Open WebUI

http://sparky:3000 — point the connection at `http://sparky:9000/v1` (gateway) or `http://host.docker.internal:8000/v1` (engine). Pick `sparky` or `qwen3.6-35b-a3b-nvfp4`.

## Troubleshooting

- **No models yet** — still loading. `spark engine eugr logs` or `docker logs vllm_node`.
- **OOM** — lower `gpu_memory_utilization` in the eugr recipe.
- **Switching to llama.cpp or ds4** — `spark inference down` first.

Next: [smoke-llamacpp.md](smoke-llamacpp.md). Stack upgrades: [eugr-vllm-upgrade.md](eugr-vllm-upgrade.md).
