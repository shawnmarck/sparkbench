# Qwen3.8-Flash-Next (Mia kit)

Not a drop-in for the 27B DFlash2 golden. This is Qwen3.8-Flash-Next
(125B-A6B MoE VLM) via MiaAI's single-Spark pack.

The upstream launcher is cloned **next to the weights**, not into this
repo (AGPL kit, large patches):

```
/models/mia-ailab/qwen3.8-flash-next/kit     # git clone of MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark
/models/mia-ailab/qwen3.8-flash-next/hf      # HF_HOME — Mia-AiLab/Qwen3.8-Flash-Next-NVFP4
```

Spark wrapper: `scripts/spark-flash-next` (`spark engine flashnext`).
Profile: `mia-ailab-qwen3.8-flash-next-vllm` (lifecycle `testing` until bench v2).

`PORT=8000` (Mia default is 8888). `HOST_RESERVE_GIB=26`. First boot packs
a ~27 GiB PLE table under `~/.cache/vllm/ple_cache/` (~11+ min to `/v1/models`).

PBM 2026-09-11 (tools ok): **36.1 / 21.6 / 19.6** tok/s at 4k / 50k / 100k.
Golden 27B DFlash2 vision is 38.1 / 19.1 / 10.7. Lifecycle stays `testing`
until bench v2.

Watch: Mia (@MiaAI_lab) said a kit **files** drop should cut TTFT hard.
Daily check is `scripts/spark-flashnext-watch` (GitHub kit SHA + X mirrors).
Baseline kit: `d038090` (2026-09-09 reduced-vocab drafting). Do not pull/bounce
on SHA move until we re-PBM.
