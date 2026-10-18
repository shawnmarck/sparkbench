# SGLang Qwen3.8-27B DFlash2 (RadixArk NVFP4)

Golden for `radixark/qwen3.8-27b`. Packed NVFP4 target + the incoai DFlash2
draft already on disk (byte-identical to z-lab @ 50307d4c). Block size 8.
Not the BF16-lm_head checkpoint. MTP eugr stays a companion.

```bash
# preferred: profile switcher (stops other GPU engines)
spark inference up radixark-qwen3-8-27b-dflash2-sglang        # vision tower on
spark inference up radixark-qwen3-8-27b-dflash2-sglang-text   # --language-only

# low-level
spark engine sglang up
spark engine sglang status
spark engine sglang down
```

Image: `lmsysorg/sglang@sha256:00205b89…` (`nightly-cu134-20260909-708f51e`, sglang #35255 zombie-request fix). Not `dev-qwen38-27b-dflash2` (that pin predates the fix).

API: `http://sparky:8000/v1` · vision model `qwen3.8-27b-dflash2-sglang` · text model `qwen3.8-27b-dflash2-sglang-text`
Context 262144 · DFlash2 k=8 · max running 8 · vision: max 1920² px, 4 img/req · Prometheus `/metrics`.

PBM 2026-09-10 (vision on, nightly-cu134-20260909-708f51e): 38.1 / 19.1 / 10.7
at 4k / 50k / 100k vs MTP eugr 25.1 / 9.0 / 6.6. Prior language-only pin
(dev-qwen38-27b-dflash2): 41.3 / 17.2 / 10.4.
