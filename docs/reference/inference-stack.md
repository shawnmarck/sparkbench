# Inference stack (Phase 5 spec)

Last updated: 2026-06-21

## Goal

Thin control plane in `/opt/spark/` for **recipe-defined engines**, **one GPU workload at a time** (with optional always-on *small* tier later), and **many logical model names** for agents, Open WebUI, and your gateway.

No third-party orchestrator UI. Portal shows status + switch; recipes live in git.

## Can agents request different models?

**Yes — logically. No — not all at once on one GPU.**

| Layer | Multi-model? | How |
|-------|--------------|-----|
| **Your gateway / API** | Yes | Expose many model IDs (`hermes-14b`, `qwen36-nvfp4`, `qwen36-q4`, …) |
| **Physical GB10** | One heavy slot | Load one recipe at a time; switch = evict + start (minutes for big NVFP4) |
| **Agents** | Yes, with swap latency | Request any registered model; control plane swaps backend if needed |

So agents are not locked to one model forever. They *are* subject to **switch time** when the requested profile is not the active one.

### What other Spark users do

Most solo-Spark setups are simple:

- **eugr `spark-vllm-docker`** + one recipe (`run-recipe.sh --solo`) — common for NVFP4 / safetensors
- **llama.cpp** or **Ollama** for GGUF
- **Hermes Agent** (or similar) pointed at a stable `:8000/v1` endpoint

Power users who want **many model names without manual docker**:

- **[llama-swap](https://github.com/mudler/llama-swap)** — on-demand container/process swap (used in community stacks like [dgx-spark_lite-llm_llama-swap](https://github.com/mARTin-B78/dgx-spark_lite-llm_llama-swap_vllm_llama-cpp_ollama))
- Often paired with a gateway (LiteLLM or custom) in front

We skip LiteLLM here (your product already routes). We borrow the **swap idea** inside `spark inference`.

## Architecture

```text
Consumers
  Hermes agents │ Open WebUI (:3000) │ Your gateway (OSS)
        │
        │  many model IDs
        ▼
  spark inference API (thin)          ← Phase 5
  GET  /api/inference/status
  POST /api/inference/switch { "profile": "qwen36-nvfp4" }
        │
        │  one active profile
        ▼
  Engines (existing)
  spark-eugr  (vLLM / eugr docker)   recipes/*.yaml → eugr format
  spark-llama (llama-server)           recipes/*.yaml → GGUF flags
        │
        ▼
  Portal control panel (status, switch, logs link)
```

Open WebUI stays on dual-backend URLs or moves to gateway-only — TBD when gateway lands on LAN.

## Recipe format (draft)

One file per profile under `/opt/spark/recipes/`:

```yaml
id: qwen36-nvfp4
name: Qwen3.6 35B NVFP4
engine: eugr                    # eugr | llamacpp | ds4
tier: heavy                     # heavy | fast | experimental
eugr_recipe: /opt/spark/services/eugr-qwen36-local.yaml
served_name: qwen3.6-35b-a3b-nvfp4
port: 8000
notes: |
  Primary reasoning model. ~3–5 min cold start.
  Supports tool/reasoning parsers via eugr command block.

# Future: pass-through for new vLLM features
vllm_extra_args: []             # MTP, speculative, etc. when supported

---
id: hermes-14b-q4
name: Hermes 4 14B Q4
engine: llamacpp
tier: fast
model: /models/nous-research/hermes-4-14b/...gguf
served_name: hermes-4-14b
port: 8082
always_on: false                # true when we validate VRAM headroom
llamacpp_args:
  - -ngl 999
  - -c 32768
notes: Agent tier — light coding, grunt work.
```

Registry index: `/opt/spark/data/inference-profiles.yaml` (generated or hand-curated list of enabled profiles).

## CLI (wraps today’s scripts)

Full reference (humans + agents + HTTP): **`docs/reference/spark-cli.md`**.

```bash
spark inference status              # active profile, GPU, port, uptime
spark inference list                # recipes + tier + engine
spark inference up <profile>        # switch (evict current if needed)
spark inference down
spark inference logs <profile>
```

**Agents:** prefer `spark inference help` and `spark inference list` for discovery; or `GET /api/inference/status` when shell is unavailable.

Implementation: profile-driven dispatch over engine scripts (`scripts/spark-eugr`, `scripts/spark-llama`, `scripts/spark-ds4`). eugr and ds4 both use port 8000 (one at a time).

## Switch semantics (for gateway + agents)

1. Client calls gateway with `model: hermes-4-14b`.
2. Gateway maps alias → profile `hermes-14b-q4`.
3. If not active, gateway (or inference API) calls `switch`.
4. Until ready: **503 + Retry-After** or queue (gateway policy).
5. When `/v1/models` lists the model, traffic flows.

Document expected cold-start times per tier in recipe `notes`.

## Portal control panel (minimal)

Add **Inference** tab to http://sparky/:

- Active profile + engine + port
- GPU widget (existing)
- Dropdown: switch profile (confirm + ETA warning for heavy)
- Links: Open WebUI, recipe notes, log tail
- No recipe editor v1 — edit YAML in repo; optional agent/MCP later

## Experimental features (MTP, speculative, etc.)

Add to recipe as **engine-specific passthrough**, not new UI:

- eugr: extend `command:` block in eugr YAML or `vllm_extra_args`
- llamacpp: `llamacpp_args` list

When eugr/vLLM adds a flag, add one recipe field — organic growth.

## Phase 4 (closed)

Bake-off UIs (Rookery, vLLM Studio) were removed from sparky. Phase 5 is this spec.

## Implementation order

1. `recipes/` + `spark inference list|status` (read-only)
2. `spark inference up|down` unified switch
3. HTTP API for gateway integration
4. Portal Inference tab
5. Hermes Agent install → point at `hermes-14b-q4` (or gateway)
6. Optional: llama-swap-style idle eviction (later)
7. Optional: MCP ops agent (recipes + notes)

## Open questions

- [ ] Always-on small + on-demand heavy on same GB10 — measure VRAM before enabling
- [ ] Single port `:8000` vs per-tier ports — gateway may prefer one upstream with swap
- [ ] Open WebUI: direct backends vs gateway-only


### ds4 (DwarfStar) recipe fields

```yaml
engine: ds4
model: /models/antirez/deepseek-v4-flash/gguf/DeepSeek-V4-Flash-….gguf
served_name: deepseek-v4-flash
port: 8000
ds4_args:
  - -c
  - "32768"
```

Scaffold: `spark recipe scaffold antirez/deepseek-v4-flash ds4` or auto-detect when catalog marks `engine: ds4`.
