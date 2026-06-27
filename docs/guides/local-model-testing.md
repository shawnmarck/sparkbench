# Local model testing — Sparky SOP (living doc)

> **Status:** draft / growing  
> **Host:** `sparky` (`ssh sparky`, key auth)  
> **Repo:** `/opt/spark`  
> **Purpose:** How agents (and humans) bench every completed model, fix stack issues without regressions, and run long work asynchronously so chat stays responsive.

This file lives in `docs/guides/local-model-testing.md` in the **sparkbench** repo (`/opt/spark` on host).

---

## Quick reference

| What | Where |
|------|--------|
| **Workspace orientation** | `docs/guides/local-model-testing.md` |
| Project orientation (production) | `AGENTS.md` (this repo) |
| CLI reference | `/opt/spark/docs/reference/spark-cli.md` |
| Inference stack | `/opt/spark/docs/reference/inference-stack.md` |
| Model inventory (UI) | `http://sparky/models.html` → `portal/models.json` |
| Benchmark results (latest) | `/opt/spark/data/inference-benchmarks.yaml` |
| **Benchmark history** (all runs) | `/opt/spark/run/inference-benchmark-history.yaml` (legacy: `data/inference-benchmark-history.yaml`) |
| **OpenAI gateway (agents)** | `http://sparky:9000/v1` — OpenCode, Hermes, etc. |
| OpenCode profiles | `opencode-qwen36-250k` (256k MoE) · `opencode-qwen27-dflash-262k` (262k DFlash) |
| **Audit log (agents)** | `/opt/spark/benchmark-audit.log` |
| **Async worker log** | `/opt/spark/logs/bench-queue-worker.log` |
| Async worker script | `/opt/spark/run/bench-queue-worker.sh` |
| **DwarfStar (ds4) smoke** | `docs/runbooks/smoke-ds4.md` |
| **Golden audit / new models** | `docs/runbooks/new-model-golden-benchmark.md`, `scripts/golden-inventory-audit.py` |
| **Bench standard v2** | `docs/reference/benchmark-standard.md` |
| ds4 pin / install | `data/ds4-dwarfstar.yaml`, `install/22-ds4-dwarfstar.sh` |

```bash
ssh sparky 'spark inference list'
ssh sparky 'spark inference status'
ssh sparky 'spark recipe list'
ssh sparky 'tail -f /opt/spark/logs/bench-queue-worker.log'
ssh sparky 'tail -20 /opt/spark/benchmark-audit.log'
```

---

## Goals

1. **100% bench coverage** — every model with a **completed download** gets `best_bench_tok_s` in `portal/models.json` (sortable in UI).
2. **One model at a time** — single GPU engine (eugr vLLM *or* llama.cpp), never parallel loads.
3. **Fix before proceed** — if CLI, recipe, or inference stack breaks, fix in `/opt/spark`, **commit locally**, log in audit file, then continue.
4. **No regressions** — after stack changes, smoke-check a **known-good profile** before resuming the queue.
5. **Don't interrupt downloads** — skip models actively downloading; never kill `hf download` / `spark-download-*` jobs.
6. **Async by default** — long loads and benches run in background; user can keep chatting with the agent.
7. **Dynamic queue** — as download batches finish, refresh inventory and auto-enqueue any model still missing `best_bench_tok_s` (do not maintain a static list by hand).

---

## Dynamic queue (new downloads)

The download pipeline runs separately (`spark-download-queue-tail.sh`, per-model scripts). **When a download finishes**, it appears in `portal/models.json` after inventory refresh.

The benchmark worker **discovers work automatically**:

```bash
python3 /opt/spark/run/bench-queue-discover.py              # unbenched (default)
python3 /opt/spark/run/bench-queue-discover.py --mode refire-import
python3 /opt/spark/run/bench-queue-discover.py --mode all
# → lines: <inventory_path> <eugr|llamacpp|ds4>
```

Rules:
- **Include (unbenched):** any model in `models.json` without `best_bench_tok_s`, with ready weights on disk (`nvfp4/`, `hf/`, `fp8/`, `prismaquant/`, or main `.gguf` ≥500MB excluding mmproj-only).
- **Include (refire-import):** already has `best_bench_tok_s` but recipe history is import-only or empty; requires existing recipe for `(inventory_path, engine)`.
- **Skip:** actively downloading (per-model `pgrep` on `hf download` / `spark-download` for that path).
- **Skip:** DFlash-only aux trees (`z-lab/*/dflash`, &lt;5GB).
- **Engine pick:** vLLM subdirs → `eugr`; catalog/pin `ds4` + GGUF → `ds4` (`antirez/deepseek-v4-flash`); other GGUF → `llamacpp` (skips `deepseek4` arch unless ds4-pinned).

