# Solo GB10 user backlog

**Vision:** Git repo = shared cookbook (recipes + GB10 perf). Clone → see all golden recipes → download only what you want → run on your Spark.

This index tracks the four vision gaps and high-leverage next steps. Work **one task = one PR** per [`README.md`](README.md).

| Seq | Task | Gap / leverage | Status | Doc |
|-----|------|----------------|--------|-----|
| 8 | First Spark setup guide | Onboarding | proposed | [TASK-011](tasks/TASK-011-first-spark-setup.md) |
| 9 | `spark models fetch` | Gap 1 — shelf-less download | proposed | [TASK-012](tasks/TASK-012-spark-models-fetch.md) |
| 10 | Golden badge in portal | Gap 2 — discoverability | proposed | [TASK-013](tasks/TASK-013-golden-badge-portal.md) |
| 11 | Fleet golden matrix in git | Gap 3 — perf completeness | proposed | [TASK-014](tasks/TASK-014-fleet-golden-matrix.md) |
| 12 | Recipe perf git policy | Gap 4 — verify vs recipes + sync doc | proposed | [TASK-015](tasks/TASK-015-recipe-perf-git-policy.md) |

## Vision gap mapping

| # | Gap | Task |
|---|-----|------|
| 1 | No one-command HF download for golden variant | TASK-012 |
| 2 | Golden not visible in portal for catalog-only models | TASK-013 |
| 3 | Fleet lacks committed `bench_matrix` / `kv_sweep` | TASK-014 |
| 4 | `model-verification.yaml` vs recipe perf + old “never commit data” policy | TASK-015 |

## Already shipped (foundation)

- Golden workflow layers: `scripts/spark-golden-workflow.py`
- Perf on recipes: `context.bench_matrix`, `kv_sweep`, `ctx_ladder`
- `data/golden-recipes.yaml` golden map
- `spark models golden` CLI

## Suggested execution order

1. **TASK-015** — unblock correct git hygiene (small doc/script PR).
2. **TASK-011** — solo user can orient immediately.
3. **TASK-012** — download path (highest product leverage).
4. **TASK-013** — portal discoverability.
5. **TASK-014** — long GPU run on sparky; batch recipe commits.

## Maintainer cadence (after TASK-014 / workflow runs)

```bash
# on sparky after golden workflow
git add recipes/*.yaml data/model-verification.yaml data/golden-recipes.yaml
git commit -m "Golden matrix: <model> GB10 bench data"
git push
./scripts/deploy-sparky.sh   # or pull on other clones
```
