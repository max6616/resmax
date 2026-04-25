#!/usr/bin/env python3
import datetime as dt
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / ".codex" / "response-summary-log.md"
MISSING_PROMPT = "(user prompt not captured)"

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)(\s*[:=]\s*)([^\s,;`]+)"),
)


def load_event() -> dict[str, Any]:
    raw_input = sys.stdin.read()
    if not raw_input.strip():
        return {}
    try:
        parsed = json.loads(raw_input)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 3:
            redacted = pattern.sub(r"\1\2[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def latest_user_prompt(transcript_path: Any) -> str:
    if not isinstance(transcript_path, str) or not transcript_path:
        return MISSING_PROMPT

    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return MISSING_PROMPT

    latest_prompt = ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return MISSING_PROMPT

    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue

        if payload.get("type") == "user_message":
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                latest_prompt = message
            continue

        if payload.get("type") == "message" and payload.get("role") == "user":
            text = text_from_content(payload.get("content"))
            if text.strip():
                latest_prompt = text

    return latest_prompt or MISSING_PROMPT


def fenced_text(text: str) -> str:
    fence_length = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, fence_length + 1)
    return f"{fence}text\n{text}\n{fence}"


def append_log(event: dict[str, Any], prompt: str, message: str) -> None:
    if should_skip_message(message):
        return

    timestamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    session_id = str(event.get("session_id") or "unknown")
    turn_id = str(event.get("turn_id") or "unknown")
    cwd = str(event.get("cwd") or ROOT)
    model = str(event.get("model") or "unknown")
    transcript_path = event.get("transcript_path")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(f"## {timestamp}\n")
        log_file.write(f"- event: `Stop`\n")
        log_file.write(f"- session: `{session_id}`\n")
        log_file.write(f"- turn: `{turn_id}`\n")
        log_file.write(f"- model: `{model}`\n")
        log_file.write(f"- cwd: `{cwd}`\n")
        if isinstance(transcript_path, str) and transcript_path:
            log_file.write(f"- transcript: `{transcript_path}`\n")
        log_file.write(f"- prompt_chars: `{len(prompt)}`\n")
        log_file.write(f"- response_chars: `{len(message)}`\n\n")
        log_file.write("User Prompt:\n")
        log_file.write(f"{fenced_text(redact(prompt))}\n\n")
        log_file.write("Assistant Response:\n")
        log_file.write(f"{fenced_text(redact(message))}\n\n")


def should_skip_message(message: str) -> bool:
    stripped = message.strip()
    if not stripped:
        return True
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and set(parsed.keys()) == {"title"}


def main() -> int:
    event = load_event()
    message = event.get("last_assistant_message")
    transcript_path = event.get("transcript_path")
    prompt = latest_user_prompt(transcript_path)
    append_log(event, prompt, message if isinstance(message, str) else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
