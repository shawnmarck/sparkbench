---
name: sparky-safe-sync
description: >-
  Git pull/push on a live Sparky box without stopping inference or regressing
  host-local state. Use when committing from /opt/spark, pulling updates on sparky,
  deploy sync, skip-worktree, or keeping custom files out of git.
---

# Sparky safe git sync

Operate on **`/opt/spark` while inference may be serving**. Never run `spark inference down`, `spark-install core`, or nginx/gateway restarts as part of a routine pull/push.

## Layers (what travels in git)

| Layer | Paths | On pull |
|-------|-------|---------|
| **Shared cookbook** | `recipes/`, `data/golden-recipes.yaml`, `data/model-catalog.yaml`, `data/model-verification.yaml`, `data/use-cases.yaml` | Update from origin |
| **Code** | `scripts/`, `install/`, `portal/`, `services/`, `docs/` | Update from origin |
| **Host-local (skip-worktree)** | `data/inference-profiles.yaml`, `data/inference-benchmarks.yaml` | **Keep sparky copy** — restored after pull |
| **Gitignored runtime** | `run/`, `logs/`, `portal/models.json`, `data/hf-*-queue.yaml` | Never in git |
| **Per-host custom** | `local/` (entire tree) | Never in git — put diffs here |

## Pull (live box)

```bash
cd /opt/spark
bash scripts/sparky-safe-pull.sh
```

This script:

1. Records active inference profile (does not stop it)
2. Runs `sparky-protect-runtime.sh` (clears wrong skip-worktree on shared cookbook)
3. Backs up host-local YAML → `git pull --ff-only` → restores host-local YAML
4. Runs `migrate-host-local-data.sh` and `spark-link-engine-bins.sh`
5. Optionally `spark models inventory` (read-only rebuild of portal JSON)

**Forbidden during pull:** `sudo bash install/spark-install core`, `spark inference down`, fleet golden workflow.

## Push (live box)

```bash
cd /opt/spark
bash scripts/sparky-safe-push.sh -m "Describe the shared cookbook change."
```

Preview without committing: `DRY_RUN=1 bash scripts/sparky-safe-push.sh -m "..."`

Never stages: `local/`, `run/`, `logs/`, `data/inference-profiles.yaml`, `data/inference-benchmarks.yaml`, `vendor/`, `bin/`.

## Custom / per-host files

If something must differ from the repo and is not host-local YAML:

1. Put it under **`local/`** (gitignored; see `local/README.example`)
2. Document the manual step in `local/notes.md` if needed
3. Do **not** skip-worktree shared cookbook files

## One-time / after clone

```bash
bash scripts/sparky-protect-runtime.sh
bash scripts/migrate-host-local-data.sh
bash scripts/spark-link-engine-bins.sh
```

## Verify no regression

```bash
spark inference status | head -12
git ls-files -v | grep '^S'    # only inference-profiles + inference-benchmarks
./scripts/deploy-sparky.sh --status   # from dev machine
```

## Remote deploy (dev machine → sparky)

Default path: `./scripts/deploy-sparky.sh` (already backs up host-local YAML on sparky).

Full runbook: `docs/runbooks/sparky-live-sync.md`
