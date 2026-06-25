#!/usr/bin/env python3
"""Repair broken eugr_language_model_only_line after bad patch."""
from pathlib import Path

path = Path("/opt/spark/scripts/spark-inference.py")
text = path.read_text()

old_broken = '''def eugr_language_model_only_line(model_dir: Path) -> str:
    if is_language_model_only(model_dir):
        return "    --language-model-only \\
"
    return ""'''

new_fixed = '''def eugr_language_model_only_line(model_dir: Path) -> str:
    if is_language_model_only(model_dir):
        return "    --language-model-only \\\\\\n"
    return ""'''

if old_broken in text:
    text = text.replace(old_broken, new_fixed)
elif 'return "    --language-model-only \\\\' in text and "\\\\n\"" not in text.split("eugr_language_model_only_line")[1].split("def is_multimodal_model")[0]:
    # line-split repair
    lines = text.splitlines()
    out: list[str] = []
    skip_next = False
    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue
        if line.strip().startswith('return "    --language-model-only \\'):
            out.append('        return "    --language-model-only \\\\\\n"')
            if i + 1 < len(lines) and lines[i + 1].strip() == '"':
                skip_next = True
            continue
        out.append(line)
    text = "\n".join(out) + ("\n" if text.endswith("\n") else "")

path.write_text(text)
import py_compile

py_compile.compile(str(path), doraise=True)
print("repaired", path)
