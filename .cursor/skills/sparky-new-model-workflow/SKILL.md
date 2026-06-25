---
name: sparky-new-model-workflow
description: >-
  Onboard a new model on Sparky homelab: download, golden recipe, max-ctx optimization,
  bench v2, verify works (bench-gated), inventory rebuild. Use when adding models to
  /models, running golden audit, benchmarking new downloads, or user mentions
  "new model workflow", "golden audit", or AgentWorld/Qwythos-style onboarding.
---

# Sparky new model workflow (golden + bench v2)

Production host: **`sparky`**, repo **`/opt/spark`**. Local mirror: **`~/projects/sparky`**.

## Policy (do not skip)

- **`works` tag only after successful bench v2** — never from load-only smoke tests.
- **One golden profile** per `inventory_path` in `data/golden-recipes.yaml`.
- **Bench standard v2** (`BENCH_STANDARD=v2`): long ctx fill + tools + agent turns. See `docs/reference/benchmark-standard.md`.
- **Skip shelf push during audit** (`--skip-shelf`) unless user asks — large rsyncs block for hours.
- **0xsero/deepseek-v4-flash-spark** — intentionally skipped (REAP GGUF load fails).

## Quick path (one or more new models)

```bash
# 1. Confirm model on disk
ssh sparky 'ls -la /models/<lab>/<slug>/'

# 2. Scaffold recipe if none in /opt/spark/recipes/
ssh sparky 'spark recipe scaffold <lab>/<slug> eugr'   # or llamacpp / ds4

# 3. Register golden map (local mirror + deploy)
#    Edit data/golden-recipes.yaml:
#      <inventory_path>: <golden-profile-id>
#    Edit scripts/golden-inventory-audit.py DEFAULT_GOLDEN + ARCH_FIXES if needed.
scp data/golden-recipes.yaml scripts/golden-inventory-audit.py sparky:/opt/spark/...

# 4. Run golden audit for new models only
ssh sparky 'nohup /opt/spark/venv/bin/python3 /opt/spark/scripts/golden-inventory-audit.py \
  --only "<lab>/<slug>,<lab2>/<slug2>" \
  --skip-shelf \
  >> /opt/spark/logs/golden-audit.log 2>&1 &'

# 5. Monitor
ssh sparky 'tail -f /opt/spark/logs/golden-audit.log'

# 6. After finish: reports + portal
ssh sparky 'cat /opt/spark/run/golden-audit-report.md'
ssh sparky 'spark models inventory'
```

Wrapper script (on sparky after deploy):

```bash
/opt/spark/scripts/spark-new-model-golden.sh qwen/qwen-agentworld-35b-a3b empero-ai/qwythos-9b-claude-mythos-5-1m
```

## What the audit does per model

1. Fix catalog architecture tags (`ARCH_FIXES`) if set
2. `spark shelf pull` if not local
3. Promote draft recipe → production if needed
4. **Max-fit ctx** + fp8/q8_0 KV on golden preset (`optimize_recipe_context`)
5. `spark inference up <golden> --ctx N --kv … --preset golden`
6. Wait for `/v1/models` — **eugr: up to 2400s** (`AUDIT_EUGR_READY_SECS`)
7. `BENCH_STANDARD=v2 spark inference bench --write-result`
8. On success only: `spark models verify set … works`
9. On failure: `spark models verify set … failed`
10. `spark models inventory` (portal `best_bench_tok_s` needs `bench-agent-v2` in `BENCH_METHODS`)

Reports: `/opt/spark/run/golden-audit-report.json` + `.md`

## Result table columns (for user reports)

| Column | Source |
|--------|--------|
| Native max ctx | recipe `context.native` |
| Test ctx (loaded) | audit `--ctx` / golden preset |
| v2 tok/s | bench v2 decode throughput |
| Status | `ok` only if bench + verify succeed |

## Engine choice

| Format on disk | Typical golden engine |
|----------------|----------------------|
| `nvfp4/` or MoE HF | `eugr` |
| `hf/` dense | `eugr` or `llamacpp` if GGUF-only |
| `gguf/` | `llamacpp` |
| DwarfStar / ds4 weights | `ds4` |

Scaffold picks a draft; golden audit promotes after bench.

## Portal bench display

If cards show `works` but no tok/s: ensure `spark-inventory-build.py` includes `bench-agent-v2` in `BENCH_METHODS`, then `spark models inventory`.

## Text-only multimodal (AgentWorld-class)

If eugr load fails with **uninitialized `visual.*` weights** but `config.json` has
`"language_model_only": true`:

1. Ensure `/opt/spark/scripts/patch-eugr-language-model-only.py` ran (adds scaffold flag).
2. Re-scaffold or hand-edit `services/eugr-<profile>.yaml` → `--language-model-only`.
3. Re-run audit for that model only.

## Sudo / root-owned state

- Eugr stack pins: `spark-eugr-check` writes `.pending.json` when official file is root-owned.
- Do **not** block workflow on manual sudo; promote pending on sparky when needed.
- HF Explorer scaffolds may create **root-owned** draft recipes. If promote fails with `Permission denied` on `recipes/drafts/`:

```bash
ssh sparky 'python3 << "PY"
import yaml
from pathlib import Path
for pid in ["qwen-qwen-agentworld-35b-a3b-eugr", "..."]:
    draft = Path(f"/opt/spark/recipes/drafts/{pid}.yaml")
    prod = Path(f"/opt/spark/recipes/{pid}.yaml")
    if prod.exists(): continue
    data = yaml.safe_load(draft.read_text()) or {}
    data["lifecycle"] = "testing"
    prod.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
    print("wrote", prod)
PY'
```

Then re-run `spark-new-model-golden.sh`.

## Full fleet re-audit

```bash
ssh sparky 'nohup /opt/spark/venv/bin/python3 /opt/spark/scripts/golden-inventory-audit.py \
  --reset-verify --skip-shelf >> /opt/spark/logs/golden-audit.log 2>&1 &'
```

## Reference files

- `docs/runbooks/new-model-golden-benchmark.md` — step-by-step runbook
- `docs/reference/benchmark-standard.md` — bench v2 spec
- `data/golden-recipes.yaml` — inventory → golden profile map
- `scripts/golden-inventory-audit.py` — automation
