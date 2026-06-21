# Phase 4 bake-off notes

## Rookery — disqualified on GB10

Rookery v0.1.5 initializes NVML but reports `gpu=None` on DGX Spark (GB10).
Dashboard shows no GPU; chat/GPU features unreliable. Service disabled.

Config retained at `/ops/rookery/config.toml` for reference only.

## vLLM Studio — primary candidate

Supports **both** backends via recipes:

| Backend | Use on Spark |
|---------|----------------|
| `llamacpp` | GGUF under `/models/.../gguf/` — uses `VLLM_STUDIO_LLAMA_BIN=/opt/spark/bin/llama-server` |
| `vllm` | NVFP4 safetensors — prefer **Docker** runtime with eugr image (`vllm-node`) until pip vLLM supports GB10 MoE NVFP4 |

URL: http://sparky:3080  
Controller: http://sparky:8080

### First-time setup (UI)

1. Open http://sparky:3080 — setup wizard
2. Models directory: `/models`
3. Install **llama.cpp** runtime (points at bundled binary)
4. Create recipe: backend **llamacpp**, model path Qwen3.6 Q4 GGUF
5. For vLLM: create recipe backend **vllm**, runtime target **docker**, image from eugr stack — or keep using `spark-eugr` externally and use Studio for llama.cpp lifecycle first

Only one recipe loaded on GPU at a time.

Install: `sudo /opt/spark/install/17-vllm-studio.sh`
