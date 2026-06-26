# TASK-004: Explore queue UX overhaul

| Field | Value |
|-------|-------|
| **Status** | done |
| **Priority** | Seq 6 |
| **Owner** | — |
| **PR policy** | **One PR** — Shortlist UI + API snapshot/dedupe (phases A+B in one PR if scope fits; else phase A only with follow-up task) |
| **Depends on** | — |
| **Primary files** | `portal/index.html`, `scripts/spark-hf.py`, `data/hf-explore-queue.yaml` (runtime) |

## Problem

Explore queue is a cramped bottom panel (`max-height: ~200px`) showing repo + intent only. Comparing multiple shortlisted models requires clicking each item sequentially and loading `/api/hf/model/{repo}`. No size, engine, Spark fit, or status at a glance. Same repo can be saved twice.

## Requirements

### Functional

1. **Shortlist / Compare view** — sub-nav under Explore: Browse | Shortlist | Downloads (persist mode in `localStorage`).
2. **Compare table** — full-width when Shortlist active: repo, badges, variant, engine, size, Spark fit, HF downloads (optional), status, added, actions.
3. **Multi-select** — bulk Remove; bulk Download (with spark fit warnings).
4. **Row click** — detail drawer without resetting browse context.
5. **Status cross-links** — `saved`, `on_disk`, `download_queued`, `downloading`, `gated` from download queue + disk checks.
6. **Dedupe** — same repo + variant replaces existing item.
7. **Legacy items** — YAML rows without snapshot enrich on first Shortlist open.

### API (Phase B)

Extend explore queue items with `snapshot` (format, engine, size, spark_fit, badges) and `variant_id` at save time. Enrich `queue_list()` with `status` + download cross-ref. Optional: `POST /api/hf/queue/explore/enrich`, bulk endpoints.

### Non-functional

- Shortlist render ≤100ms for ≤20 items with snapshots
- No extra poll storm on `expTick`
- Horizontal scroll on mobile

### Out of scope

- Post-download bench compare (Models page)
- HF browse multi-compare (shortlist only)

## Acceptance criteria

- [x] 3+ queued models visible in one screen with size, engine, Spark fit
- [x] Sort by size and Spark fit
- [x] Multi-select remove and download
- [x] Status column reflects download/disk state
- [x] Row opens detail without hiding compare table
- [x] Dedupe on save
- [x] Browse mode unchanged (search, trending, variant download)

## Test plan

1. Save 3 models (GGUF, NVFP4, MoE) → table populated
2. Sort, multi-remove, single download → status updates
3. Dedupe save
4. Legacy minimal YAML row → enrich pass
5. Gated repo → status + HF link
6. Regression: `expTick`, browse filters

## Implementation notes

**Phase A:** UI only (client fetch enrich as interim — cap 10 items).  
**Phase B:** API snapshot + dedupe + status enrichment.  
**Phase C:** Bulk download, reorder, quick-save on browse cards.

Precedent: `renderBenchCompareStrip()` on Models page for post-download compare.

Use `SparkInventoryGrid` from TASK-007 where applicable (sortable compare table, filter chips).

## Completion log

| Date | Owner | Result | Commit |
|------|-------|--------|--------|
| 2026-06-26 | fm/task-004-f6 | Phase A+B shipped: Browse\|Shortlist\|Downloads sub-nav; compare table with sort, multi-select, bulk remove/download, status chips, drawer; API snapshot+dedupe+status enrichment | fm/task-004-f6 |
