# New model golden benchmark runbook

Add a model that already exists under `/models/<lab>/<slug>/` (or pull from shelf first).

## 1. Register golden profile

Edit `/opt/spark/data/golden-recipes.yaml`:

```yaml
golden:
  qwen/qwen-agentworld-35b-a3b: qwen-qwen-agentworld-35b-a3b-eugr
  empero-ai/qwythos-9b-claude-mythos-5-1m: empero-ai-qwythos-9b-claude-mythos-5-1m-eugr
```

Mirror the same entries in `scripts/golden-inventory-audit.py` → `DEFAULT_GOLDEN`.

## 2. Scaffold recipe (if missing)

```bash
spark recipe scaffold qwen/qwen-agentworld-35b-a3b eugr
spark recipe list | grep agentworld
```

Remove duplicate draft profiles; keep one golden id. Add extras to `deprecated_profiles` in golden-recipes.yaml.

## 3. Run audit

```bash
/opt/spark/scripts/spark-new-model-golden.sh \
  qwen/qwen-agentworld-35b-a3b \
  empero-ai/qwythos-9b-claude-mythos-5-1m
```

Or directly:

```bash
python3 /opt/spark/scripts/golden-inventory-audit.py \
  --only "qwen/qwen-agentworld-35b-a3b,empero-ai/qwythos-9b-claude-mythos-5-1m" \
  --skip-shelf
```

## 4. Read results

```bash
cat /opt/spark/run/golden-audit-report.md
spark models verify get qwen/qwen-agentworld-35b-a3b
```

## 5. Optional shelf push

After `works` + bench:

```bash
spark shelf push qwen/qwen-agentworld-35b-a3b
```

## Verify policy

`spark models verify set … works` runs **only** after bench v2 returns ok. Failed load/bench → `failed`.

## Troubleshooting: text-only multimodal checkpoints

Some HF models ship **language weights only** but still declare `vision_config` in `config.json`
(e.g. `qwen/qwen-agentworld-35b-a3b` has `"language_model_only": true`).

**Symptom:** vLLM dies during load with `ValueError: Following weights were not initialized
from checkpoint: {'visual.blocks...', ...}` and audit times out on `/v1/models`.

**Fix:** add `--language-model-only` to the eugr service command (scaffold does this automatically
when `config.json` has `"language_model_only": true`):

```bash
# one-off repair
spark recipe scaffold qwen/qwen-agentworld-35b-a3b eugr   # after patch-eugr-language-model-only.py
# or edit /opt/spark/services/eugr-<profile>.yaml and add:
#   --language-model-only \
```

Apply scaffold patch on sparky if missing:

```bash
python3 /opt/spark/scripts/patch-eugr-language-model-only.py
```

Then re-run golden audit for that model only.

## Grok / agent tools (`tool_choice: auto`)

Grok Build sends OpenAI tools with `tool_choice: auto`. eugr vLLM needs:

```text
--enable-auto-tool-choice
--tool-call-parser qwen3_xml
```

Add to `services/eugr-<profile>.yaml` for Qwen-family models, then reload the same profile (`spark inference up … --ctx N --kv fp8`). Without this, gateway returns 400 Bad Request.

## Context viability (no bench)

After golden bench at safe ctx, ladder to target ctx with load + smoke only:

```bash
bash /opt/spark/scripts/ctx-viability-test.sh <profile-id> <ctx> fp8 3600
python3 /opt/spark/scripts/update-recipe-ctx.py <profile-id> <ctx> --label "..." --note "..."
spark models inventory
```

Script refreshes `context.native` from HF before launch (stale 16k native otherwise clamps `--ctx`).
Verify `max_model_len` in `/v1/models` matches requested ctx before updating recipe.
