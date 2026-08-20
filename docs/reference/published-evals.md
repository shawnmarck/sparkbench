# Published evals (display-only)

Vendor SWE / Terminal-Bench (and optional extras) shown on [sparkbench.dev](https://sparkbench.dev). **Not a Spark measurement.** PBM tok/s on this GB10 stays the default ranking.

Source file: [`data/published-evals.yaml`](../../data/published-evals.yaml).

## What this is

| Axis | Where it comes from | Site |
|------|---------------------|------|
| Speed | PBM on Sparky (`perfbench-metrics.yaml`) | Default sort |
| SWE / TB | Vendor model cards and launch blogs | Optional sort; source link on every number |
| Artificial Analysis | Outbound link only | `AA ↗` when `aa_url` is set. **Do not copy AA scores.** |

These numbers are whoever published them, on whatever harness they used. They are not comparable to a Harbor run against the golden recipe on this box.

## Inherit rules

Scores attach to a **canonical base** (`qwen/qwen3.6-35b-a3b`, …). Packs of the same weights inherit via `aliases` (NVFP4, MTP, DFlash, Unsloth GGUF of that checkpoint).

**Do not alias** finetunes, merges, uncensored, “opus”, “thinkingcap”, “agentworld”, “qwythos”, or other trained-away checkpoints. Those stay `—` until that checkpoint has its own card number.

The site footnotes inherited rows: “Published for {base}, not this pack.”

## Adding or updating a score

1. Prefer the vendor card or launch blog over secondary roundups.
2. Every numeric cell needs `score`, `source_name`, `source_url`, and `as_of` (ISO date).
3. Record Terminal-Bench suite as `"2.0"` or `"2.1"` — do not mix unlabeled.
4. SWE-Verified goes in `swe_verified`. SWE-Pro, LiveCodeBench, GPQA go under `extras`.
5. Add `aa_url` only when Artificial Analysis has a model page for that base. Never paste AA index values into this file.
6. Open a PR. The public site rebuilds from this YAML (nightly or `workflow_dispatch`).

Missing data is `—`, never `0`.
