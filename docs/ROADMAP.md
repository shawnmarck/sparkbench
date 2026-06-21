# Spark setup roadmap

Last updated: 2026-06-21

## Phase 1 — Visibility ✅

- [x] SSH keys + hostname (`sparky`, 192.168.0.101)
- [x] Portal at http://sparky/ (System | Models | Chat | Netdata tabs)
- [x] Netdata at http://sparky:19999
- [x] GPU metrics widget (`spark-gpu-metrics` → `/api/gpu`)

## Phase 2 — Model shelf (QNAP) ✅

- [x] NFS/SMB mount at `/mnt/model-shelf` (//192.168.0.99/models)
- [x] Canonical layout under `/models` (mirrors shelf)
- [x] `spark-shelf-push` / `spark-shelf-pull`
- [x] Model inventory dashboard at http://sparky/models.html
- [x] Auto-refresh (`spark-inventory-refresh` timer + inotify)
- [ ] **In progress:** first full shelf backup (`spark-shelf-push --all --background --bwlimit 200`)
- [ ] `HF_TOKEN` / `spark-hf-login` for gated models (Gemma-3-27B blocked without approval)

Deferred from original plan: LRU cache at `/var/lib/spark-model-cache` — not needed yet with 4TB local NVMe.

## Phase 3 — Inference engines

Goal: prove engines on GB10 before the UI bake-off.

### 3a — vLLM (NVFP4) ✅

- [x] eugr [spark-vllm-docker](https://github.com/eugr/spark-vllm-docker) build
- [x] Smoke test: **Qwen3.6-35B-A3B NVFP4** via `spark-eugr`
- [x] Open WebUI at http://sparky:3000 (Phase 3 chat only — not bake-off UI)
- [x] API: http://sparky:8000/v1 — model id `qwen3.6-35b-a3b-nvfp4`

Stock `vllm/vllm-openai:cu130-nightly` fails on this checkpoint (MoE NVFP4 loader gap). eugr recipe works.

See `docs/INFERENCE-SMOKE.md`.

### 3b — llama.cpp (GGUF) — next

- [ ] Build llama.cpp for sm_121 (CUDA 13, GB10)
- [ ] Smoke test: `/models/unsloth/qwen3.6-35b-a3b/gguf/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`
- [ ] Optional: MXFP4_MOE quant after Q4_K_M works

Run **one GPU engine at a time** — stop vLLM (`spark-eugr down`) before llama.cpp load.

See `docs/LLAMACPP-SMOKE.md`. Install: `sudo /opt/spark/install/11-llama-cpp-smoke.sh`

## Phase 4 — UI bake-off (not started)

**Compare:** vLLM Studio vs Rookery (orchestrator UIs)

**Do not compare:** Docker vs eugr — eugr is the engine layer both UIs call.

| Layer | Examples | Bake-off? |
|-------|----------|-----------|
| Engine | eugr vLLM, llama.cpp | Pick what works on Spark first ✅ vLLM |
| Orchestrator UI | vLLM Studio, Rookery | **Yes — next after 3b** |
| API gateway | LiteLLM | Later |

## Phase 5 — Closet / 10Gb

Deferred until desk setup is stable.

## Deferred / later

- Tailscale remote access
- Portal TPS / per-request inference metrics (vLLM `/metrics` scrape)
- Netdata vLLM integration

## Current stack (quick reference)

| Service | URL | Command |
|---------|-----|---------|
| Portal | http://sparky/ | nginx |
| Models | http://sparky/models.html | inventory JSON |
| vLLM | http://sparky:8000/v1 | `spark-eugr up/down/status` |
| Open WebUI | http://sparky:3000 | docker compose (install 06/07) |
| Shelf push | — | `spark-shelf-push --all --background --bwlimit 200` |
| HF auth | — | `spark-hf-login` |
