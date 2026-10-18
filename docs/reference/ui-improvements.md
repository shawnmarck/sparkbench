# Portal UI

The Sparky portal is a static nginx site on :80. The React app (`portal-v2/`, built to `portal/`) is the default at `/`. Legacy single-page UI is archived at `/archive/v1/` (`portal/archive/v1/index.html`); inventory grid at `/archive/v1/models.html`.

LAN-trusted. Do not expose :80 to the WAN.

## Tabs

| Tab | URL | What it does |
|-----|-----|----------------|
| System | `/` | GPU, health, client activity, usage counters |
| Models | `/#models` or `/models.html` | Inventory grid, Model Lab, verify, fetch |
| Explore | `/#explore` | Hugging Face search, trending, download queue |
| Inference | `/#inference` | Active profile, switch, logs, engine filter, eugr upgrade banner |
| Benchmaster | `/#benchmaster` | Overnight perf / intel queue |

Optional nav buttons (if those services are installed):

| Button | Port | Notes |
|--------|------|-------|
| Hermes | :9119 | Agent UI |
| Chat | :3000 | Open WebUI |
| Netdata | :19999 | Host metrics |

Shared grid widgets live in `portal/assets/spark-inventory-grid.js` (`window.SparkInventoryGrid`).

## Data the UI reads

| File / API | Role |
|------------|------|
| `portal/models.json` | Built by `spark models inventory` (gitignored) |
| `GET /api/inference/status` | Active profile (`?lite=1` for nav) |
| `GET /api/gpu` | GPU widget |
| `GET /api/activity` | Client activity (1h / 24h) |
| `GET /api/hf/*` | Explore queue |
| `GET /api/benchmaster/*` | Queue + control |
| `GET /api/shelf/status` | NAS mount / job |

Rebuild inventory after catalog or verify edits: `spark models inventory`.

## Public site vs this portal

[sparkbench.dev](https://sparkbench.dev) is a static build from the same YAML (`model-catalog`, `model-verification`, `golden-recipes`, `perfbench-metrics`, `published-evals`). It does not talk to your box.

Portal shows host-local state: what is downloaded, what is serving, what Benchmaster is doing.

## Themes

`?theme=b` or `localStorage.sparky-theme`. Stylesheets: `portal/themes/`.
