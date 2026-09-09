# SGLang Qwen3.8-27B DFlash2 (RadixArk NVFP4)

Golden for `radixark/qwen3.8-27b`. Packed NVFP4 target + the incoai DFlash2
draft already on disk (byte-identical to z-lab @ 50307d4c). Block size 8.
Not the BF16-lm_head checkpoint. MTP eugr stays a companion.

```bash
# preferred: profile switcher (stops other GPU engines)
spark inference up radixark-qwen3-8-27b-dflash2-sglang

# low-level
spark engine sglang up
spark engine sglang status
spark engine sglang down
```

API: `http://sparky:8000/v1` · model `qwen3.8-27b-dflash2-sglang`
Context 262144 · DFlash2 k=8 · max running 8.

PBM 2026-09-09: 41.3 / 17.2 / 10.4 at 4k / 50k / 100k vs MTP eugr 25.1 / 9.0 / 6.6.
