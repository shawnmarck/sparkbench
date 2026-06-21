# llama.cpp smoke test (Phase 3b)

Goal: run the same Qwen3.6 family via **GGUF** on GB10 for comparison with NVFP4 vLLM.

## Prerequisites

- Phase 3a done (proves the box runs LLMs)
- GGUF on disk: `/models/unsloth/qwen3.6-35b-a3b/gguf/`
  - Start with: `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` (~21 GB)
  - Later: `Qwen3.6-35B-A3B-MXFP4_MOE.gguf` (needs `121a` build + newer llama.cpp)
- **Stop vLLM first:** `spark-eugr down` (single GPU workload)

## Install

```bash
sudo /opt/spark/install/13-llama-cpp-smoke.sh
```

Builds from source into `/opt/spark/vendor/llama.cpp` with `CMAKE_CUDA_ARCHITECTURES=121` (GB10). Installs `spark-llama` CLI.

## Smoke test

```bash
spark-eugr down                    # free GPU
spark-llama up                     # Q4_K_M on :8081
spark-llama status
curl http://sparky:8081/v1/models

curl http://sparky:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-35b-a3b-q4","messages":[{"role":"user","content":"Hello!"}],"max_tokens":64}'
```

Point Open WebUI at `http://host.docker.internal:8081/v1` temporarily, or use curl only for smoke.

## Runtime flags (GB10)

From community DGX Spark guides:

- `-ngl 999` — full GPU offload
- `-fa 1` — flash attention (if build supports it)
- `--no-mmap` — avoids unified-memory mmap quirks on Spark
- `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` — optional tuning for load speed

## Commands

| Command | Purpose |
|---------|---------|
| `spark-llama up` | Start server (default Q4_K_M) |
| `spark-llama down` | Stop server |
| `spark-llama status` | PID + health |
| `spark-llama logs` | Tail server log |

## Compare with vLLM

| | vLLM NVFP4 | llama.cpp Q4_K_M |
|--|------------|------------------|
| Path | `nvidia/.../nvfp4` | `unsloth/.../gguf` |
| Port | 8000 | 8081 |
| CLI | `spark-eugr` | `spark-llama` |

Subjective feel + tok/s (manual or `llama-bench`) — no portal TPS widget yet.

## Troubleshooting

- **Build fails on mxfp4 templates** — use `121` not `121a`, or update llama.cpp; Q4_K_M doesn't need FP4 kernels
- **"no kernel image"** — wrong CUDA arch; must be `121` for GB10
- **Slow load** — try `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` and `--no-mmap`
- **OOM with vLLM still up** — only one engine at a time

## Related

- `docs/INFERENCE-SMOKE.md` — vLLM path (3a)
- `docs/ROADMAP.md` — Phase 3b checklist


## Open WebUI

Open WebUI is wired for **both** backends (install `14-openwebui-dual-backend.sh`):

| Backend | URL | When |
|---------|-----|------|
| vLLM | `http://host.docker.internal:8000/v1` | `spark-eugr up` |
| llama.cpp | `http://host.docker.internal:8081/v1` | `spark-llama up` |

1. Open http://sparky:3000 (same account as before — volume preserved)
2. New chat → model picker → **`qwen3.6-35b-a3b-q4`** (llama) or **`qwen3.6-35b-a3b-nvfp4`** (vLLM)
3. Only one GPU engine at a time — if a model is missing, start the matching backend

Admin → Connections → OpenAI shows both URLs if you need to verify.
