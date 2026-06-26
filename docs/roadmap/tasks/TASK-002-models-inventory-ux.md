# TASK-002: Models inventory UX (sortable table + detail pane)

| Field | Value |
|-------|-------|
| **Status** | done |
| **Priority** | Seq 4 |
| **Owner** | — |
| **PR policy** | **One PR** — table + side pane together (supersedes old split TASK-002/TASK-003) |
| **Parallel-safe** | no — owns `portal/models.html` |
| **Depends on** | TASK-006, TASK-007 (recommended) |
| **Primary files** | `portal/models.html`, `portal/assets/spark-inventory-grid.js` |

## Problem

1. **Table:** Key stats (local/shelf size, max CTX, params, MoE active params, tags) are buried in description lines; no column-header sort.
2. **Detail:** Inline row expansion breaks list scanning at ~145+ models; nested `<details>` overload.

User wants sortable table **and** detail in a side pane (not inline expand) — one cohesive Models page rework.

## Requirements

### Sortable table

- Semantic `<table>` with sticky header; columns: Model, Local, Shelf, Max CTX, Params, Active (MoE), Spark, Download, Arch, Engine, Inference, Bench, capabilities/tags
- Header sort (asc/desc); persist in `localStorage`
- Tags visible, sortable/filterable; live `#q` search
- Family grouping toggle (flat default)
- Data from `models.json` / `spark-inventory-build.py` fields

### Detail side pane

- Remove inline `.row-detail`; `#model-detail-pane` master–detail (desktop right pane; mobile sheet)
- `selectedModelId` replaces `expandedId`
- Preserve: verify, shelf, recipes, bench history, `?highlight=`, all API actions

### Integration

- Use `SparkInventoryGrid` from TASK-007 where applicable

## Acceptance criteria

- [x] Stats in columns, not meta line; header sort works
- [x] Selecting model opens side pane; list scroll independent
- [x] All recipe/shelf/bench actions work from pane
- [x] Family view + highlight deep links work
- [x] Embedded portal iframe + 30s refresh stable
- [x] One PR; Completion log filled

## Test plan

See combined test plans from prior TASK-002 + TASK-003 research (sort columns, pane actions, highlight, mobile sheet, poll stability).

## Completion log

| Date | Owner | Result | Commit / PR |
|------|-------|--------|-------------|
| 2026-06-25 | fm/task-002-r5 | Sortable table + detail side pane implemented. `spark-inventory-grid.js` vendored from TASK-007 branch. | fm/task-002-r5 |
