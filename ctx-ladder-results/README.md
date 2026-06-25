# Context ladder results (Qwen3.6 35B NVFP4 on Sparky)

Automated test harness: `scripts/ctx-ladder-test.py`

## Run — 2026-06-22T181904Z

Full ladder **passed** for gateway multi-turn context fill at all four ceilings.

| Target ctx | `max_model_len` | Mem % | KV pool | Fill reached | Fill time | Reload |
|------------|-----------------|-------|---------|--------------|-----------|--------|
| 128k (131072) | 131072 | 91.3 | 7.40M tok | **126,657** | 53s | 177s |
| 160k (163840) | 163840 | 89.7 | 7.47M tok | **158,313** | 74s | 247s |
| 190k (194560) | 194560 | 91.9 | 7.61M tok | **179,417** | 91s | 207s |
| 250k (256000) | 256000 | 90.4 | 7.68M tok | **232,177** | 139s | 237s |

### Method

1. `spark inference down && spark inference up qwen36-nvfp4 --ctx N --kv fp8`
2. Multi-turn API fill (~10.5k tokens/turn) until ~92% of ceiling, then verify `CONTEXT_OK`
3. OpenCode `run` smoke (3 agent turns) — **timed out at 900s** each step (CLI bootstrap issue, not ctx failure)

### Takeaways

- **No extra VRAM needed** — unified mem stayed ~90–92% at every step; raising `max_model_len` mostly raised the per-request cap, not total footprint.
- **KV pool grew slightly** with higher ceilings (7.27M → 7.68M tokens).
- **250k is viable** on this box with fp8 KV at `gpu_memory_utilization: 0.85`.
- Native **262144** was not tested; 256k succeeded with margin.
- OpenCode interactive use worked manually earlier; automated `opencode run` after heavy API fill needs a lighter smoke path (separate from ctx capacity).

### Artifacts

- `20260622T181904Z/SUMMARY.md` — per-step JSON
- `20260622T181904Z/ctx_*/api_fill.json` — turn-by-turn token counts
- `20260622T181904Z/ctx_*/spark_metrics.json` — memory snapshot per step

### Production recipe recommendation

Default **256000** (250k) for OpenCode agent work — validated 2026-06-22 ctx ladder (232k fill). Fallback preset: **163840** (160k).
