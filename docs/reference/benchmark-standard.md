# Benchmark standard

Versioned inference benchmarks. **Do not change a published version.** Add a new version instead.

| Version | Method ID | Status | Notes |
|---------|-----------|--------|-------|
| 1.0 | `bench-agent` | legacy | 3×3 short turns, ~256 tok/gen, no long context |
| 2.0 | `bench-agent-v2` | **verify gate** | Recipe-ratio ctx fill + tool roundtrip + agent turns |
| 3.0 / PBM | `perfbench-metrics` | **site / portal display** | Fixed 4k / 50k / 100k fills; skip rungs the recipe cannot load |

`spark models verify set … works` still requires **v2**. PBM does not overwrite `model-verification.yaml` headlines unless a human promotes 4k into verify `tok_s`.

Portal Models + Inference, and [sparkbench.dev](https://sparkbench.dev), sort on PBM `tok_s_4k` when present, else bench v2.

Vendor SWE / Terminal-Bench columns on the public site are not this harness. See [published-evals.md](published-evals.md).

## v2.0 — long-context agent workload

Measure **decode throughput under agent pressure** after a large context fill, not idle short-chat speed.

### Workload (one session)

1. **Context fill** — synthetic repo text targeting **min(50 000, 85% of recipe default ctx)** (~4 chars/token).
2. **Ack turn** — 64 tok assistant reply (prefill stats only; not in primary `tok_s`).
3. **Tool roundtrip** — user requests `record_inventory_delta`; assistant must emit `tool_calls`; tool result fed back.
4. **Agent turns** — two substantive prompts (summarize; design a REST API).

### Measurement

| Metric | Field | Meaning |
|--------|-------|---------|
| Primary score | `tok_s` | Mean decode tok/s (tool + agent generation only) |
| Sessions | `sessions` | 2 measured (+ 1 warmup, not scored) |
| Context target | `context_fill_target_tokens` | Fill target for this recipe |
| Tool success | `tool_roundtrip_ok` | Whether tool_calls were emitted |
| Range | `tok_s_min`, `tok_s_max` | Per-session decode rates |

```bash
spark inference up <golden-profile>
spark inference bench

BENCH_STANDARD=v2 spark inference bench
BENCH_STANDARD=v1 spark inference bench   # legacy compare only
BENCH_V2_TARGET_CTX=50000                 # override fill ceiling
```

- Latest: `data/inference-benchmarks.yaml` (`method: bench-agent-v2`)
- History: `run/inference-benchmark-history.yaml`

Changing fill target, turn count, tool schema, or scored phases requires **v2.1 or v3.0**. Re-bench goldens after a bump. Keep old runs in history.

## Perfbench-metrics (PBM) — fixed fill ladder

Comparable decode tok/s at three fixed fills for every switchable recipe (`works` / `testing`).

| Rung | Fill tokens | Skipped when |
|------|-------------|----------------|
| 4k | 4096 | loaded ctx &lt; 4096 + 8k headroom |
| 50k | 50000 | loaded ctx &lt; 50000 + 8k headroom |
| 100k | 100000 | loaded ctx &lt; 100000 + 8k headroom |

Workload per rung reuses the v2 session shape. Default **1 measured session** per rung (`PBM_MEASURED_SESSIONS`). Optional warmup on the smallest rung.

```yaml
# data/perfbench-metrics.yaml
profiles:
  opencode-qwen36-250k:
    method: perfbench-metrics
    version: "1.0"
    tok_s_4k: 70.0
    tok_s_50k: 58.9
    tok_s_100k: 41.2
    fills: { "4096": { tok_s: 70.0 }, ... }
    skipped: { "100000": "needs>=108192 ctx (loaded=65536)" }
    primary_fill: 50000
```

```bash
spark inference up <profile>
/opt/spark/venv/bin/python /opt/spark/scripts/spark-inference-perfbench-metrics.py
# overnight: spark benchmaster add <profile> --type perf_sweep
```

sparkbench.dev **Full ladder** shows 50k PBM plus the fastest pack per family. Weaker packs tuck under **All recipes**.

## Golden recipe policy (paired with v2)

One golden production profile per `inventory_path`:

- Max-fit context from `spark-inference-context.estimate_max_ctx`
- fp8 KV on eugr where supported
- Single entry in host-local `data/inference-profiles.yaml`
- Lifecycle `works` + `spark models verify set … works`
- Optional shelf push after local validation

See `data/golden-recipes.yaml` and [new-model-golden-benchmark.md](../runbooks/new-model-golden-benchmark.md).
