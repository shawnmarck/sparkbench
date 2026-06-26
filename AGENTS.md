# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Portal shared inventory module (TASK-007)

`portal/assets/spark-inventory-grid.js` exposes `window.SparkInventoryGrid` — a reusable UX primitive library for inventory-style portal pages. Loaded in `portal/index.html` with `<script defer>`.

API: `renderSummary(el, {filtered, total, suffix})`, `compareValues(a, b, col, dir)`, `renderTable(container, opts)`, `renderChips(container, chips, active, onToggle)`, `toggleGrouped(wrapEl, flat, grouped, onRender)`.

Consumed by TASK-002 (Models — done) and TASK-005 (Inference — done; uses `renderSummary` for the count line; grid rows rendered inline like Models — sort uses local `compareInfValues()` in `index.html`, not `SparkInventoryGrid.compareValues`). TASK-004 (Explore Shortlist) is done and uses `SparkInventoryGrid.compareValues` for sort. See the module header comment for integration examples.

## Client activity (TASK-001)

Pipeline: Gateway (`:9000`, `spark-inference-gateway.py`) appends JSONL to `run/inference-activity.jsonl` → Activity API (`:8769`, `spark-client-activity.py`) reads JSONL → nginx proxies `/api/activity` → Portal System tab widget.

- `json.dumps(session, separators=(",", ":"))` used in gateway to minimize JSONL line size
- Gateway `run/inference-activity.jsonl` is git-ignored; events survive gateway restarts
- Activity API is LAN-only, no auth; `install/24-client-activity-api.sh` handles systemd + nginx
- Nginx config is centralized in `install/common.sh` `write_nginx_portal_site`; add new locations there, not via sed

## Explore Shortlist / Compare view (TASK-004)

`portal/index.html` Explore card now has three sub-nav tabs persisted in `localStorage` key `sparky-explore-tab`: **Browse** (original browse + detail flow), **Shortlist** (compare table), **Downloads** (download queue full-width).

Shortlist state: `expShortlistItems` (from `data.queue.explore`), `expShortlistSelected` (Set of ids), `expShortlistSort` (`{col, dir}`).

Status enrichment: `queue_list()` in `spark-hf.py` derives `status` per explore item: `downloading > download_queued > gated > on_disk > saved`. Matched by `(repo, inventory_path)`.

Snapshot: sent client→server at save time in the POST body `snapshot: {format, engine, size_bytes, size_human, spark_fit, spark_fit_label, badges, dest}`. Server stores it on the explore queue item.

Dedupe key: `(repo, intent, inventory_path)` — stable across HF API response drift. Deduped items preserve the same `id` so UI selections survive re-saves.

Legacy items (no snapshot): enriched client-side on first Shortlist open, capped at 10 concurrent fetches via `expEnrichShortlistItems()`.

Shortlist detail drawer (`#exp-shortlist-drawer`): separate state (`expSlVariants`, `expSlSelectedVariantId`) from browse detail (`expVariants`, `expSelectedVariantId`) — no state corruption on tab switch.
