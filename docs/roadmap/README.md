# Roadmap tasks — agent workflow

`docs/ROADMAP.md` is the **index** (vision, Model Lab loop, priority queue).  
Actionable work lives in **`tasks/`** — one markdown file per deliverable.

## Main agent (Techno)

**Work locally on techno** (`~/projects/sparky` or Cursor worktree). **Do not** implement directly on sparky unless explicitly asked.

```text
1. Read ROADMAP.md → pick next row where Status = ready (top to bottom)
2. Open task file → set Status: in_progress, Owner: <session>
3. Branch from main:  feat/TASK-00N-short-name
4. Implement full task scope → one PR to origin
5. Run test plan locally where possible; note sparky deploy smoke for human review
6. Update task Completion log + ROADMAP backlog Status → done (after merge)
```

### One PR per task

Each task = **one pull request** = full **Definition of Done** for that feature or rework.

- Do **not** split a task into multiple PRs (no “part 1 table, part 2 pane”).
- Do **not** combine unrelated tasks into one PR.
- Merge PRs **one at a time, in backlog sequence** (Seq 1 → 2 → …). Human reviews and merges; then agent picks up next `ready` task.

### Definition of Done

- [ ] All **Acceptance criteria** in the task file checked
- [ ] **Test plan** executed (document results in Completion log)
- [ ] Code on branch; **one PR** to `origin/main`
- [ ] Task file updated: Status `done`, Completion log row (date, PR link, commit)
- [ ] `docs/ROADMAP.md` backlog row Status → `done`
- [ ] Post-merge (human): `./scripts/deploy-sparky.sh` to sparky when the change needs runtime verification

**Runtime data:** never commit sparky-local `data/*.yaml` changes from audits/bench. See [`runbooks/sparky-live-sync.md`](../runbooks/sparky-live-sync.md).

### Sparky verification

Agent on techno cannot always hit sparky. In PR description, list:

- What was tested locally (lint, static review, unit if any)
- **Sparky smoke checklist** for reviewer (URLs, curl commands from task Test plan)

## Pick up a task (checklist)

1. ROADMAP backlog — next `ready` by **Seq**
2. Task file — read Problem, Requirements, Acceptance criteria
3. `in_progress` + Owner
4. Single branch → single PR
5. Completion log + ROADMAP status after merge

## Task file template

Copy `tasks/TEMPLATE.md` for new work.

## Status values

`proposed` → `ready` → `in_progress` → `blocked` → `done` → `cancelled`

## Superseded tasks

| Old | New |
|-----|-----|
| TASK-002 (table only) + TASK-003 (pane only) | **TASK-002-models-inventory-ux.md** (combined) |
