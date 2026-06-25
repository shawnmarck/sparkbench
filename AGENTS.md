# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Portal shared inventory module (TASK-007)

`portal/assets/spark-inventory-grid.js` exposes `window.SparkInventoryGrid` — a reusable UX primitive library for inventory-style portal pages. Loaded in `portal/index.html` with `<script defer>`.

API: `renderSummary(el, {filtered, total, suffix})`, `compareValues(a, b, col, dir)`, `renderTable(container, opts)`, `renderChips(container, chips, active, onToggle)`, `toggleGrouped(wrapEl, flat, grouped, onRender)`.

Consumer tasks that should migrate to this module: TASK-002 (Models), TASK-005 (Inference full migration), TASK-004 (Explore). See the module header comment for integration examples.
