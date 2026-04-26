#!/usr/bin/env python3
"""Smoke test the project-local multimodel MCP server."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
RUNNER = ROOT_DIR / "scripts" / "mcp" / "resmax_multimodel" / "run_server.sh"


def load_secret_env(env: dict[str, str]) -> None:
    env_path = ROOT_DIR / ".secrets" / "deepseek.env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip().strip("'").strip('"')
        env.setdefault(key.strip(), value)


def encode_message(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def read_message(proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    headers: dict[str, str] = {}
    while True:
        line = proc.stdout.readline() if proc.stdout else b""
        if line in (b"\r\n", b"\n"):
            break
        if not line:
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            raise RuntimeError(f"Server exited before response. stderr={stderr}")
        key, _, value = line.decode("ascii").partition(":")
        headers[key.lower()] = value.strip()
    content_length = int(headers["content-length"])
    body = proc.stdout.read(content_length) if proc.stdout else b""
    return json.loads(body.decode("utf-8"))


def send_request(
    proc: subprocess.Popen[bytes],
    request_id: int,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    proc.stdin.write(encode_message(payload))
    proc.stdin.flush()
    return read_message(proc)


def send_notification(
    proc: subprocess.Popen[bytes],
    method: str,
    params: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    proc.stdin.write(encode_message(payload))
    proc.stdin.flush()


def parse_tool_text(response: dict[str, Any]) -> dict[str, Any]:
    text = response["result"]["content"][0]["text"]
    return json.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", action="store_true", help="Call the DeepSeek API through the MCP tool.")
    parser.add_argument("--reasoning-effort", choices=["high", "max"], default="high")
    args = parser.parse_args()

    env = os.environ.copy()
    load_secret_env(env)

    proc = subprocess.Popen(
        ["bash", str(RUNNER)],
        cwd=str(ROOT_DIR),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None

    try:
        init = send_request(
            proc,
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "resmax-mcp-smoke-test", "version": "0.1.0"},
            },
        )
        send_notification(proc, "notifications/initialized")
        tools = send_request(proc, 2, "tools/list")

        summary: dict[str, Any] = {
            "initialize": init.get("result", {}),
            "tools": [tool.get("name") for tool in tools.get("result", {}).get("tools", [])],
        }

        if args.api:
            tool_response = send_request(
                proc,
                3,
                "tools/call",
                {
                    "name": "deepseek_review",
                    "arguments": {
                        "prompt": (
                            "Review this architecture decision in one concise paragraph: "
                            "use a local MCP wrapper to expose DeepSeek V4 Pro as a review "
                            "tool instead of replacing Codex's primary model."
                        ),
                        "rubric": "Focus on correctness, integration risk, and whether the boundary is clean.",
                        "reasoning_effort": args.reasoning_effort,
                        "max_tokens": 1024,
                    },
                },
            )
            payload = parse_tool_text(tool_response)
            summary["api_call"] = {
                "model": payload.get("model"),
                "thinking": payload.get("thinking"),
                "reasoning_present": payload.get("reasoning_present"),
                "reasoning_chars": payload.get("reasoning_chars"),
                "usage": payload.get("usage"),
                "content_preview": (payload.get("content") or "")[:500],
            }

        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
