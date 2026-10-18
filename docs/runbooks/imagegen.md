# Image generation — Qwen-Image-2.1 NVFP4 (sparky)

Local text-to-image + image editing on the GB10 via ComfyUI, driven by
`scripts/spark-imagegen`. Outputs land in `run/imagegen/` (gitignored) and are
pasted into chat on request.

## Stack

| Piece | Where |
|-------|-------|
| Model (NVFP4 bundle: DiT + Qwen3-VL 8B encoder + VAE) | `/models/qwen/qwen-image-2.1/nvfp4/` |
| ComfyUI (pinned `99073836`) | `/home/techno/comfyui` |
| Daemon | systemd **user** unit `comfyui.service` (:8188, linger on) |
| Helper CLI | `/opt/spark/scripts/spark-imagegen` (stdlib only) |
| Outputs | `/opt/spark/run/imagegen/` |

Model files are **symlinked** into `/home/techno/comfyui/models/{diffusion_models,clip,vae}/`
— zero copy, edits to the shelf are live.

## Usage

```bash
spark-imagegen generate "a cobalt glass perfume bottle on marble, studio light" [--w 1024 --h 1024] [--steps 40] [--seed N] [--rgba] [--out P]
spark-imagegen edit /path/to/img.png "change the cap to brushed silver, keep everything else" [--seed N]
spark-imagegen status
```

Defaults: 1024x1024, 40 steps, Euler/simple, CFG 1. `--rgba` wraps the prompt
for native transparent output. See the bundle's `PROMPTING.md` for prompt style
(attributes next to objects; quote exact text for lettering).

## Performance / coexistence

- ~30 s warm per 1024px image alongside the live vLLM profile (94 GB) —
  ComfyUI adds ~10 GB; ~105/128 GB total. Verified no vLLM disruption.
- Cold start (first generation after daemon restart) adds ~8 s for kernel JIT.

## Known limitations

- **Conditioning runs stock** (slower, slightly different output). The optional
  `runtime/qwen21-nvfp4-conditioning.patch` (native NVFP4 matmul, ~2.3x author
  speedup) is NOT applied: triton JIT needs `Python.h`
  (`sudo apt install python3.12-dev`), then from `/home/techno/comfyui`:
  `git apply /models/qwen/qwen-image-2.1/nvfp4/runtime/qwen21-nvfp4-conditioning.patch`
  and `systemctl --user restart comfyui`.
- Triton cache: `TRITON_CACHE_DIR=/home/techno/.triton-cache-comfy` (default
  `~/.triton/cache` is root-owned by the vLLM stack).
- Python headers via `CPATH` point at the uv-managed 3.12 (no sudo needed).
- License: Qwen Research License — **non-commercial only** (upstream dropped
  Apache 2.0 on the 2.1 line).

## Ops

```bash
systemctl --user status comfyui        # daemon state
journalctl --user -u comfyui -f        # logs
systemctl --user restart comfyui       # after model/patch changes
```

Survives reboots (user unit + `loginctl enable-linger`).
