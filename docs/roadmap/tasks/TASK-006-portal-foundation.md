# TASK-006: Portal foundation (CSS, defer, models poll)

| Field | Value |
|-------|-------|
| **Status** | done |
| **Priority** | Seq 1 (do first) |
| **Owner** | — |
| **PR policy** | **One PR** — entire task; merge before TASK-007+ |
| **Parallel-safe** | yes (no overlap with feature tasks if merged first) |
| **Depends on** | — |
| **Primary files** | `portal/index.html`, `portal/models.html`, `portal/themes/portal.css` (new), `install/common.sh` (cache headers, if needed) |

## Problem

Portal pages are monoliths with ~820 lines inline CSS in `index.html`, render-blocking `sparky-theme.js`, and remaining Opus audit gaps on `models.html` (duplicate `loadData`, poll when tab hidden). UI feature tasks (TASK-007+) will touch the same files — clean foundation first.

## Requirements

1. **Extract inline CSS** from `portal/index.html` to `portal/themes/portal.css` with browser cache-friendly serving (nginx `Cache-Control` if needed).
2. **`defer`** on `sparky-theme.js` in `index.html` and `models.html`.
3. **Models poll fixes:** visibility guard on 30s refresh (match index.html pattern); remove redundant double `loadData` after recipe actions unless still needed for race — document if kept.
4. **Optional:** `AbortController` on inference view switch in index (partial guard exists).

### Out of scope

- Shared inventory grid (TASK-007)
- Feature UX (TASK-002, 005, 004)

## Acceptance criteria

- [ ] Portal loads with external CSS; repeat visits cache CSS
- [ ] No render regression on System / Explore / Inference tabs
- [ ] Theme B nebula still works
- [ ] Models page stops polling when iframe/tab hidden
- [ ] Recipe action does not cause unnecessary duplicate full inventory fetch
- [ ] One PR to `origin`; task Completion log filled

## Test plan

1. Hard refresh + soft reload `http://sparky/` and `/models.html`
2. Theme A/B toggle
3. Models: trigger recipe scaffold; network tab shows sane fetch count
4. Hide tab 60s; models poll does not fire until visible

## Implementation notes

Source audit: [`reference/ui-improvements-opus.md`](../reference/ui-improvements-opus.md) items #8, #9, models notes.

## Completion log

| Date | Owner | Result | Commit / PR |
|------|-------|--------|-------------|
| 2026-06-25 | claude | Done | PR #task-006-portal-foundation |
