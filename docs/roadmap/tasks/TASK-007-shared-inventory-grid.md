# TASK-007: Shared inventory grid module

| Field | Value |
|-------|-------|
| **Status** | done |
| **Priority** | Seq 2 |
| **Owner** | — |
| **PR policy** | **One PR** — entire task |
| **Parallel-safe** | yes after TASK-006 merged |
| **Depends on** | TASK-006 (recommended) |
| **Primary files** | `portal/assets/spark-inventory-grid.js` (new), `portal/index.html`, `portal/models.html` (minimal wiring) |

## Problem

Models, Inference recipes, and Explore shortlist all need the same UX primitives: sortable columns, filter chips, “Showing A of B”, flat vs grouped toggle. Today logic is duplicated across 3k-line monoliths. TASK-002, 005, and 004 should consume one module, not fork three implementations.

## Requirements

### Module API (minimum)

Export a small API (IIFE or `window.SparkInventoryGrid`) with:

1. **`renderTable(container, { columns, rows, sort, onSort, summary })`**
2. **`renderSummary(el, { filtered, total, suffix })`** — “Showing A of B”
3. **`renderChips(container, chips, active, onToggle)`**
4. **`compareValues(a, b, col, dir)`** — nulls last
5. **Flat vs grouped toggle** helper (optional callback for grouped render)

### Non-functional

- No framework; vanilla JS matching portal style
- Document usage in module header comment
- TASK-002/005/004 migrate to module in their own PRs (this task only ships module + one reference integration or demo wiring)

### Deliverable for this PR

- New `spark-inventory-grid.js` with tests via manual checklist
- Wire into **one** consumer as proof (Inference recipe count/summary line only, or Models sort helper extraction) — enough to prove API, not full TASK-002

## Acceptance criteria

- [ ] Module loaded by portal without console errors
- [ ] At least one live callsite uses summary + sort helpers
- [ ] README snippet in file documents integration for TASK-002/005/004
- [ ] One PR; Completion log filled

## Test plan

1. Load portal; verify no JS errors
2. Exercise the reference callsite (sort or summary updates on filter change)

## Completion log

| Date | Owner | Result | Commit / PR |
|------|-------|--------|-------------|
| 2026-06-25 | agent fm/task-007-g8 | done | feat/TASK-007-shared-inventory-grid |
