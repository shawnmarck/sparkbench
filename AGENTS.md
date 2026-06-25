# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Portal shared inventory module (TASK-007)

`portal/assets/spark-inventory-grid.js` exposes `window.SparkInventoryGrid` — a reusable UX primitive library for inventory-style portal pages. Loaded in `portal/index.html` with `<script defer>`.

API: `renderSummary(el, {filtered, total, suffix})`, `compareValues(a, b, col, dir)`, `renderTable(container, opts)`, `renderChips(container, chips, active, onToggle)`, `toggleGrouped(wrapEl, flat, grouped, onRender)`.

Consumer tasks that should migrate to this module: TASK-002 (Models), TASK-005 (Inference full migration), TASK-004 (Explore). See the module header comment for integration examples.

## Client activity (TASK-001)

Pipeline: Gateway (`:9000`, `spark-inference-gateway.py`) appends JSONL to `run/inference-activity.jsonl` → Activity API (`:8769`, `spark-client-activity.py`) reads JSONL → nginx proxies `/api/activity` → Portal System tab widget.

- `json.dumps(session, separators=(",", ":"))` used in gateway to minimize JSONL line size
- Gateway `run/inference-activity.jsonl` is git-ignored; events survive gateway restarts
- Activity API is LAN-only, no auth; `install/24-client-activity-api.sh` handles systemd + nginx
- Nginx config is centralized in `install/common.sh` `write_nginx_portal_site`; add new locations there, not via sed
