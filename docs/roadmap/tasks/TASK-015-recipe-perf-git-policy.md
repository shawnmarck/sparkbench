# TASK-015: Recipe perf in git — policy + sync runbook update

| Field | Value |
|-------|-------|
| **Status** | proposed |
| **Priority** | Seq 12 |
| **Owner** | — |
| **PR policy** | One PR |
| **Parallel-safe** | yes |
| **Depends on** | — |
| **Primary files** | `docs/runbooks/sparky-live-sync.md`, `docs/roadmap/README.md`, `scripts/sparky-protect-runtime.sh` |

## Problem

`sparky-live-sync.md` says **never commit** `data/model-verification.yaml` and treats runtime YAML as sparky-only. Product vision is the opposite for **shared cookbook**: recipes + perf + golden map + verify headlines should be **committed and pushed** so solo GB10 users inherit GB10 measurements.

## Requirements

### Functional

1. Rewrite sync runbook with two tiers:
   - **Shared (commit from maintainer):** `recipes/*.yaml` (incl. `bench_matrix`), `data/golden-recipes.yaml`, `data/model-catalog.yaml`, `data/model-verification.yaml` (headlines only).
   - **Local (never commit from sparky):** `portal/models.json`, `run/*`, `/models/*`, logs.
2. Update `sparky-protect-runtime.sh` — skip-worktree only for truly local files (`models.json`, maybe `inference-profiles.yaml` local toggles); **remove** recipes from skip-worktree if present.
3. Add maintainer workflow: after golden workflow → `git add recipes/ data/` → commit → push → `deploy-sparky.sh`.
4. Clarify headline `tok_s` in verify vs `bench_matrix` on recipe (verify = portal sort; matrix = detail).

### Out of scope

- Splitting verify into separate committed vs local files (future).

## Acceptance criteria

- [ ] No contradiction between live-sync doc and solo-user vision
- [ ] roadmap README agent rule updated (recipes + perf ARE committed)
- [ ] Protect script matches new policy

## Test plan

1. Review doc on techno; confirm agent won’t refuse recipe commits.
2. `git check-ignore` / skip-worktree audit on sparky.

## Completion log

| Date | Owner | Result | Commit / PR |
|------|-------|--------|-------------|
| — | — | — | — |
