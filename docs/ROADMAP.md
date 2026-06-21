# Spark setup roadmap

## Phase 1 — Visibility (current)
- [x] SSH keys
- [x] Staging in `~/spark/`
- [ ] Run `sudo bash ~/spark/install/01-netdata-portal.sh`
- [ ] Verify portal + Netdata from LAN browser

## Phase 2 — Model shelf (QNAP)
- [ ] NFS export from QNAP shared folder
- [ ] Mount at `/mnt/model-shelf`
- [ ] Define canonical directory layout + manifest schema
- [ ] Local cache at `/var/lib/spark-model-cache` with LRU eviction

## Phase 3 — Inference engines (before UI bake-off)
Goal: get **one model** running via CLI/Docker on GB10 — not a UI yet.

- [ ] Spark-compatible vLLM image (eugr / NVIDIA community builds)
- [ ] llama.cpp GPU build for sm_121
- [ ] Smoke test: load one GGUF + one safetensors model

## Phase 4 — UI bake-off (compare orchestrators, not engines)

**What we are comparing:** vLLM Studio vs Rookery (web UIs / lifecycle managers)

**What we are NOT comparing:** Docker vs eugr — eugr (or similar) is the **engine layer**
both UIs would call to run vLLM on GB10 hardware.

| Layer | Examples | Bake-off? |
|-------|----------|-----------|
| Engine | eugr vLLM docker, llama.cpp binary | Pick what works on Spark first |
| Orchestrator UI | vLLM Studio, Rookery | **Yes — compare these** |
| API gateway | LiteLLM (optional) | Later |

## Phase 5 — Closet / 10Gb
- Deferred until desk setup is stable
