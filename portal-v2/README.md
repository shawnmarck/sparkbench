# Portal v2 — Vite + React + shadcn

## Dev (this machine)

```bash
cd portal-v2
npm install
npm run dev          # fixtures on by default (.env.development)
```

Against a live Spark host:

```bash
SPARK_HOST=sparky VITE_USE_FIXTURES=0 npm run dev
```

Fixtures are opt-in. Production builds never replace failed live requests with demo
data. For deliberate offline UI work, use `VITE_USE_FIXTURES=1`; to test the
legacy fallback behavior explicitly, use `VITE_ALLOW_FIXTURE_FALLBACK=1`.

## Information architecture

- **Command center** — live inference, memory, gateway activity, Benchmaster, endpoints
- **Spark operator** — Hermes-backed OOB chat, confirmed admin actions, goals, daily checks
- **Catalog** — benchmark-proven recipes and honest download/serve workflows
- **Library** — local weights, optional NAS shelf, safe removal, recipe creation
- **Recipes** — draft/testing/works lifecycle and memory-aware tuning
- **Benchmaster** — GPU and remote-intel queue controls, failures, recent runs
- **Health · Add-ons · Setup** — diagnostics and allowlisted host administration

Press `Ctrl/Cmd+K` anywhere for workflow navigation and safe global actions.

Install the optional agent runtime with `sudo bash install/spark-install hermes`.
Portal sessions expose typed SparkBench tools only; mutating actions are
proposals that require explicit confirmation.

## Build

```bash
npm run build        # → dist/
```

On Sparky, nginx serves the built SPA at `/v2/` while the legacy `portal/`
continues to serve `/` (see `install/common.sh`). Both portals share the same
root-level `/api/*` routes and `/models.json`.
