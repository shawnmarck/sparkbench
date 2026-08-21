# Inspiration — 0xSero models view

Source: [x.com/0xSero/status/2090192921987330183](https://x.com/0xSero/status/2090192921987330183) (2026-08-19).  
Screenshot: [xsero-models-view.jpg](xsero-models-view.jpg)

Steal from this when we build v2 Models / usage. Do not copy the product. Control plane stays our `/api/*`.

## What works

- One huge lifetime number at the top (`6.82B Proxied tokens`), then a quiet strip of smaller facts (requests, sessions, streak, success).
- GitHub-style year heatmap for “tokens per day,” with a hover that names the day.
- Tabs under the hero: Models / Activity / Controller / Errors. Models is a table, not a card wall.
- Compact mix line above the table: in vs out, cache hit, decode. Same idea as our `24h · 30D · All` line.
- Per-row **tokens cell is a tiny stacked bar** (in vs out) plus `↑3.7b ↓15.7m`. That is the scan trick.
- Tabular numbers, lots of air, grayscale with green only for “good” (100% success / cache).
- Model column is icon + short id (`glm-5.2`), not a 60-char recipe slug.

## Map onto SparkBench

- Hero + heatmap + mix line can sit on v2 Home or a Usage tab using `/api/activity` `usage.windows` and later daily buckets.
- “By model” is our **by profile** table (`usage.profiles`). Add an in/out bar when we have prompt vs completion per row (we already store both).
- Heatmap needs day buckets we already keep in `run/inference-usage.json` `days` — expose them on `/api/activity` in a later control-plane PR, then paint this.
- Recipe list on Inference stays operational (switch / lifecycle). This layout is for **usage**, not the switcher.
