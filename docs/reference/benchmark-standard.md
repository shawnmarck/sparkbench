# Benchmark standard

Versioned inference benchmarks for Sparky Model Lab. **Do not change a published version** — add a new version instead.

| Version | Method ID | Status | Notes |
|---------|-----------|--------|-------|
| 1.0 | `bench-agent` | legacy | 3×3 short turns, ~256 tok/gen, no long context |
| 2.0 | `bench-agent-v2` | golden / verify gate | ~recipe-ratio ctx fill + tool roundtrip + agent turns |
| **3.0 / PBM** | `perfbench-metrics` | **display ladder (new)** | Fixed **4k / 50k / 100k** fills; skip rungs the recipe cannot load |

Default golden/verify gate remains **v2** until a human promotes PBM for site display.
**Portal display (Sparky models + inference pages):** use **PBM `tok_s_4k`** for the Bench column and speed sort when present; fall back to bench-agent-v2.
PBM overnight (`loop2`) writes `data/perfbench-metrics.yaml` and does **not** overwrite `model-verification.yaml` headlines unless a human sync promotes 4k into verify `tok_s`.

---

## v2.0 — long-context agent workload

**Goal:** Measure **decode throughput under realistic agent pressure** after a large context fill, not idle short-chat speed.

### Workload (one session)

1. **Context fill** — synthetic repo/architecture text targeting **min(50 000, 85% of recipe default ctx)** estimated tokens (~4 chars/token).
2. **Ack turn** — 64 tok assistant reply (counted in prefill stats, excluded from primary `tok_s`).
3. **Tool roundtrip** — user requests `record_inventory_delta` tool call; assistant must emit `tool_calls`; tool result fed back; follow-up generation.
4. **Agent turns** — two substantive user prompts (summarize context; design REST API).

### Measurement

| Metric | Field | Meaning |
|--------|-------|---------|
| **Primary score** | `tok_s` | Mean **decode** tok/s across measured sessions (tool + agent generation only) |
| Sessions | `sessions` | 2 measured (+ 1 warmup, not scored) |
| Context target | `context_fill_target_tokens` | Fill target for this recipe |
| Tool success | `tool_roundtrip_ok` | Whether tool_calls were emitted |
| Range | `tok_s_min`, `tok_s_max` | Per-session decode rates |

### Environment

```bash
# Default (v2)
spark inference up <golden-profile> --ctx <max> --kv fp8
spark inference bench

# Explicit
BENCH_STANDARD=v2 spark inference bench
BENCH_STANDARD=v1 spark inference bench   # legacy compare only
BENCH_V2_TARGET_CTX=50000                 # override fill ceiling
```

### Storage

- Latest: `data/inference-benchmarks.yaml` (`method: bench-agent-v2`)
- History: `run/inference-benchmark-history.yaml`
- Portal sort uses latest measured `tok_s` for the golden profile

### When to bump version

- Changing fill target, turn count, tool schema, or scored phases → **v2.1 or v3.0**
- Re-benchmark all golden profiles after a version bump; keep old runs in history for comparison

---

## Perfbench-metrics (PBM) — fixed fill ladder

**Goal:** Comparable decode tok/s at **three fixed context fills** for every switchable recipe (`works` / `testing`), independent of the old “~75% of max window” site copy.

### Ladder

| Rung | Fill tokens | When skipped |
|------|-------------|----------------|
| 4k | 4096 | loaded ctx &lt; 4096 + 8k headroom |
| 50k | 50000 | loaded ctx &lt; 50000 + 8k headroom |
| 100k | 100000 | loaded ctx &lt; 100000 + 8k headroom |

Workload per rung reuses the v2 session shape (fill → ack → tool roundtrip → agent turns). Default **1 measured session** per rung (`PBM_MEASURED_SESSIONS`, optional warmup on the smallest rung).

### Storage

```yaml
# data/perfbench-metrics.yaml
profiles:
  nvidia-qwen3-6-27b-eugr:
    method: perfbench-metrics
    version: "1.0"
    tok_s_4k: 12.3
    tok_s_50k: 11.1
    tok_s_100k: 9.8   # omitted if skipped
    fills: { "4096": { tok_s: 12.3, ... }, ... }
    skipped: { "100000": "needs>=108192 ctx (loaded=65536)" }
    primary_fill: 50000
```

### CLI

```bash
spark inference up <profile> --ctx <enough_for_largest_rung> --kv fp8
/opt/spark/venv/bin/python /opt/spark/scripts/spark-inference-perfbench-metrics.py
# or overnight: /opt/spark/run/pbm-loop2.sh
```

### Site / portal display

- Portal models + inference: **Bench 4k** column and sort use PBM `tok_s_4k` (fallback: bench-agent-v2).
- Public site: prefer PBM 4k over “measured at 75% context fill” once `perfbench-metrics.yaml` is published with verification.
- Optional later: fill selector (`4k` / `50k` / `100k`) for alternate sorts.

---

## Golden recipe policy (paired with v2)

One **golden** production profile per `inventory_path`:

- Max-fit context from `spark-inference-context.estimate_max_ctx`
- fp8 KV on eugr where supported
- Single entry in `data/inference-profiles.yaml`
- Lifecycle `works` + `spark models verify set … works`
- Shelf push after local validation

See `data/golden-recipes.yaml` and `scripts/golden-inventory-audit.py`.
