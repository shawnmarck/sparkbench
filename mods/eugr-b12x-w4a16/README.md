# eugr b12x W4A16 overlays (Ornith-1.5)

Host-side file overlays for `eugr/spark-vllm-b12x`. MTP + CUDA graphs crash
on stock b12x W4A16 (`undefined metadata_row`, `torch.empty` during capture).

Source: [MiaAI-Lab/Ornith-1.5-35B-A3B-DGX-Spark](https://github.com/MiaAI-Lab/Ornith-1.5-35B-A3B-DGX-Spark) `patches/` (MIT).

Mounted read-only into:

```
/usr/local/lib/python3.12/dist-packages/b12x/moe/_shared/kernels/w4a16/kernel.py
/usr/local/lib/python3.12/dist-packages/b12x/moe/_shared/kernels/w4a16/route_pack.py
```