Worker loop (`bench-queue-worker.sh`):
1. `spark models inventory` (pick up new models)
2. Run discover (`--mode unbenched`) → bench each job one at a time
3. If unbenched queue empty and `BENCH_REFIRE_IMPORTED=1`, run `--mode refire-import`
4. After each successful bench: `spark inference bench note …` + log `bench history` snippet
5. Sleep 5 min → repeat until both queues empty, then keep heartbeating for new downloads

**Do not kill download jobs.** Bench worker and download queue run concurrently; worker skips models mid-download.

---

## Prerequisites

- SSH: `ssh sparky` (passwordless key)
- CLI on host: `/usr/local/bin/spark`
- One GPU workload at a time: eugr, llama.cpp, and ds4 are mutually exclusive (`spark inference up` evicts the others). eugr and ds4 both bind **:8000**.

---

## What “benched” means

Successful run of:

```bash
spark inference bench
```

- Multi-turn **agent-style** timing on the **active profile** (default: 3 sessions × 3 turns).
- **Latest** result saved to `data/inference-benchmarks.yaml` and merged into `portal/models.json` as `best_bench_tok_s`.
- **Every run** appended to `run/inference-benchmark-history.yaml` (full timeline; UI Models detail panel).
- Auto-run gets a `system_note` with session stats; agents add a human `note` after each queue bench.
- Also updates `data/model-verification.yaml` tok_s fields for the recipe’s `inventory_path`.

**Profile must be up and ready** (`curl http://127.0.0.1:8000/v1/models` or `:8081` for llama) before benching.

### Benchmark history (read / annotate)

```bash
# List runs for a profile (newest first)
spark inference bench history <profile> [--json] [--limit N]

# Latest snapshot (includes latest_run_id)
spark inference bench latest <profile> [--json]

# One run detail
spark inference bench show <profile> <run_id> [--json]

# Agent or human annotation (does not replace system_note)
spark inference bench note <profile> <run_id> "baseline before MTP tweak"
```

HTTP: `GET /api/inference/benchmarks/<profile>/history`, `PATCH .../runs/<run_id>` with `{"note":"..."}`.

Cards and inventory sort still use **latest** `tok_s`; history is for comparisons and audit.

### Refiring pre-history benches

Runs before the history feature may exist only as **migrated import** entries (`source: import`, one row, no agent note). Re-run to append a proper `source: auto` run with full session stats:

```bash
python3 /opt/spark/run/bench-queue-discover.py --mode refire-import
# then normal scaffold → up → bench workflow for each line
```

The async worker does this automatically when the unbenched queue is empty (`BENCH_REFIRE_IMPORTED=1`, default). Refires get note: `agent-queue refire … replaces import-only history`.

---

## Standard workflow (single model)

Model Lab lifecycle:

```text
scaffold → testing → inference up → wait ready → bench → (optional promote)
```

```bash
# 1. Scaffold draft recipe (if none exists)
spark recipe scaffold <lab/slug> <eugr|llamacpp>

# 2. Mark testing (required before switch)
spark recipe testing <profile-id>

# 3. Switch engine (evicts current)
spark inference up <profile-id>

# 4. Poll until ready (heavy models: minutes)
spark inference status
curl -sf http://127.0.0.1:8000/v1/models   # eugr
curl -sf http://127.0.0.1:8081/v1/models   # llamacpp

# 5. Benchmark (can take several minutes)
spark inference bench

# 6. Verify + free GPU
grep <profile-id> /opt/spark/data/inference-benchmarks.yaml
spark models inventory   # refresh portal/models.json
spark inference down
```

Log every step in `/opt/spark/benchmark-audit.log`:

```text
[ISO8601] START: <inventory_path> (<engine>)
[ISO8601] FIX: <what> (commit <hash> if applicable)
[ISO8601] DONE: <inventory_path> -> <tok/s> tok/s (<engine>)
[ISO8601] FAIL/BLOCKED: <reason>
```

---

## Queue: what to bench vs skip

### Bench when

