# Model picks — why these models

**Started:** 2026-06-21  
**Status:** See `/opt/spark/logs/model-download-latest.log`  
**Batch manifest:** `examples/download-batch.yaml`

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

### 5. `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` (Q4_K_M + Q5_K_M ~40 GB)
**Path:** `/models/unsloth/qwen3-coder-30b-a3b-instruct/gguf/`  
**Role:** **Agentic coding** · llama.cpp  
**Why:** DGX Spark forum consensus for coding quality/speed is Qwen3-Coder family. MoE 30B-A3B fits Spark well. Q4 for daily use, Q5 when you want sharper code gen. llama.cpp path for bake-off.

### 6. `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` (~65 GB)
**Path:** `/models/deepseek-ai/deepseek-r1-distill-qwen-32b/hf/`  
**Role:** **Reasoning / intelligence** · vLLM  
**Why:** Distilled R1 reasoning into a 32B dense model — strong chain-of-thought for hard agent planning without 671B MoE complexity. “Optimize for intelligence” slot in your library.

### 7. `microsoft/phi-4` (~29 GB)
**Path:** `/models/microsoft/phi-4/hf/`  
**Role:** **Fast general** · vLLM  
**Why:** Spark community pick for low-latency general tasks — quick drafts, classification, short summarization before escalating to bigger models. Good “first pass” in agent pipelines.

## Gemma 4 add-on (separate script)

Run `scripts/spark-download-gemma4.sh` after the main batch.

### 8. `google/gemma-4-12b-it`
**Path:** `/models/google/gemma-4-12b-it/` — vLLM + GGUF variants

### 9. `google/gemma-4-26b-a4b-it`
**Path:** `/models/google/gemma-4-26b-a4b-it/` — MoE vision/text

### 10. `yuxinlu1/gemma-4-12B-coder-fable5-composer2.5-v1-GGUF`
**Path:** `/models/yuxinlu1/gemma-4-12b-coder-fable5-composer2.5-v1/gguf/` — coding GGUF

**Removed 2026-06-21:** Hermes-3-8B, Gemma-3-27b (superseded by Hermes-4 and Gemma 4 above).
