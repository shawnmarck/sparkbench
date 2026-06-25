#!/usr/bin/env python3
"""Add --language-model-only to eugr scaffold when config.json says language_model_only."""
from __future__ import annotations

import sys
from pathlib import Path

SPARK_INFERENCE = Path("/opt/spark/scripts/spark-inference.py")

HELPER = '''
def is_language_model_only(model_dir: Path) -> bool:
    cfg_path = model_dir / "config.json"
    if not cfg_path.is_file():
        return False
    try:
        cfg = json.loads(cfg_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return cfg.get("language_model_only") is True


def eugr_language_model_only_line(model_dir: Path) -> str:
    if is_language_model_only(model_dir):
        return "    --language-model-only \\\\n"
    return ""


'''


def patch(text: str) -> str:
    if "def is_language_model_only" not in text:
        text = text.replace(
            "def is_multimodal_model(model_dir: Path) -> bool:",
            HELPER + "def is_multimodal_model(model_dir: Path) -> bool:",
        )

    replacements = [
        (
            "    load_fmt = eugr_load_format(model_dir, weight_format)\n"
            "    env_block = eugr_nvfp4_env_yaml() if weight_format == \"nvfp4\" else \"\"\n"
            "    max_len = infer_max_model_len(model_dir, weight_format)\n"
            "    path = SERVICES_DIR / f\"eugr-{profile_id}.yaml\"",
            "    load_fmt = eugr_load_format(model_dir, weight_format)\n"
            "    lmo_line = eugr_language_model_only_line(model_dir)\n"
            "    env_block = eugr_nvfp4_env_yaml() if weight_format == \"nvfp4\" else \"\"\n"
            "    max_len = infer_max_model_len(model_dir, weight_format)\n"
            "    path = SERVICES_DIR / f\"eugr-{profile_id}.yaml\"",
        ),
        (
            "{attn_line}{moe_line}    --gpu-memory-utilization {{gpu_memory_utilization}} \\\n"
            "    --max-model-len {{max_model_len}} \\\n"
            "    --max-num-seqs {{max_num_seqs}} \\\n"
            "    --max-num-batched-tokens {{max_num_batched_tokens}} \\\n"
            "    --enable-chunked-prefill \\\n"
            "    --enable-prefix-caching \\\n"
            "    --load-format {load_fmt}\n"
            "\"\"\"",
            "{attn_line}{lmo_line}{moe_line}    --gpu-memory-utilization {{gpu_memory_utilization}} \\\n"
            "    --max-model-len {{max_model_len}} \\\n"
            "    --max-num-seqs {{max_num_seqs}} \\\n"
            "    --max-num-batched-tokens {{max_num_batched_tokens}} \\\n"
            "    --enable-chunked-prefill \\\n"
            "    --enable-prefix-caching \\\n"
            "    --load-format {load_fmt}\n"
            "\"\"\"",
        ),
        (
            "    load_fmt = eugr_load_format(model_dir, weight_format)\n"
            "    env_block = eugr_nvfp4_env_yaml() if weight_format == \"nvfp4\" else \"\"\n"
            "    max_len = infer_max_model_len(model_dir, weight_format)\n"
            "    moe_backend = \"triton\" if is_moe_model(model_dir) else \"triton\"",
            "    load_fmt = eugr_load_format(model_dir, weight_format)\n"
            "    lmo_line = eugr_language_model_only_line(model_dir)\n"
            "    env_block = eugr_nvfp4_env_yaml() if weight_format == \"nvfp4\" else \"\"\n"
            "    max_len = infer_max_model_len(model_dir, weight_format)\n"
            "    moe_backend = \"triton\" if is_moe_model(model_dir) else \"triton\"",
        ),
        (
            "{attn_line}{moe_line}    --gpu-memory-utilization {{gpu_memory_utilization}} \\\n"
            "    --max-model-len {{max_model_len}} \\\n"
            "    --max-num-seqs {{max_num_seqs}} \\\n"
            "    --max-num-batched-tokens {{max_num_batched_tokens}} \\\n"
            "    --enable-chunked-prefill \\\n"
            "    --enable-prefix-caching \\\n"
            "    --load-format {load_fmt} \\\n"
            "    --speculative-config '{spec_json}'",
            "{attn_line}{lmo_line}{moe_line}    --gpu-memory-utilization {{gpu_memory_utilization}} \\\n"
            "    --max-model-len {{max_model_len}} \\\n"
            "    --max-num-seqs {{max_num_seqs}} \\\n"
            "    --max-num-batched-tokens {{max_num_batched_tokens}} \\\n"
            "    --enable-chunked-prefill \\\n"
            "    --enable-prefix-caching \\\n"
            "    --load-format {load_fmt} \\\n"
            "    --speculative-config '{spec_json}'",
        ),
        (
            "    for key in (\"max_position_embeddings\", \"max_seq_len\", \"seq_length\"):\n"
            "        val = cfg.get(key)\n"
            "        if isinstance(val, (int, float)) and val > 0:\n"
            "            return int(val)\n"
            "    rope = cfg.get(\"rope_scaling\") or {}",
            "    for key in (\"max_position_embeddings\", \"max_seq_len\", \"seq_length\"):\n"
            "        val = cfg.get(key)\n"
            "        if isinstance(val, (int, float)) and val > 0:\n"
            "            return int(val)\n"
            "    text_cfg = cfg.get(\"text_config\")\n"
            "    if isinstance(text_cfg, dict):\n"
            "        val = text_cfg.get(\"max_position_embeddings\")\n"
            "        if isinstance(val, (int, float)) and val > 0:\n"
            "            return int(val)\n"
            "    rope = cfg.get(\"rope_scaling\") or {}",
        ),
    ]
    for old, new in replacements:
        if old in text and new not in text:
            text = text.replace(old, new, 1)
    return text


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SPARK_INFERENCE
    text = path.read_text()
    updated = patch(text)
    if updated == text:
        print("already patched:", path)
        return 0
    path.write_text(updated)
    print("patched:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
