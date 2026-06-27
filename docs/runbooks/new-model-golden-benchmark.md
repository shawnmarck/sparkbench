# Golden workflow runbook

**"Golden workflow"** = full layered bench per model: golden cell → KV sweep → ctx ladder → (optional) shelf push.

Orchestrator: `scripts/spark-golden-workflow.py`  
Report: `/opt/spark/run/golden-workflow-report.json`  
Log: `/opt/spark/logs/golden-workflow.log`

## 1. Register golden profile

Edit `/opt/spark/data/golden-recipes.yaml`:

```yaml
golden:
  qwen/qwen-agentworld-35b-a3b: qwen-qwen-agentworld-35b-a3b-eugr
```

Mirror in `scripts/golden-inventory-audit.py` → `DEFAULT_GOLDEN`.

## 2. Scaffold recipe (if missing)

```bash
spark recipe scaffold qwen/qwen-agentworld-35b-a3b eugr
```

## 3. Run full golden workflow

```bash
spark models golden qwen/qwen-agentworld-35b-a3b

# or wrapper
/opt/spark/scripts/spark-new-model-golden.sh qwen/qwen-agentworld-35b-a3b

# background (long-ctx models may take hours)
nohup /opt/spark/venv/bin/python3 /opt/spark/scripts/spark-golden-workflow.py \
  --only "qwen/qwen-agentworld-35b-a3b" --skip-shelf --resume \
  >> /opt/spark/logs/golden-workflow.log 2>&1 &
```

## 4. Fleet — all golden models

```bash
nohup /opt/spark/venv/bin/python3 /opt/spark/scripts/spark-golden-workflow.py \
  --all --skip-shelf --resume \
  >> /opt/spark/logs/golden-workflow.log 2>&1 &
```

Use `--resume` to skip phases already complete in the workflow report.

## 5. Layers

| Layer | Measures | Stored on recipe |
|-------|----------|------------------|
| Golden | Full bench v2 at optimized ctx/kv | `bench_matrix.golden_cell`, verify `works` |
| KV sweep | Golden ctx × KV quants @ 75% fill | `kv_sweep`, `bench_matrix.kv_sweep` |
| Ctx ladder | Golden kv × ctx rungs @ 75% fill | `ctx_ladder`, `bench_matrix.ctx_ladder` |
| Shelf | NAS rsync | inventory `shelf.present` |

KV options by engine (see `spark-golden-bench.py`):

- **eugr:** `fp8`
- **llamacpp:** `q8_0`, `q4_0`, `f16`
- **ds4:** `q8_0`

## 6. Read results

```bash
cat /opt/spark/run/golden-workflow-report.json | python3 -m json.tool
cat /opt/spark/run/golden-audit-report.md
spark models verify get qwen/qwen-agentworld-35b-a3b
spark models inventory
```

Portal: Models detail → recipe block shows **KV sweep** and **Context ladder** panels.

## 7. Optional shelf push

```bash
spark shelf push qwen/qwen-agentworld-35b-a3b
# or re-run workflow without --skip-shelf
```

## Verify policy

`works` is set **only** after golden-phase bench v2 succeeds. KV sweep / ctx ladder failures yield workflow status `partial` but do not revoke `works`.

## Single-layer commands

```bash
# Golden only (legacy audit)
python3 /opt/spark/scripts/golden-inventory-audit.py --only "lab/slug" --skip-shelf

# KV sweep only
python3 /opt/spark/scripts/spark-kv-sweep.py <profile-id> --force

# Ctx ladder only
python3 /opt/spark/scripts/spark-ctx-ladder.py <profile-id> --force
```

## Troubleshooting: text-only multimodal checkpoints

Some HF models ship **language weights only** but still declare `vision_config` in `config.json`
(e.g. `qwen/qwen-agentworld-35b-a3b` has `"language_model_only": true`).

**Symptom:** vLLM dies during load with `ValueError: Following weights were not initialized
from checkpoint: {'visual.blocks...', ...}` and workflow times out on `/v1/models`.

**Fix:** add `--language-model-only` to the eugr service command:

```bash
spark recipe scaffold qwen/qwen-agentworld-35b-a3b eugr
python3 /opt/spark/scripts/patch-eugr-language-model-only.py
```

Then re-run golden workflow.

## Grok / agent tools (`tool_choice: auto`)

eugr vLLM needs `--enable-auto-tool-choice` and `--tool-call-parser qwen3_xml` on Qwen-family services.

## Promote higher ctx after ladder review

```bash
python3 /opt/spark/scripts/update-recipe-ctx.py mellum2-12b-opus-q4 98304 --label "Golden max fit" --note "ctx ladder verified"
```
