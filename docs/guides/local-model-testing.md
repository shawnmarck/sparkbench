# Local model testing

How to bench models on Sparky without blocking chat and without running two GPUs.

Host: `sparky` (`ssh sparky`). Repo: `/opt/spark`.

## Quick reference

| What | Where |
|------|--------|
| CLI | [spark-cli.md](../reference/spark-cli.md) |
| Inference stack | [inference-stack.md](../reference/inference-stack.md) |
| Portal | http://sparky/ · Models: http://sparky/models.html |
| Latest bench | `data/inference-benchmarks.yaml` |
| Bench history | `run/inference-benchmark-history.yaml` |
| PBM ladder | `data/perfbench-metrics.yaml` |
| Gateway | http://sparky:9000/v1 — model `sparky` |
| Agent profiles | `opencode-qwen36-250k` · `opencode-qwen27-dflash-262k` |
| Overnight queue | [benchmaster-agent.md](../runbooks/benchmaster-agent.md) · http://sparky/#benchmaster |
| Golden audit | [new-model-golden-benchmark.md](../runbooks/new-model-golden-benchmark.md) |
| Bench v2 / PBM | [benchmark-standard.md](../reference/benchmark-standard.md) |

```bash
ssh sparky 'spark inference status'
ssh sparky 'spark inference list'
ssh sparky 'spark benchmaster status'
ssh sparky 'tail -F /opt/spark/logs/benchmaster.log'
```

## Rules

1. **One GPU at a time.** `spark inference up` evicts the other engines. eugr and ds4 both bind :8000.
2. **`works` only after bench v2.** A `/v1/models` 200 is not enough.
3. **Do not kill downloads.** Skip a model that is still pulling.
4. **Pause Benchmaster** before a manual `up` if the queue mode is `running`.
5. **Fix the stack, then smoke**, then resume the queue.

## What “benched” means

```bash
spark inference up <profile>
# wait until ready
spark inference bench
```

Bench v2 is the verify gate: long-ctx fill, tool roundtrip, agent turns. Latest result lands in `data/inference-benchmarks.yaml` and `best_bench_tok_s` in `portal/models.json`. Every run appends to `run/inference-benchmark-history.yaml`.

PBM is the public ladder (4k / 50k / 100k). Benchmaster `perf_sweep` jobs write it. Portal and sparkbench.dev sort on PBM 4k when present, else bench v2.

```bash
spark bench history <profile> [--json] [--limit N]
spark bench latest <profile>
spark bench note <profile> <run_id> "baseline before MTP tweak"
```

HTTP: `GET /api/inference/benchmarks/<profile>/history`, `PATCH .../runs/<run_id>` with `{"note":"..."}`.

## Single model

```text
scaffold → testing → inference up → wait ready → bench → (optional promote)
```

```bash
spark recipe scaffold <lab/slug> <eugr|llamacpp|ds4>
spark recipe testing <profile-id>
spark inference up <profile-id>
spark inference status
# eugr/ds4:
curl -sf http://127.0.0.1:8000/v1/models
# llama.cpp:
curl -sf http://127.0.0.1:8081/v1/models

spark inference bench
spark models inventory
spark inference down
```

Known-good smoke after a stack change: `opencode-qwen36-250k` or `gemma4-12b-coder-q4`.

### When to bench vs skip

**Bench** when `portal/models.json` shows weights ready (`nvfp4/`, `hf/`, `fp8/`, `gguf/`, `prismaquant/`) and no download is running for that path.

**Skip** DFlash-only sidecar trees (`z-lab/*/dflash`, tiny dirs) and incomplete pulls.

| Weights | Engine |
|---------|--------|
| `nvfp4/`, `hf/`, `fp8/`, `prismaquant/` | `eugr` |
| `gguf/` | `llamacpp` (prefer Q4_K_M) |
| ds4-pinned DeepSeek V4 Flash | `ds4` |

## Overnight: Benchmaster

The old `bench-queue-worker.sh` path is gone. Overnight work is Benchmaster.

| Job | Where it runs |
|-----|----------------|
| `perf_sweep`, `ctx_ladder`, `kv_sweep`, `golden_workflow` | Sparky GPU worker |
| `intel_eval` | Remote Harbor worker (Mac / techno) |

```bash
spark benchmaster status
spark benchmaster queue
spark benchmaster control resume    # queue starts paused after install
spark benchmaster add opencode-qwen36-250k --type perf_sweep
```

Portal: http://sparky/#benchmaster. Supervise, do not replace the worker. Full runbook: [benchmaster-agent.md](../runbooks/benchmaster-agent.md).

## Regression policy

After edits to `scripts/spark-inference.py`, eugr YAML generation, or bench code:

1. Commit the fix on the box (or push from the clone).
2. Smoke `opencode-qwen36-250k` (or a small llama profile): `up` → `/v1/models` → optional short completion.
3. Resume Benchmaster if you paused it.

Model-specific quirks belong in that recipe’s eugr YAML or scaffold conditions, not in global defaults.

## Stack fixes (keep these)

Learned on the first full bench pass. Still the right defaults.

| Issue | Symptom | Fix |
|-------|---------|-----|
| Scaffold only saw `nvfp4/` | `no nvfp4 weights` for HF/FP8 models | Discover `hf/`, `fp8/`, `prismaquant/` |
| `max_model_len` too high | vLLM ValidationError | `infer_max_model_len()` from `config.json` |
| FlashInfer + multimodal | `partial multimodal token full attention` | Omit `--attention-backend flashinfer` for MM |
| fastsafetensors crash | Engine dies at 0% shards | `--load-format auto` for multimodal |
| Large MM MoE OOM | OOM during load | Lower `gpu_memory_utilization`, shorter ctx |
| GGUF picks largest quant | Hang at “fitting params” | Prefer Q4_K_M / Q4_K_XL |
| Download check too broad | Skipped everything while another model pulled | Per-inventory-path download check |
| Text-only MM checkpoint | `visual.blocks.*` missing | `--language-model-only`; read `language_model_only` |
| Nested `text_config` ctx | Native ctx stuck at 16384 | Also read `text_config.max_position_embeddings` |
| Grok `tool_choice: auto` | 400 on gateway | `--enable-auto-tool-choice` + `--tool-call-parser qwen3_xml` |

## Troubleshooting

### vLLM never ready

```bash
docker logs vllm_node 2>&1 | tail -50
spark engine eugr status
```

Usual causes: wrong `max_model_len`, FlashInfer on multimodal, OOM, bad weight path.

### llama.cpp stuck at “fitting params”

Try a smaller quant. Confirm eugr is down. Check `/opt/spark/logs/llama-server.log`.

### Bench tok/s very low, GPU ~2%

Dense models at batch=1 often under-fill GB10. MoE NVFP4 is the high-tok/s path. Check `nvidia-smi` and `curl -sf http://sparky/api/gpu` during generate.

### Engine fights

`spark inference down` before switching families. If Docker is stuck: `spark engine eugr down`, then `docker ps | grep vllm`.
