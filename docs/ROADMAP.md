# Spark setup roadmap

**This is the plan.** Status, phases, URLs, and what to build next.  
Last updated: 2026-06-21

---

## Why this exists

Homelab control plane for **sparky** (`192.168.0.101`, DGX Spark / GB10):

| Use case | Tool |
|----------|------|
| Local agents (Hermes) — grunt work, light coding | Hermes Agent → local `:v1` endpoint |
| Private human chat | Open WebUI `:3000` |
| OSS gateway — routing, guardrails, “free” local tier | Your gateway product (separate repo) → spark backends |

**Not on sparky:** LiteLLM (gateway product already covers routing). Orchestrator UIs (Rookery, vLLM Studio) were tried and removed.

---

## Architecture (target)

```text
Hermes agents │ Open WebUI │ Your gateway
        │ many model IDs
        ▼
spark-inference (Phase 5)     status + switch API
        │ one GPU profile at a time
        ▼
spark-eugr (:8000)  │  spark-llama (:8081)
        ▼
/opt/spark portal + inventory + recipes/
```

**Rule:** One heavy GPU workload at a time. Many logical model names; switching = evict + load (minutes for big NVFP4).

---

## Current state (today)

| Layer | Status |
|-------|--------|
| Portal, Netdata, GPU widget, inventory | ✅ Running |
| NAS shelf mount + push/pull | ✅ |
| eugr vLLM (`spark-eugr`) | ✅ Proven; **stopped** right now |
| llama.cpp (`spark-llama`) | ✅ Proven; **running** Gemma 4 12B Coder Q4 (`gemma4-12b-coder-q4`) on `:8081` |
| Open WebUI | ✅ `:3000` |
| Recipes | 🟡 `gemma4`, `qwen36-q4`, `qwen36-nvfp4` |
| `spark-inference` control plane | 🟡 CLI + API + portal Inference tab; Hermes + gateway next |
| Hermes Agent | ❌ Not installed |

---

## Phase 1 — Visibility ✅

- [x] SSH, hostname `sparky`, LAN `192.168.0.101`
- [x] Portal http://sparky/ (System · Models · Chat · Netdata)
- [x] Optional Theme B nebula (constellation toggle)
- [x] Netdata http://sparky:19999
- [x] GPU metrics http://sparky/api/gpu

---

## Phase 2 — Model shelf ✅

- [x] SMB mount `/mnt/model-shelf` (QNAP `192.168.0.99`)
- [x] Canonical tree `/models` (mirrors shelf)
- [x] `spark-shelf-push` / `spark-shelf-pull`
- [x] Inventory dashboard http://sparky/models.html
- [x] Auto-refresh (`spark-inventory-refresh` + inotify)
- [x] First full shelf push (background)
- [x] `spark-hf-login` for Hugging Face
- [ ] Second shelf push for Gemma 4 trees (after downloads)

Deferred: LRU cache at `/var/lib/spark-model-cache` — not needed with 4 TB local NVMe.

---

## Phase 3 — Inference engines ✅

Prove both engines on GB10 before building the control plane.

### 3a — eugr vLLM (NVFP4) ✅

- [x] [spark-vllm-docker](https://github.com/eugr/spark-vllm-docker) build (`vllm-node`)
- [x] Qwen3.6-35B-A3B NVFP4 via `spark-eugr`
- [x] Open WebUI `:3000` (private chat)
- [x] API http://sparky:8000/v1 — `qwen3.6-35b-a3b-nvfp4`

Stock `vllm/vllm-openai` fails on this checkpoint (MoE NVFP4 gap). eugr works.

Runbook: [`runbooks/smoke-vllm-eugr.md`](runbooks/smoke-vllm-eugr.md)

### 3b — llama.cpp (GGUF) ✅

- [x] `llama-server` built for sm_121 / GB10 (`/opt/spark/bin/llama-server`)
- [x] Qwen3.6 Q4_K_M smoke test
- [x] Gemma 4 12B Coder (Fable5×Composer2.5) Q4 smoke test — `testing` tag, `spark_status: works`
- [ ] Optional: MXFP4_MOE quant for Qwen3.6 GGUF

Runbook: [`runbooks/smoke-llamacpp.md`](runbooks/smoke-llamacpp.md)

---

## Phase 4 — Orchestrator UI bake-off ✅ closed

Tried **Rookery** (GB10 GPU invisible) and **vLLM Studio** (works with hacks; not a good stack manager). Both **removed**.

**Keep:** Open WebUI for chat only.

**Decision:** Thin control plane in `/opt/spark` (Phase 5), not a third-party orchestrator UI.

---

## Phase 5 — Inference stack 🔜 (next)

**Goal:** Recipe-defined profiles, unified switch CLI/API, portal status panel.

Spec detail: [`reference/inference-stack.md`](reference/inference-stack.md)

### Build order

1. [x] Expand `recipes/` — Qwen NVFP4, Qwen Q4 (Hermes fast tier when GGUF on disk)
2. [x] **`spark-inference`** CLI — `status`, `list`, `up <profile>`, `down`, `logs` (wrap `spark-eugr` + `spark-llama`)
3. [x] **HTTP API** — `GET /api/inference/status`, `POST /api/inference/switch`, `POST /api/inference/down`
4. [x] **Portal Inference tab** — active profile, switch, stop, log tail (no recipe editor v1)
5. [ ] **Hermes Agent** — install, point at fast local tier
6. [ ] Gateway integration — model aliases → profiles, handle cold-start (503/retry)
7. [ ] Later: idle eviction, MCP ops agent for recipes/notes

### Already started

- [x] `recipes/gemma4-12b-coder-q4.yaml`, `qwen36-q4-llama.yaml`, `qwen36-nvfp4.yaml`
- [x] `data/inference-profiles.yaml` (profile index)
- [x] `scripts/spark-inference.py` — profile switch CLI
- [x] `scripts/spark-inference-api.py` — portal/gateway HTTP API (`:8767` via nginx)
- [x] Portal **Inference** nav tab — switch UI + logs

---

## Phase 6 — Closet / 10Gb ⏸

Deferred until desk setup is stable.

---

## Deferred / later

- Tailscale remote access
- Portal TPS / vLLM `/metrics` scrape
- Netdata vLLM integration
- Always-on small + on-demand heavy (only if VRAM headroom proven)
- Experimental flags (MTP, speculative decode) via recipe passthrough — organic, no new UI

---

## Quick reference

| Service | URL | Command |
|---------|-----|---------|
| Portal | http://sparky/ | nginx |
| Models | http://sparky/models.html | `spark-inventory-build` |
| vLLM | http://sparky:8000/v1 | `spark-eugr up/down/status` |
| llama.cpp | http://sparky:8081/v1 | `spark-llama up/down/status` |
| Open WebUI | http://sparky:3000 | docker |
| Netdata | http://sparky:19999/v3/ | — |
| Shelf | — | `spark-shelf-push`, `spark-shelf-pull` |

---

## Repo layout

```
/opt/spark/
├── AGENT.md           Agent quick start
├── portal/            LAN UI
├── scripts/           spark-* CLIs
├── install/           sudo install scripts
├── data/              model-catalog.yaml, model-verification.yaml
├── recipes/           inference profiles (Phase 5)
├── README.md          Repo homepage + doc index
├── docs/              ROADMAP + guides/runbooks/reference
└── services/          eugr recipe yaml, compose files
```

Staging: `~/spark` → promoted by install scripts.

---

## Documentation

See [`README.md`](../README.md) for the doc index and repo homepage.
