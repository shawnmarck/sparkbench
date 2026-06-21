# Model library — download batch report

**Started:** 2026-06-21  
**Status:** See `/opt/spark/logs/model-download-latest.log`  
**Batch manifest:** `MODEL-DOWNLOAD-BATCH.yaml`

---

## Your two requested models

### 1. `nvidia/Qwen3.6-35B-A3B-NVFP4` (~24 GB)
**Path:** `/models/nvidia/qwen3.6-35b-a3b/nvfp4/`  
**Engine:** vLLM (NVFP4 — native Spark/Blackwell path)

**Why:** NVIDIA’s own NVFP4 build of Qwen3.6 35B-A3B MoE. Only ~3B active params per token but 35B total — fits easily in 128GB unified memory with room for KV cache. This is the primary **vLLM / production inference** variant for your new flagship Qwen.

### 2. `unsloth/Qwen3.6-35B-A3B-GGUF` (selected quants ~44 GB, not full 550 GB repo)
**Path:** `/models/unsloth/qwen3.6-35b-a3b/gguf/`  
**Files downloaded:**
- `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` — balanced quality/size for **llama.cpp**
- `Qwen3.6-35B-A3B-MXFP4_MOE.gguf` — MoE-aware quant, relevant for GB10 experimentation

**Why:** Same base model as above but for the **llama.cpp** engine path in your future bake-off. The full Unsloth repo contains every quant (~550 GB); we pulled two practical ones only.

---

## Curated additions (~230 GB) — Hermes / agentic focus

Picked for **single DGX Spark (128 GB)**, **Hermes-style agent workloads**, and your two-engine plan (vLLM + llama.cpp).

### 3. `nvidia/Qwen3-30B-A3B-NVFP4` (~18 GB)
**Path:** `/models/nvidia/qwen3-30b-a3b/nvfp4/`  
**Role:** Fast MoE general model · **vLLM**  
**Why:** Smaller/faster sibling to Qwen3.6. Good for interactive agent loops when you don’t need max intelligence — higher tok/s, less memory pressure, quick tool-calling rounds.

### 4. `NousResearch/Hermes-4-14B` (~30 GB)
**Path:** `/models/nousresearch/hermes-4-14b/hf/`  
**Role:** **Tool calling / Hermes-aligned agentic** · vLLM  
**Why:** Hermes line is literally tuned for function calling and agent frameworks. 14B is small enough to leave headroom for long context + tools while staying responsive. Pairs naturally with Hermes agent stack.

### 5. `NousResearch/Hermes-3-Llama-3.1-8B` (~16 GB)
**Path:** `/models/nousresearch/hermes-3-llama-3.1-8b/hf/`  
**Role:** **Fast tool-calling sidecar** · vLLM  
**Why:** When you want snappy tool routing, plan summarization, or a cheap “router” model in multi-agent setups. Proven Hermes 3 tool format; tiny footprint on Spark.

### 6. `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` (Q4_K_M + Q5_K_M ~40 GB)
**Path:** `/models/unsloth/qwen3-coder-30b-a3b-instruct/gguf/`  
**Role:** **Agentic coding** · llama.cpp  
**Why:** DGX Spark forum consensus for coding quality/speed is Qwen3-Coder family. MoE 30B-A3B fits Spark well. Q4 for daily use, Q5 when you want sharper code gen. llama.cpp path for bake-off.

### 7. `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` (~65 GB)
**Path:** `/models/deepseek-ai/deepseek-r1-distill-qwen-32b/hf/`  
**Role:** **Reasoning / intelligence** · vLLM  
**Why:** Distilled R1 reasoning into a 32B dense model — strong chain-of-thought for hard agent planning without 671B MoE complexity. “Optimize for intelligence” slot in your library.

### 8. `microsoft/phi-4` (~29 GB)
**Path:** `/models/microsoft/phi-4/hf/`  
**Role:** **Fast general** · vLLM  
**Why:** Spark community pick for low-latency general tasks — quick drafts, classification, short summarization before escalating to bigger models. Good “first pass” in agent pipelines.

### 9. `google/gemma-3-27b-it` (~55 GB)
**Path:** `/models/google/gemma-3-27b-it/hf/`  
**Role:** **Balanced general + long context** · vLLM / SGLang  
**Why:** Frequently recommended on Spark for balanced quality and long context. Native function-calling support in SGLang-oriented stacks. Non-Qwen diversity so you’re not single-vendor for everything.

---

## Total estimated download: ~280 GB

| Category | Models | ~GB |
|----------|--------|-----|
| Your picks (vLLM + GGUF) | Qwen3.6 NVFP4 + 2 GGUF quants | ~68 |
| Fast / routing | Qwen3-30B NVFP4, Hermes-3-8B, Phi-4 | ~63 |
| Agentic / tools | Hermes-4-14B | ~30 |
| Coding | Qwen3-Coder GGUF ×2 | ~40 |
| Reasoning | DeepSeek-R1-Distill-32B | ~65 |
| General | Gemma-3-27b-it | ~55 |

---

## Not downloaded (and why)

| Model | Reason |
|-------|--------|
| Full Unsloth GGUF repos | 500+ GB each — only selected quants |
| `nvidia/Qwen3-Coder-*-NVFP4` | Gated — requires HF login/token on Spark |
| `nvidia/Llama-3.3-Nemotron-*` | Gated NVIDIA NIM models |
| 70B+ dense models | Tight for 128GB with agent context + KV |
| MiniMax M2.7 / Qwen3.5-397B | Multi-node territory; you’re single Spark for now |

**Recommendation:** Add `HF_TOKEN` to `/etc/spark/` or `hf login` on Spark to unlock NVIDIA gated NVFP4 coder models later.

---

## After downloads complete

```bash
# Check progress
tail -f /opt/spark/logs/model-download-latest.log

# Push to NAS shelf (when ready)
spark-shelf-push --all

# Disk usage
du -sh /models/*/*
```

---

## Next steps (when you’re back)

1. Confirm downloads finished (`/opt/spark/logs/`)
2. `spark-shelf-push --all` to back up to QNAP
3. Inference smoke test: Qwen3.6 NVFP4 on vLLM, Qwen3.6 Q4_K_M on llama.cpp
4. vLLM Studio vs Rookery bake-off using these paths
