#!/usr/bin/env python3
"""Generate a faithful mock portal/models.json so models.html renders every column.
Writes into portal/ as a TRANSIENT test artifact (removed after evidence capture)."""
import json, os, sys

SCRIPT = os.path.abspath(__file__)
ROOT = os.getcwd()
assert os.path.isdir(os.path.join(ROOT, "portal")), "run from repo root"
PORTAL = os.path.join(ROOT, "portal")

models = [
    {
        "id": "unsloth/qwen3.6-27b", "rel_path": "unsloth/qwen3.6-27b",
        "name": "Qwen3.6-27B", "lab": "unsloth", "slug": "qwen3.6-27b",
        "hf_repo": "Qwen/Qwen3.6-27B", "status": "ready", "max_context": 262144,
        "param_b": 27, "param_active_b": None,
        "capabilities": ["general", "dense", "vllm", "llamacpp", "nvfp4", "agentic"],
        "engines": ["vllm", "llamacpp"], "pipeline_tag": "text-generation",
        "local": {"present": True, "size_human": "26.4 GB", "size_bytes": 28350000000},
        "shelf": {"present": True, "size_human": "28.1 GB", "size_bytes": 30180000000},
        "best_bench_tok_s": 142.7, "release_date": "2025-11-04",
        "spark_verify": {"spark_status": "works", "removal_pending": False},
        "inference_profiles": [
            {"id": "qwen36-27b-nvfp4", "name": "NVFP4 vLLM", "lifecycle": "production", "tier": "fast", "tok_s": 142.7},
            {"id": "qwen36-27b-gguf", "name": "Q4 GGUF", "lifecycle": "testing", "tier": "fast", "tok_s": 88.3},
        ],
    },
    {
        "id": "qwen/qwen3.6-27b", "rel_path": "qwen/qwen3.6-27b",
        "name": "Qwen3.6-27B (FP8)", "lab": "qwen", "slug": "qwen3.6-27b",
        "hf_repo": "Qwen/Qwen3.6-27B", "status": "ready", "max_context": 131072,
        "param_b": 27, "param_active_b": None,
        "capabilities": ["general", "dense", "vllm", "fp8"],
        "engines": ["vllm"], "pipeline_tag": "text-generation",
        "local": {"present": True, "size_human": "27.0 GB", "size_bytes": 29000000000},
        "shelf": {"present": False, "size_human": "—", "size_bytes": 0},
        "best_bench_tok_s": 131.0, "release_date": "2025-11-04",
        "spark_verify": {"spark_status": "works", "removal_pending": False},
        "inference_profiles": [
            {"id": "qwen36-27b-fp8", "name": "FP8 vLLM", "lifecycle": "production", "tier": "fast", "tok_s": 131.0},
        ],
    },
    {
        "id": "deepseek/r1-671b", "rel_path": "deepseek/r1-671b",
        "name": "DeepSeek-R1-671B", "lab": "deepseek", "slug": "r1-671b",
        "hf_repo": "deepseek-ai/DeepSeek-R1", "status": "partial", "max_context": 65536,
        "param_b": 671, "param_active_b": 37, "model_architecture": "moe",
        "capabilities": ["reasoning", "moe", "vllm", "agentic"],
        "engines": ["vllm"], "pipeline_tag": "text-generation",
        "local": {"present": True, "size_human": "404 GB", "size_bytes": 433800000000},
        "shelf": {"present": True, "size_human": "398 GB", "size_bytes": 427400000000},
        "best_bench_tok_s": 31.5, "release_date": "2025-09-15",
        "spark_verify": {"spark_status": "wip", "removal_pending": False},
        "inference_profiles": [
            {"id": "r1-671b-fp8", "name": "FP8 vLLM", "lifecycle": "testing", "tier": "heavy", "tok_s": 31.5},
        ],
    },
    {
        "id": "meta/llama-4-scout-17b", "rel_path": "meta/llama-4-scout-17b",
        "name": "Llama-4-Scout-17B", "lab": "meta", "slug": "llama-4-scout-17b",
        "hf_repo": "meta-llama/Llama-4-Scout-17B", "status": "ready", "max_context": 1048576,
        "param_b": 109, "param_active_b": 17,
        "capabilities": ["general", "moe", "vllm", "vision"],
        "engines": ["vllm"], "pipeline_tag": "text-generation",
        "local": {"present": True, "size_human": "98.2 GB", "size_bytes": 105400000000},
        "shelf": {"present": False, "size_human": "—", "size_bytes": 0},
        "best_bench_tok_s": 210.4, "release_date": "2025-10-22",
        "spark_verify": {"spark_status": "works", "removal_pending": False},
        "inference_profiles": [
            {"id": "scout17b-fp8", "name": "FP8 vLLM", "lifecycle": "production", "tier": "fast", "tok_s": 210.4},
        ],
    },
    {
        "id": "mistral/nemo-12b", "rel_path": "mistral/nemo-12b",
        "name": "Mistral-Nemo-12B", "lab": "mistral", "slug": "nemo-12b",
        "hf_repo": "mistralai/Mistral-Nemo-Base-2407", "status": "shelf-only", "max_context": 131072,
        "param_b": 12, "param_active_b": None,
        "capabilities": ["general", "dense", "llamacpp"],
        "engines": ["llamacpp"], "pipeline_tag": "text-generation",
        "local": {"present": False, "size_human": "—", "size_bytes": 0},
        "shelf": {"present": True, "size_human": "7.1 GB", "size_bytes": 7620000000},
        "best_bench_tok_s": None, "release_date": "2024-07-18",
        "spark_verify": {"spark_status": "unverified", "removal_pending": False},
        "inference_profiles": [],
    },
    {
        "id": "qwen/qwen3-coder-30b", "rel_path": "qwen/qwen3-coder-30b",
        "name": "Qwen3-Coder-30B", "lab": "qwen", "slug": "qwen3-coder-30b",
        "hf_repo": "Qwen/Qwen3-Coder-30B-A3B", "status": "downloading", "max_context": 262144,
        "param_b": 30, "param_active_b": 3,
        "capabilities": ["code", "moe", "vllm"],
        "engines": ["vllm"], "pipeline_tag": "text-generation",
        "local": {"present": True, "size_human": "18.4 GB", "size_bytes": 19770000000},
        "shelf": {"present": False, "size_human": "—", "size_bytes": 0},
        "best_bench_tok_s": 165.2, "release_date": "2025-10-30",
        "spark_verify": {"spark_status": "failed", "removal_pending": False},
        "inference_profiles": [
            {"id": "coder30b-fp8", "name": "FP8 vLLM", "lifecycle": "draft", "tier": "fast"},
        ],
    },
    {
        "id": "rdtand/qwen3.6-27b", "rel_path": "rdtand/qwen3.6-27b",
        "name": "Qwen3.6-27B (PrismaQuant)", "lab": "rdtand", "slug": "qwen3.6-27b",
        "hf_repo": "Qwen/Qwen3.6-27B", "status": "missing", "max_context": 131072,
        "param_b": 27, "param_active_b": None,
        "capabilities": ["general", "dense", "vllm", "experimental"],
        "engines": ["vllm"], "pipeline_tag": "text-generation",
        "local": {"present": False, "size_human": "—", "size_bytes": 0},
        "shelf": {"present": False, "size_human": "—", "size_bytes": 0},
        "best_bench_tok_s": None, "release_date": "2025-11-04",
        "spark_verify": {"spark_status": "unverified", "removal_pending": True},
        "inference_profiles": [],
    },
    {
        "id": "google/gemma-3-12b", "rel_path": "google/gemma-3-12b",
        "name": "Gemma-3-12B", "lab": "google", "slug": "gemma-3-12b",
        "hf_repo": "google/gemma-3-12b-it", "status": "ready", "max_context": 8192,
        "param_b": 12, "param_active_b": None,
        "capabilities": ["general", "dense", "vllm", "llamacpp", "vision"],
        "engines": ["vllm", "llamacpp"], "pipeline_tag": "text-generation",
        "local": {"present": True, "size_human": "8.1 GB", "size_bytes": 8700000000},
        "shelf": {"present": True, "size_human": "8.2 GB", "size_bytes": 8800000000},
        "best_bench_tok_s": 96.0, "release_date": "2025-08-12",
        "spark_verify": {"spark_status": "works", "removal_pending": False},
        "inference_profiles": [
            {"id": "gemma3-12b-gguf", "name": "Q5 GGUF", "lifecycle": "production", "tier": "fast", "tok_s": 96.0},
        ],
    },
]

doc = {
    "shelf_mounted": True,
    "generated_at": "2026-06-26T01:45:00Z",
    "models": models,
}

out = os.path.join(PORTAL, "models.json")
with open(out, "w") as f:
    json.dump(doc, f)
print("wrote", out, "with", len(models), "models")

host = os.path.join(PORTAL, "_test_host.html")
with open(host, "w") as f:
    f.write("""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;height:100%;background:#0f1117}
iframe{border:0;width:100%;height:100vh;display:block}</style></head>
<body><iframe id="f" src="/models.html?highlight=unsloth/qwen3.6-27b"></iframe></body></html>
""")
print("wrote", host)
