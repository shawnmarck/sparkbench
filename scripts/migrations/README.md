# Historical migrations

One-shot patch scripts that were applied to running SparkBench installs to
fix a specific defect or roll forward a schema. **Their effect is already
baked into the current code** — fresh installs do not need to run any of
these.

Keep them around so we can:

1. Reconstruct what changed and when
2. Re-run on an old fork that missed the upgrade window
3. Audit "did this install get the fix?"

If you are setting up a new Spark, skip this directory entirely.

## Index

| File | Date applied | What it did |
|------|--------------|-------------|
| `patch-eugr-language-model-only.py` | 2026-06 | Added `--language-model-only` flag handling to eugr recipe YAML for text-only multimodal checkpoints. |
| `patch-eugr-qwen-tool-choice.py` | 2026-06 | Added `--enable-auto-tool-choice` + `--tool-call-parser qwen3_xml` for Qwen agent models. |
| `patch-eugr-state-writable.py` | 2026-06 | Made eugr state dir writable by the spark user. |
| `patch-gateway-qwen-messages.py` | 2026-06 | Normalized Qwen message shape in `spark-inference-gateway.py`. |
| `patch-gateway-thinking-variants.py` | 2026-06 | Added `thinking` model variant routing in the gateway. |
| `patch-gpu-metrics-endpoints.py` | 2026-06 | Added `/api/gpu` endpoints for the portal widget. |
| `patch-inference-bench-v2.py` | 2026-06 | Cut over `spark inference bench` to v2 methodology (long-ctx + tool-use). |
| `patch-portal-containers-ui.py` | 2026-06 | Wired the System tab "containers" card into `portal/index.html`. |
| `fix-spark-inference-lmo-string.py` | 2026-06 | Repaired a quoting bug in `--language-model-only` injection. |
| `fix-spark-inference-qwen-agent-lines.py` | 2026-06 | Repaired Qwen agent flag injection at recipe scaffold time. |
| `apply-spark-patches.sh` | 2026-06 | Wrapper that ran the eugr/gateway patches above in order. |

## When to actually run one

Only if you're upgrading an install that predates the patch *and* you've
read the script to confirm what it touches. They are not idempotent in the
sense modern install scripts are — they pattern-match against expected
file content. If your file diverged, the patch may fail loudly or (worse)
no-op silently.
