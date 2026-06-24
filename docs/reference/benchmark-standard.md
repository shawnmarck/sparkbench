# Benchmark standard

Versioned inference benchmarks for Sparky Model Lab. **Do not change a published version** — add a new version instead.

| Version | Method ID | Status | Notes |
|---------|-----------|--------|-------|
| 1.0 | `bench-agent` | legacy | 3×3 short turns, ~256 tok/gen, no long context |
| **2.0** | `bench-agent-v2` | **current** | ~50k ctx fill + tool roundtrip + agent turns |

Default since 2026-06-24: **v2** (`BENCH_STANDARD=v2`, overridable with `BENCH_STANDARD=v1`).

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

## Golden recipe policy (paired with v2)

One **golden** production profile per `inventory_path`:

- Max-fit context from `spark-inference-context.estimate_max_ctx`
- fp8 KV on eugr where supported
- Single entry in `data/inference-profiles.yaml`
- Lifecycle `works` + `spark models verify set … works`
- Shelf push after local validation

See `data/golden-recipes.yaml` and `scripts/golden-inventory-audit.py`.
