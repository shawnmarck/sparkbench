# TASK-011: First Spark setup guide (solo GB10)

| Field | Value |
|-------|-------|
| **Status** | done |
| **Priority** | Seq 8 |
| **Owner** | — |
| **PR policy** | One PR |
| **Parallel-safe** | yes |
| **Depends on** | — |
| **Primary files** | `docs/guides/first-spark-setup.md`, `README.md`, `install/INSTALL.md` |

## Problem

New solo DGX Spark (GB10) users clone the repo but lack a single doc for: install order, what’s in git vs on disk, how to browse golden recipes without weights, and how to get a model running.

## Requirements

### Functional

1. Add `docs/guides/first-spark-setup.md` — clone → install scripts → portal → inventory rebuild.
2. Explain **git cookbook** vs **local weights** (`recipes/`, `data/golden-recipes.yaml` vs `/models/`).
3. Document minimum install set for inference (CLI, shelf optional, HF login).
4. Link to golden workflow, `spark models golden`, and TASK-012 fetch when done.
5. Add README + INSTALL index links.

### Non-functional

1. Assumes one Spark, no NAS shelf (shelf as optional path).
2. Under 200 lines; scannable checklist format.

## Acceptance criteria

- [ ] Guide exists and is linked from README
- [ ] New user can follow guide without reading AGENT.md first
- [ ] Clearly states: recipes + perf travel in git; weights do not

## Test plan

1. Dry-run guide steps against fresh clone checklist (peer review).
2. Verify all linked paths exist.

## Completion log

| Date | Owner | Result | Commit / PR |
|------|-------|--------|-------------|
| — | — | — | — |
