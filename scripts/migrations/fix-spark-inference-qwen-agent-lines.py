#!/usr/bin/env python3
from pathlib import Path
import py_compile

path = Path("/opt/spark/scripts/spark-inference.py")
text = path.read_text()

fixed_fn = '''def eugr_qwen_agent_lines(model_dir: Path) -> str:
    if not is_qwen36_family(model_dir):
        return ""
    return (
        "    --enable-auto-tool-choice \\\\\\n"
        "    --tool-call-parser qwen3_xml \\\\\\n"
    )
'''

start = text.find("def eugr_qwen_agent_lines")
end = text.find("\n\n", start)
if start == -1:
    raise SystemExit("eugr_qwen_agent_lines not found")
# find end at next blank line after function
end = text.find("\n\ndef ", start)
if end == -1:
    raise SystemExit("function end not found")
text = text[:start] + fixed_fn + text[end + 1:]

# ensure agent_line in command template
if "{agent_line}" not in text.split("def write_eugr_service")[1].split("def discover_dflash")[0]:
    text = text.replace(
        "    --trust-remote-code \\\\n"
        "    --kv-cache-dtype auto \\\\n"
        "{attn_line}{lmo_line}{moe_line}",
        "    --trust-remote-code \\\\n"
        "{agent_line}    --kv-cache-dtype auto \\\\n"
        "{attn_line}{lmo_line}{moe_line}",
        1,
    )

path.write_text(text)
py_compile.compile(str(path), doraise=True)
print("repaired", path)
