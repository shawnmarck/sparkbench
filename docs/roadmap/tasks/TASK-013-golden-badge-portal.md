# TASK-013: Golden badge + GB10 verified UX in Models portal

| Field | Value |
|-------|-------|
| **Status** | done |
| **Priority** | Seq 10 |
| **Owner** | — |
| **PR policy** | One PR |
| **Parallel-safe** | yes |
| **Depends on** | — |
| **Primary files** | `portal/models.html`, `scripts/spark-inventory-build.py`, `data/golden-recipes.yaml` |

## Problem

Golden status is used internally for bench headlines but users cannot scan which models are **GB10-verified** with a committed golden recipe and perf matrix.

## Requirements

### Functional

1. Inventory exposes `is_golden: true` when `inventory_path` ∈ `golden-recipes.yaml`.
2. Models table: **Golden** badge/chip on golden rows (sort/filter optional).
3. Detail pane: “GB10 golden recipe” block — profile id, golden ctx/kv, headline tok/s, matrix summary (rungs × kv count).
4. Catalog-only (`missing`) golden models: show badge + **Download** CTA (TASK-012) instead of empty lab.

### Non-functional

1. Badge does not require local disk or `works` on this host (recipe perf is in git).
2. Distinguish `works` (this box verified) vs `golden` (upstream cookbook).

## Acceptance criteria

- [ ] Golden models visible in table without local copy
- [ ] Badge + golden profile id in detail pane
- [ ] Filter chip “Golden only” (reuse chip pattern)
- [ ] `spark models inventory` includes `is_golden`

## Test plan

1. Rebuild inventory; verify golden model with no local disk shows badge.
2. Verify non-golden model has no badge.

## Completion log

| Date | Owner | Result | Commit / PR |
|------|-------|--------|-------------|
| — | — | — | — |
