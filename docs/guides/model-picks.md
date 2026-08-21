# Model picks

How the SparkBench catalog is chosen. The live map is `data/golden-recipes.yaml` and `data/model-catalog.yaml`. This page is the why, not a download script.

Public names on [sparkbench.dev](https://sparkbench.dev) are the model, not the client. Profile ids such as `opencode-qwen36-250k` stay in the CLI.

## What we optimize for

One DGX Spark (128 GB unified). One GPU engine at a time. Workloads are coding agents, long context, and fair tok/s.

Prefer:

- First-party or NVIDIA NVFP4 / FP8 when it loads on eugr
- A GGUF sibling (Q4_K_M class) when we want a llama.cpp bake-off
- Speculative paths (MTP, DFlash, DSpark) as **companions**, not replacements, until they beat the golden

Skip or fold:

- Duplicate packs of the same family that lose the 50k PBM rung
- Early dense baselines that no longer earn a default leaderboard row (phi-4, Hermes-4-14B, R1-distill-32B live in `leaderboard_exclude`)

## Editor's pick

**Ornith 1.5** (`ornith-ai/ornith-1.5-35b-a3b`)

- Profile: `ornith-ai-ornith-1-5-35b-a3b-nvfp4-b12x-eugr`
- Why: current site pick for “start here on a Spark”
- Marked `currently_testing` in `golden-recipes.yaml` while we keep measuring it

## Everyday agent profiles

These are the profiles you actually `up` for OpenCode, Grok, and Hermes. Gateway base: `http://sparky:9000/v1`, model `sparky`.

| Profile | Public model | Role |
|---------|--------------|------|
| `opencode-qwen36-250k` | Qwen3.6-35B-A3B | Fast MoE coding, 256k, fp8 KV |
| `opencode-qwen27-dflash-262k` | Qwen3.6-27B + DFlash | Dense 27B, architecture / design |
| `qwen36-35b-a3b-mtp-eugr` | Qwen3.6-35B-A3B · MTP | Golden companion for `nvidia/qwen3.6-35b-a3b` |
| `qwen36-q4-llama` | Qwen3.6-35B-A3B Q4 | llama.cpp path for the same family |

`qwen36-nvfp4` is deprecated. Do not use it in new docs or smokes.

## Families on the board

The public site folds weaker packs of the same family behind **All recipes**. Full ladder also hides rows without a 50k PBM fill.

Typical rows you will see:

- Qwen3.6 35B-A3B (NVIDIA NVFP4, Unsloth GGUF / NVFP4-fast, official DFlash)
- Qwen3.6 / 3.8 27B (official, Unsloth, DFlash / DFlash2 / DSpark, community quants)
- Qwen3 Coder Next, AgentWorld, thinkingcap / Qwopus finetunes
- Ornith 1.0 / 1.5
- Gemma 4 12B / 26B-A4B, Mellum2, Laguna, Step-3.7 Flash
- DeepSeek V4 Flash (ds4 + DSpark)

Vendor SWE / Terminal-Bench numbers on the site are citations. See [published-evals.md](../reference/published-evals.md).

## How a model gets in

1. Land weights under `/models/<lab>/<slug>/`
2. Scaffold a recipe (`spark recipe scaffold …`). Extend the router before hand-writing YAML.
3. Bench v2 → `spark models verify set … works`
4. Register the golden in `data/golden-recipes.yaml` and `scripts/golden-inventory-audit.py`
5. Rebuild inventory. The site picks up catalog + verify + PBM on the next sparkbench.dev build.

Runbook: [new-model-golden-benchmark.md](../runbooks/new-model-golden-benchmark.md).

## Historical note

The first June 2026 pull was Qwen3.6-35B-A3B NVFP4 + Unsloth GGUF, then Hermes-4-14B, Qwen3-30B-A3B, Qwen3-Coder-30B, R1-distill-32B, phi-4, and Gemma 4. Those weights are still on disk. Several no longer headline the public board. Use `golden-recipes.yaml` as the current list.
