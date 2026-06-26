# TASK-010: Inference grid — sortable column headers

| Field | Value |
|-------|-------|
| **Status** | done |
| **Priority** | Seq 7 |
| **Owner** | — |
| **PR policy** | **One PR** — full task scope |
| **Depends on** | TASK-005 (flat recipe grid) |
| **Primary files** | `portal/index.html`, `portal/themes/portal.css` |

## Problem

The inference recipe grid (TASK-005) has column headers but no sort affordance. Users cannot sort by engine, tier, ctx, bench, or status without scrolling manually.

## Requirements

### Functional

1. **Sortable columns** — Recipe, Engine, Tier, Lifecycle, Ctx, Bench, Status columns are clickable in flat view; clicking sorts ascending, second click reverses to descending.
2. **Visual indicators** — Active sort column shows ↑ (asc) or ↓ (desc) in the header and is highlighted via `aria-sort` + accent color.
3. **Persist sort state** — `infSortCol` + `infSortDir` saved in the existing `spark-inference-filters` localStorage key alongside chip/view prefs.
4. **Grouped view** — Sort affordance suppressed (headers non-clickable, no indicators) when `infGroupByFamily` is true; groups keep their own internal order.
5. **Tiebreaker** — When `infSortCol` is set, `compareInfValues()` is primary and `infProfileSort()` is the tiebreaker.

### Out of scope

- Sorting within family groups
- Backend API changes

## Acceptance criteria

- [x] Flat view: clicking any sortable column header sorts the grid; clicking again reverses direction
- [x] Active sort column shows ↑/↓ and accent color
- [x] Reload restores sort col + dir from localStorage
- [x] Grouped view: column headers have no sort affordance and clicks do nothing
- [x] Model path column is intentionally non-sortable (no stable key)

## Implementation notes

`infSortValue(p, col)` extracts per-column raw values (numeric for `ctx`/`bench`, string for others).
`compareInfValues(a, b, col, dir)` sorts nulls last, applies `localeCompare` for strings, numeric compare for numbers.
`renderInfGridHead(allowSort)` takes a boolean — `true` for flat view, `false` for grouped view — to conditionally render `data-inf-sort-col` attributes and `.inf-gh-sort` CSS class.
Click handler in the `inf-list` delegation block reads `e.target.closest('[data-inf-sort-col]')` and guards on `!infGroupByFamily`.

## Completion log

| Date | Owner | Result | Commit / PR |
|------|-------|--------|-------------|
| 2026-06-26 | fm/task-010-85 | done | b278d8b |
