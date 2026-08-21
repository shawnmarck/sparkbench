# llama.cpp smoke

Same Qwen3.6 family via GGUF, for a bake-off against NVFP4 vLLM.

**Profile:** `qwen36-q4-llama`  
**Weights:** `/models/unsloth/qwen3.6-35b-a3b/gguf/`  
Start with `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`.

## Prereqs

```bash
sudo bash /opt/spark/install/spark-install engine llama
spark inference down            # free eugr / ds4
```

Build is `CMAKE_CUDA_ARCHITECTURES=121` (GB10) into `/opt/spark/vendor/llama.cpp`.

## Smoke via Model Lab (preferred)

```bash
spark inference up qwen36-q4-llama
spark inference status
curl -sf http://sparky:8081/v1/models
curl -sf http://sparky:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-35b-a3b-q4","messages":[{"role":"user","content":"Hello!"}],"max_tokens":64}'
```

Gateway (after `spark-install gateway`):

```bash
curl -sf http://sparky:9000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"sparky","messages":[{"role":"user","content":"Hello!"}],"max_tokens":64}'
```

```bash
spark inference down
```

## Engine-only

```bash
spark engine eugr down
spark engine llama up
spark engine llama status
spark engine llama logs
spark engine llama down
```

## Runtime flags (GB10)

- `-ngl 999` — full GPU offload
- `-fa 1` — flash attention when the build supports it
- `--no-mmap` — avoids unified-memory mmap quirks
- `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` — optional load-speed tweak

## Compare with vLLM

| | vLLM NVFP4 | llama.cpp Q4_K_M |
|--|------------|------------------|
| Profile | `opencode-qwen36-250k` | `qwen36-q4-llama` |
| Path | `nvidia/.../nvfp4` | `unsloth/.../gguf` |
| Port | 8000 | 8081 |
| CLI | `spark engine eugr` | `spark engine llama` |

Fair tok/s: `spark inference bench` (v2) or a Benchmaster `perf_sweep`.

## Open WebUI

Prefer the gateway (`http://sparky:9000/v1`, model `sparky`). Direct engine URLs if you skip the gateway:

| Backend | URL |
|---------|-----|
| vLLM | `http://host.docker.internal:8000/v1` |
| llama.cpp | `http://host.docker.internal:8081/v1` |

Only one GPU engine at a time. If a model is missing from the picker, that backend is down.

## Troubleshooting

- **Build fails on mxfp4 templates** — use arch `121` not `121a`. Q4_K_M does not need FP4 kernels.
- **"no kernel image"** — CUDA arch must be `121` for GB10.
- **Slow load** — try `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` and `--no-mmap`.
- **OOM with vLLM still up** — `spark inference down` first.

Related: [smoke-vllm-eugr.md](smoke-vllm-eugr.md).
