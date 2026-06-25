# Sparky live sync — avoiding regressions

Two ways to sync code with GitHub. **Runtime data always stays on sparky.**

| Path | Who | When |
|------|-----|------|
| **A — deploy from techno** | Cursor agent on techno | Default for shared code: commit → push → `./scripts/deploy-sparky.sh` |
| **B — git on sparky** | Agent running on sparky | Local dev on the box; pull / rebase / merge when ready |

**Never treat sparky `/opt/spark` as a throwaway clone** — it runs inference and holds live audit state.

## Layers

| Layer | Where | What | Overwrite from git? |
|-------|--------|------|---------------------|
| **Code** | techno → GitHub → sparky | `scripts/`, `recipes/`, `services/`, `portal/`, `docs/`, `hermes/` | Yes (code paths only) |
| **Runtime data** | sparky only | `data/model-verification.yaml`, `inference-benchmarks.yaml`, `inference-profiles.yaml`, `model-catalog.yaml` | **Never** |
| **Build/vendor** | sparky only | `vendor/`, `bin/llama-*`, `run/` | Ignore / local OK |

Runtime data is updated by **golden audit**, **bench v2**, **`spark models verify`**, and **`spark models inventory`** on sparky. Git copies are templates or stale snapshots — not the portal source of truth.

## One-time setup on sparky

```bash
cd /opt/spark
bash scripts/sparky-protect-runtime.sh
```

Marks the four runtime YAML files `skip-worktree` so `git status` doesn’t noise and agents are reminded not to commit them from sparky.

---

## Path A — deploy from techno (default)

```bash
# On techno
./scripts/deploy-sparky.sh --status
./scripts/deploy-sparky.sh            # push + pull on sparky
SKIP_PUSH=1 ./scripts/deploy-sparky.sh  # pull only
```

Deploy **backs up runtime YAML → pulls code → restores runtime → apply patches**. Does not restart inference. Does not `stash -u`.

---

## Path B — agent on sparky (local dev)

Use when experimenting directly on sparky or when a sparky-resident agent syncs on its own schedule.

```bash
cd /opt/spark
bash scripts/sparky-protect-runtime.sh
git fetch origin
git status
spark inference status | head -12
```

### Sync when ready

**No local commits on sparky** (only dirty vendor / skip-worktree data):

```bash
git pull --ff-only origin main
bash scripts/apply-spark-patches.sh   # idempotent; safe if code already merged
```

**Local commits on sparky** (experiments to keep):

```bash
git rebase origin/main    # linear history — preferred if you know the rebase
# or
git merge origin/main     # merge commit — safer if unsure
```

After rebase/merge, if runtime YAML conflict: **keep the sparky working-tree versions** (live audit state), not origin’s templates:

```bash
git checkout --ours data/model-verification.yaml   # during merge, "ours" = current branch
# or restore from backup before sync (see below)
bash scripts/sparky-protect-runtime.sh
```

### Manual runtime backup (if not using deploy)

When `git pull` refuses because origin changed tracked data files:

```bash
cp data/model-verification.yaml /tmp/model-verification.yaml.bak
cp data/inference-profiles.yaml /tmp/inference-profiles.yaml.bak
cp data/inference-benchmarks.yaml /tmp/inference-benchmarks.yaml.bak
cp data/model-catalog.yaml /tmp/model-catalog.yaml.bak
git pull --ff-only origin main
cp /tmp/model-verification.yaml.bak data/model-verification.yaml
cp /tmp/inference-profiles.yaml.bak data/inference-profiles.yaml
cp /tmp/inference-benchmarks.yaml.bak data/inference-benchmarks.yaml
cp /tmp/model-catalog.yaml.bak data/model-catalog.yaml
bash scripts/sparky-protect-runtime.sh
```

### Sparky-local agent checklist

- [ ] `sparky-protect-runtime.sh` run
- [ ] `spark inference status` — note active profile
- [ ] No `git stash -u` on `recipes/` or `services/`
- [ ] Local commits eventually land on techno → GitHub (don’t drift forever)
- [ ] After recipe/service changes, smoke active profile if it was touched

---

## What went wrong before

1. **Deploy stashed `-u`** — removed host-only recipe files (AgentWorld) not yet in git.
2. **Premature audit promote** — set `works` before bench v2 (fixed in `golden-inventory-audit.py`).
3. **Pull overwrote runtime data** — git `model-verification.yaml` replaced live golden-audit results.

## Export runtime data (optional)

When git should reflect a known-good sparky audit snapshot:

```bash
# On sparky
git update-index --no-skip-worktree data/model-verification.yaml
# copy or diff to techno, commit there, re-protect on sparky
bash scripts/sparky-protect-runtime.sh
```

Default: leave runtime data on sparky only.

## Check live state

```bash
# From techno
./scripts/deploy-sparky.sh --status

# On sparky
cd /opt/spark && git fetch origin
git rev-parse --short HEAD origin/main HEAD
git ls-files -v | grep '^S'
spark inference status | head -12
```