- Model appears in `portal/models.json` with `status: ready` (or weights present on disk).
- Variant subdir exists: `nvfp4/`, `hf/`, `fp8/`, `gguf/`, `prismaquant/`, etc.
- No active download **for that specific model path**.

### Skip when

- **Download in progress** for that model (check `pgrep -af "local-dir /models/<lab/slug>"`).
- **Auxiliary / not inference targets** — e.g. `z-lab/*/dflash` (DFlash sidecars, hundreds of MB, not full models).
- **Untracked / incomplete** — tiny dir size vs expected (e.g. 737 MB for a 35B MoE).

### Engine choice

| Weights | Engine | Notes |
|---------|--------|--------|
| `nvfp4/` | `eugr` | MoE NVFP4; use `--moe-backend marlin` |
| `hf/` | `eugr` | Dense / HF safetensors |
| `fp8/` | `eugr` | Qwen FP8 builds |
| `prismaquant/` | `eugr` | Community quant vLLM layouts |
| `gguf/` | `llamacpp` | Prefer **Q4_K_M** over larger quants |

### Multiple llama.cpp builds (planned)

Some GGUFs need a newer or forked build (e.g. **`deepseek4`** — not in the current stable `/opt/spark/bin/llama-server`).

**Recommended shape:** keep `engine: llamacpp`, add **`llamacpp_variant`** on recipes:

| Field | Purpose |
|-------|---------|
| `llamacpp_variant: stable` | Default GB10 build (`/opt/spark/bin/llama-server`) |
| `llamacpp_variant: dsv4` | Experimental build for `deepseek4` arch |

Registry: `/opt/spark/config/llamacpp-variants.yaml` (see `projects/sparky/llamacpp-variants.yaml.example`) maps variant → `bin`, `pid_file`, `log_file`, `architectures`.

**Selection:** scaffold/discover reads GGUF `general.architecture` and picks the variant whose `architectures` list matches. Still **one GPU process at a time** — variant only chooses which binary `spark-llama` launches.

Until `dsv4` is installed, discover **skips** GGUF-only models whose arch isn't in the stable list (e.g. `0xsero/deepseek-v4-flash-spark`).

---

## Async operation (chat-safe)

Long model loads block for minutes. **Do not hold the user’s chat hostage.**

### Pattern

1. **Background worker on sparky** — `/opt/spark/run/bench-queue-worker.sh`
   - Processes queue one model at a time.
   - Appends to `benchmark-audit.log` and `logs/bench-queue-worker.log`.
   - Emits machine-readable events: `AGENT_BENCH_EVENT {"event":"done|fail|skip|finished", ...}`

2. **Start worker** (non-blocking):

   ```bash
   ssh sparky 'nohup /opt/spark/run/bench-queue-worker.sh >> /opt/spark/logs/bench-queue-worker.log 2>&1 &'
   ```

3. **Agent monitors** log stream (local `tail -F` over SSH) with wake on `^AGENT_BENCH_EVENT`.
4. **User keeps chatting** — agent handles wake notifications and reports status on request (“bench status?”).

### Loop skill (Cursor)

Use `/loop` or **dynamic self-pacing** when:

- Retrying queue after downloads finish (heartbeat every ~5 min).
- Waiting for vLLM ready (event: API responds on `/v1/models`).

Do **not** use fixed tight loops for multi-minute loads — prefer event wakes + long fallback heartbeat.

---

## Regression policy

After **any** change to `scripts/spark-inference.py`, eugr service YAML generation, or benchmark logic:

1. **Commit** the fix on sparky (`cd /opt/spark && git commit ...`).
2. **Smoke one known-good profile** (e.g. `qwen36-nvfp4` or `microsoft-phi-4-eugr`):
   - `spark inference up <profile>`
   - Confirm `/v1/models` lists the model
   - Optional: short bench or single completion
3. **Then** resume queue.

Fixes for model A must not break model B — if a change is model-specific, prefer **per-recipe eugr YAML** or conditional scaffold logic over global behavior changes.

---

## Stack fixes learned (2026-06-21)

These were committed to `/opt/spark` during the first full bench pass.

