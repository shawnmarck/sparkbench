# TASK-005: Inference page UX overhaul

| Field | Value |
|-------|-------|
| **Status** | done |
| **Priority** | Seq 5 |
| **Owner** | — |
| **PR policy** | **One PR** — flat recipe grid + ctx labeling + view toggle |
| **Depends on** | TASK-002 pattern reference (Models grid); can parallel if different sections |
| **Primary files** | `portal/index.html` |

## Problem

Recipe list defaults to **family-grouped shelf view** (`<details>` with "N shelves") — hard to scan. Yellow/gold `.inf-profile .meta` looks like warnings but shows **recipe YAML defaults** (shelf, engine, ctx) even though ctx/kv are adjustable in the context picker before switch.

Context window picker works well. Log functionality stays as-is.

## Requirements

### Functional

1. **Flat recipe grid by default** — column header row like Models page; not nested family shelves.
2. **View toggle** — Flat list | By family (persist in `spark-inference-filters`); Expand/Collapse all only in family mode.
3. **Showing A of B** — summary line like Models `#summary`; Switchable controlled by chip (not ambiguous count suffix).
4. **Ctx labeling** — three contexts:
   - **Recipe default** — list column, muted styling
   - **Launch selection** — selected row shows override when `infCtxSelection` differs
   - **Active runtime** — `#inf-active-meta` only
5. **Remove default warn color** from `.inf-profile .meta`; keep warn for `#inf-msg`, switch banner, log overlay.
6. **Keep unchanged:** `#inf-ctx-panel`, log tail, log overlay, Switch/Benchmark/Stop, search + filter chips.

### Out of scope

- Backend API changes
- Extract inline CSS
- Models page changes

## Acceptance criteria

- [ ] Default view is flat column grid (no collapsed family groups)
- [ ] Flat / By family toggle persists
- [ ] Showing A of B matches Models pattern
- [ ] Recipe meta not default yellow; launch override visible on selected row
- [ ] Context picker behavior unchanged
- [ ] Log section and overlay unchanged (heavy/ds4 switch still opens overlay)

## Test plan

1. `/#inference` — flat list, count matches filters
2. Toggle By family — groups + expand/collapse
3. Change ctx/kv — selected row shows launch preview
4. Switch profile — active meta shows runtime ctx
5. Reload — localStorage prefs restored

## Implementation notes

Refactor `renderInfProfiles()` using Models patterns: `renderGridHead`, flat vs grouped branch, `infGroupByFamily` (default `false`).

Use `SparkInventoryGrid` from TASK-007 where applicable (summary line, sort, flat/grouped toggle already wired for the Inference count line).

Extend `infProfilesSnapshot()` with view mode. Hidden `#inf-select` + `pickInfProfile()` unchanged.

Suggested columns: Recipe, Model path, Engine, Tier, Lifecycle, Ctx (default), Bench, Status.

## Completion log

| Date | Owner | Result | Commit |
|------|-------|--------|--------|
| 2026-06-26 | fm/task-005-7v | done | fm/task-005-7v |
