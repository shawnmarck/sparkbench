# Sparky live sync — shared cookbook in git

Two ways to sync code with GitHub. **Recipes and GB10 perf data travel in git** so solo Spark clones inherit the cookbook.

| Path | Who | When |
|------|-----|------|
| **A — deploy from techno** | Cursor agent on techno | Default: commit cookbook → push → `./scripts/deploy-sparky.sh` |
| **B — git on sparky** | Agent on sparky | Pull when ready; commit maintainer cookbook updates back to GitHub |

**Never treat sparky `/opt/spark` as a throwaway clone** — it runs inference. Local-only state stays on the box.

## Layers

| Layer | Git? | What | On `git pull` |
|-------|------|------|----------------|
| **Shared cookbook** | Yes — commit & push | `recipes/*.yaml` (incl. `bench_matrix`, `kv_sweep`, `ctx_ladder`), `data/golden-recipes.yaml`, `data/model-catalog.yaml`, `data/model-verification.yaml` | **Update from origin** |
| **Code** | Yes | `scripts/`, `services/`, `portal/`, `docs/` | Update |
| **Host-local** | Tracked but skip-worktree on sparky | `data/inference-profiles.yaml` (enabled profiles), `data/inference-benchmarks.yaml` if used | Keep sparky copy |
| **Generated** | No | `portal/models.json`, `run/*`, `logs/` | Rebuild / ignore |
| **Weights** | No | `/models/*` | Never in git |

### Headline vs matrix

| Store | Role |
|-------|------|
| `data/model-verification.yaml` | Portal **Spark** column: `works` / tok/s headline on this host |
| `recipes/*.yaml` → `context.bench_matrix` | **GB10 cookbook** perf grid (ctx ladder, kv sweep) for all clones |
| `run/inference-benchmark-history.yaml` | Full bench v2 session history (local, optional export) |

Clones without local weights still see golden recipes and upstream GB10 perf from git. `works` on a clone means “verified on **this** box” after they run golden workflow.

## Maintainer workflow (after golden workflow on sparky)

```bash
cd /opt/spark
git add recipes/*.yaml data/model-verification.yaml data/golden-recipes.yaml data/model-catalog.yaml
git status   # review cookbook diff
git commit -m "Golden matrix: <model> GB10 bench data"
git push
```

On techno (or any clone): `git pull` — or `./scripts/deploy-sparky.sh` to push + pull sparky.

## One-time setup on sparky

```bash
cd /opt/spark
bash scripts/sparky-protect-runtime.sh
```

Marks **host-local** YAML only (`inference-profiles.yaml`, etc.). Does **not** hide recipes or shared `data/*.yaml`.

---

## Path A — deploy from techno (default)

```bash
./scripts/deploy-sparky.sh --status
./scripts/deploy-sparky.sh
SKIP_PUSH=1 ./scripts/deploy-sparky.sh
```

Deploy stashes tracked code edits, pulls `origin/main`, restores **host-local** YAML only, re-runs `sparky-protect-runtime.sh`. Shared cookbook files come from git.

---

## Path B — agent on sparky

```bash
cd /opt/spark
bash scripts/sparky-protect-runtime.sh
git fetch origin
git pull --ff-only origin main
bash scripts/apply-spark-patches.sh
spark models inventory
```

### Conflicts on shared cookbook

If sparky has local recipe edits you want to keep, merge manually — then push from maintainer path. Default for solo users: **take origin** (upstream cookbook).

### Host-local backup (profiles only)

```bash
cp data/inference-profiles.yaml /tmp/inference-profiles.yaml.bak
git pull --ff-only origin main
cp /tmp/inference-profiles.yaml.bak data/inference-profiles.yaml
bash scripts/sparky-protect-runtime.sh
```

---

## What went wrong before

1. **Deploy stashed `-u`** — removed host-only files not yet in git.
2. **Pull overwrote then restored stale verify/catalog** — fought the shared-cookbook model.
3. **skip-worktree on all `data/*.yaml`** — blocked pulling GB10 perf into clones.

## Check live state

```bash
./scripts/deploy-sparky.sh --status
cd /opt/spark && git ls-files -v | grep '^S'
spark inference status | head -12
```
