#!/usr/bin/env python3
"""Patch spark-inference-gateway to normalize Qwen system messages."""
from pathlib import Path

path = Path("/opt/spark/scripts/spark-inference-gateway.py")
text = path.read_text()

helper = '''

QWEN_ENGINE_MARKERS = ("eugr", "vllm", "ds4")


def _message_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and part.get("text"):
                    parts.append(str(part["text"]).strip())
                elif part.get("text"):
                    parts.append(str(part["text"]).strip())
        return "\\n".join(p for p in parts if p)
    return str(content).strip()


def _needs_qwen_message_normalization(engine: str | None, model: str | None) -> bool:
    engine_s = (engine or "").lower()
    model_s = (model or "").lower()
    if engine_s in QWEN_ENGINE_MARKERS:
        return True
    return "qwen" in model_s


def _normalize_qwen_messages(messages: list[Any]) -> list[Any]:
    """Qwen chat templates require a single leading system message."""
    if not isinstance(messages, list) or not messages:
        return messages

    leading_system: list[str] = []
    normalized: list[Any] = []

    for msg in messages:
        if not isinstance(msg, dict):
            normalized.append(msg)
            continue
        role = str(msg.get("role") or "")
        if role in ("system", "developer"):
            content = _message_text(msg.get("content"))
            if not content:
                continue
            if normalized:
                # Mid-conversation system (plugins, task injectors) -> user wrapper.
                normalized.append(
                    {
                        "role": "user",
                        "content": f"[System instruction]\\n{content}",
                    }
                )
            else:
                leading_system.append(content)
            continue
        normalized.append(msg)

    if leading_system:
        normalized.insert(
            0,
            {"role": "system", "content": "\\n\\n".join(leading_system)},
        )
    return normalized


def _normalize_chat_payload(payload: dict[str, Any], engine: str | None) -> dict[str, Any]:
    if not _needs_qwen_message_normalization(engine, str(payload.get("model") or "")):
        return payload
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return payload
    payload = dict(payload)
    payload["messages"] = _normalize_qwen_messages(messages)
    return payload

'''

if "def _normalize_qwen_messages" not in text:
    text = text.replace(
        "THINKING_DISABLED_ENGINES = {\"ds4\"}\n\n\nclass Handler",
        "THINKING_DISABLED_ENGINES = {\"ds4\"}\n" + helper + "\n\nclass Handler",
        1,
    )

old_block = """                    if served and orig_model:
                        payload["model"] = served
                        body = json.dumps(payload).encode()

                    body = self._inject_ds4_defaults(body, engine)

            except (json.JSONDecodeError, TypeError, ValueError):
                pass"""

new_block = """                    if served and orig_model:
                        payload["model"] = served

                    payload = _normalize_chat_payload(payload, engine)
                    body = json.dumps(payload).encode()
                    body = self._inject_ds4_defaults(body, engine)

            except (json.JSONDecodeError, TypeError, ValueError):
                pass"""

if "_normalize_chat_payload(payload, engine)" not in text:
    if old_block not in text:
        raise SystemExit("chat payload block not found")
    text = text.replace(old_block, new_block, 1)

path.write_text(text)
print("patched spark-inference-gateway.py")
