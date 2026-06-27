# TASK-012: `spark models fetch` — download golden variant from HF

| Field | Value |
|-------|-------|
| **Status** | done |
| **Priority** | Seq 9 |
| **Owner** | — |
| **PR policy** | One PR |
| **Parallel-safe** | partial |
| **Depends on** | TASK-011 (docs link) |
| **Primary files** | `scripts/spark-models-fetch.py`, `scripts/spark`, `data/model-catalog.yaml` |

## Problem

Shelf-less solo users cannot use **Fetch ↓** (NAS). Catalog has `hf_repo` and variants but no one-command download that picks the **golden** quant/path for an inventory model.

## Requirements

### Functional

1. `spark models fetch <lab/slug>` — resolve golden profile → catalog variant → `hf download` to `/models/<lab>/<slug>/`.
2. `--dry-run` — print repos, files, dest paths, est. size.
3. `--variant <subpath>` override when not golden.
4. Respect existing partial downloads; log to `logs/models-fetch-latest.log`.
5. Portal: **Download** button on catalog-only / missing rows when `hf_repo` known (shelf not required).

### Non-functional

1. Reuse catalog `variants[]` + golden recipe `model` path to infer GGUF file or HF snapshot dir.
2. Fail clearly when no golden map or no matching variant.

### Out of scope

- NAS shelf pull (existing `spark shelf pull`).
- Auto-run golden workflow after download.

## Acceptance criteria

- [ ] `spark models fetch yuxinlu1/mellum2-12b-opus-thinking` downloads golden GGUF to expected path
- [ ] Dry-run shows commands without network
- [ ] Portal button triggers same path (API or documented CLI)
- [ ] Documented in `docs/reference/spark-cli.md` and first-spark-setup guide

## Test plan

1. Dry-run 3 models (llamacpp GGUF, eugr HF, MoE).
2. One real fetch on sparky for small model or `--dry-run` only in CI.

## Completion log

| Date | Owner | Result | Commit / PR |
|------|-------|--------|-------------|
| — | — | — | — |