| Issue | Symptom | Fix |
|-------|---------|-----|
| Scaffold only found `nvfp4/` | `RuntimeError: no nvfp4 weights` for phi-4, hermes, deepseek | Discover `hf/`, `fp8/`, `prismaquant/` too |
| `max_model_len` too high | vLLM ValidationError (phi-4: 16384 limit) | `infer_max_model_len()` from `config.json` |
| FlashInfer + multimodal | `partial multimodal token full attention not supported` (gemma-26b) | Omit `--attention-backend flashinfer` for MM configs |
| fastsafetensors load crash | Engine dies at 0% shards (gemma-26b HF) | `--load-format auto` for multimodal |
| High GPU mem on large MM MoE | OOM during load | Lower `gpu_memory_utilization` (0.70), shorter `max_model_len` in eugr YAML |
| GGUF picks largest quant | Q5 hung at “fitting params to device memory” | Prefer Q4_K_M / Q4_K_XL in `discover_gguf()` |
| Download check too broad | Skipped all models while *unrelated* model downloaded | `model_downloading()` per inventory path only |
| Text-only MM checkpoint | `visual.blocks.*` weights not in checkpoint (AgentWorld 35B) | `--language-model-only` on eugr serve; scaffold reads `language_model_only` in config |
| Nested `text_config` ctx | Native ctx stuck at 16384 for Qwen3.5 MoE | `infer_max_model_len()` also reads `text_config.max_position_embeddings` |
| Grok `tool_choice: auto` | 400 Bad Request on gateway | `--enable-auto-tool-choice` + `--tool-call-parser qwen3_xml` on Qwen eugr recipes |

---

## Troubleshooting

### vLLM never becomes ready

```bash
docker logs vllm_node 2>&1 | tail -50
spark engine eugr status
```

Common causes: wrong `max_model_len`, flashinfer on multimodal, OOM, wrong weight path.

### llama.cpp stuck at “fitting params”

- Try **smaller quant** (Q4 not Q5).
- Ensure eugr is fully down (`spark engine eugr down`).
- Check `/opt/spark/logs/llama-server.log`.

### Benchmark tok/s very low + GPU ~2%

Observed on **dense** models (phi-4 ~8 tok/s, deepseek-32b ~3.5 tok/s) while MoE NVFP4 hits ~70+ tok/s.

Likely causes (investigate):

- Bench sends **one sequential** chat session at a time → GPU underutilized on GB10.
- Small dense models don’t saturate memory bandwidth at batch=1.
- **TODO:** compare sequential vs N concurrent completions; consider concurrent bench mode for UI sort fairness.

Check during generation:

```bash
nvidia-smi --query-gpu=utilization.gpu,power.draw,memory.used --format=csv
curl -sf http://sparky/api/gpu
```

### Engine switch conflicts

- `spark inference down` before switching families.
- If docker stuck: `spark engine eugr down`, verify `docker ps | grep vllm`.

---

## Task management conventions

### For agents

- **One active bench at a time** — no parallel `spark inference up`.
- **Todo list** for remaining models; mark done after `best_bench_tok_s` appears in inventory.
- **Audit everything** — if something goes wrong later, `benchmark-audit.log` is the paper trail.
- **Commit fixes** before moving on — never leave stack fixes uncommitted.
- **User can interrupt** — safe to stop polling; leave worker running or restart from queue.

### Status report template

```text
Coverage: N/M models benched
Active: <profile or none>
Downloads: <in-progress list or none>
Last done: <model> @ <tok/s>
Blocked: <model + reason>
Next: <model>
```

---

## Files to update when process changes

| Change | Update |
|--------|--------|
| New failure mode / fix | This doc + commit in `/opt/spark` |
| New queue model | `bench-queue-worker.sh` QUEUE array |
| Scaffold behavior | `scripts/spark-inference.py` + regression smoke |
| Official runbook | Eventually mirror to `/opt/spark/docs/runbooks/local-model-testing.md` |

---

## Session snapshot (2026-06-21)

**Benched (10+):** gemma-4-12b-coder, gemma-4-12b-it, gemma-4-26b-a4b-it, phi-4, hermes-4-14b, qwen3-30b-a3b, qwen3.6-35b nvfp4+gguf, qwen3-coder-30b, deepseek-r1-distill-32b.

**Pending:** unsloth/qwen3.6-27b (eugr + llamacpp), qwen/qwen3.6-27b, rdtand/qwen3.6-27b, qwen/qwen3-coder-next (wait for download).

**Open investigation:** GPU utilization vs bench methodology for dense models.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-06-21 | Benchmark history + notes in worker; refire import-only runs when queue idle |
| 2026-06-21 | Dynamic discover queue — auto-pick new downloads (`bench-queue-discover.py`) |
