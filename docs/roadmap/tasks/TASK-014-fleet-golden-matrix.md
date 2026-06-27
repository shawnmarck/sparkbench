# TASK-014: Fleet golden workflow — full bench matrix in git

| Field | Value |
|-------|-------|
| **Status** | done |
| **Priority** | Seq 11 |
| **Owner** | — |
| **PR policy** | One PR (orchestration); recipe commits may batch |
| **Parallel-safe** | no |
| **Depends on** | golden workflow landed (`spark-golden-workflow.py`) |
| **Primary files** | `scripts/spark-golden-workflow.py`, `recipes/*.yaml`, `data/model-verification.yaml` |

## Problem

Most golden recipes lack committed `bench_matrix` / `kv_sweep` / complete `ctx_ladder`. Solo users cloning the repo don’t get the full GB10 perf surface.

## Requirements

### Functional

1. Fix workflow phase order: **golden → ctx ladder → kv sweep** (currently kv before ladder).
2. Run `spark-golden-workflow.py --all --skip-shelf --resume` on sparky to completion.
3. Maintainer commit push: all updated `recipes/*.yaml` with matrix data + `data/model-verification.yaml` headlines.
4. Add `scripts/spark-golden-matrix-status.py` — table of golden models × layers complete/partial/missing (for CI or manual audit).
5. Document commit cadence in golden workflow skill/runbook.

### Non-functional

1. Days of GPU time acceptable; daemon-friendly (`nohup`, `--resume`).
2. Skip list unchanged (`0xsero/...`, `z-lab/*`).

## Acceptance criteria

- [ ] Phase order corrected in orchestrator
- [ ] `spark-golden-matrix-status.py` reports per-model layer status
- [ ] ≥90% of `golden-recipes.yaml` entries have `bench_matrix.golden_cell` + `ctx_ladder` or skip reason + `kv_sweep` in git
- [ ] Runbook documents post-workflow git push

## Test plan

1. Dry-run workflow on one model; verify phase order in log.
2. Matrix status script on current repo snapshot.

## Completion log

| Date | Owner | Result | Commit / PR |
|------|-------|--------|-------------|
| — | — | — | — |
