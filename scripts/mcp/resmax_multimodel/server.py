#!/usr/bin/env python3
"""Project-local MCP server for multimodel review tools."""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any

import requests


SERVER_NAME = "resmax-multimodel"
SERVER_VERSION = "0.1.0"
DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class McpError(Exception):
    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def read_message() -> dict[str, Any] | None:
    first = sys.stdin.buffer.readline()
    if not first:
        return None

    if first.lstrip().startswith(b"{"):
        return json.loads(first.decode("utf-8"))

    headers: dict[str, str] = {}
    line = first
    while line not in (b"\r\n", b"\n", b""):
        key, _, value = line.decode("ascii").partition(":")
        headers[key.lower()] = value.strip()
        line = sys.stdin.buffer.readline()

    if not line:
        return None

    content_length = headers.get("content-length")
    if not content_length:
        raise McpError(-32700, "Missing Content-Length header")

    body = sys.stdin.buffer.read(int(content_length))
    return json.loads(body.decode("utf-8"))


def write_message(message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id: Any, error: McpError) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": error.code, "message": error.message}
    if error.data is not None:
        payload["data"] = error.data
    return {"jsonrpc": "2.0", "id": request_id, "error": payload}


def tool_text(payload: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ],
        "isError": is_error,
    }


def deepseek_tool_schema() -> dict[str, Any]:
    return {
        "name": "deepseek_review",
        "description": (
            "Review an idea, design, or implementation using DeepSeek V4 Pro "
            "through the official DeepSeek API with thinking mode enabled."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The review question or task for DeepSeek.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional project or code context to review.",
                },
                "rubric": {
                    "type": "string",
                    "description": "Optional review criteria or expected output format.",
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional system instruction for the review model.",
                },
                "reasoning_effort": {
                    "type": "string",
                    "enum": ["high", "max"],
                    "default": "high",
                    "description": "DeepSeek thinking effort.",
                },
                "max_tokens": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20000,
                    "default": 4096,
                    "description": "Maximum output tokens for the DeepSeek response.",
                },
                "include_reasoning_content": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include raw DeepSeek reasoning_content in the tool output.",
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    }


def build_user_prompt(args: dict[str, Any]) -> str:
    parts: list[str] = []
    context = str(args.get("context") or "").strip()
    rubric = str(args.get("rubric") or "").strip()
    prompt = str(args.get("prompt") or "").strip()

    if context:
        parts.append(f"# Context\n{context}")
    if rubric:
        parts.append(f"# Review Rubric\n{rubric}")
    parts.append(f"# Task\n{prompt}")
    return "\n\n".join(parts)


def call_deepseek_review(args: dict[str, Any]) -> dict[str, Any]:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise McpError(-32602, "Missing required argument: prompt")

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise McpError(
            -32001,
            "DEEPSEEK_API_KEY is not set. Populate .secrets/deepseek.env or the Codex environment.",
        )

    reasoning_effort = str(args.get("reasoning_effort") or "high")
    if reasoning_effort not in {"high", "max"}:
        raise McpError(-32602, "reasoning_effort must be 'high' or 'max'")

    try:
        max_tokens = int(args.get("max_tokens") or 4096)
    except (TypeError, ValueError) as exc:
        raise McpError(-32602, "max_tokens must be an integer") from exc
    max_tokens = max(1, min(max_tokens, 20000))

    base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")
    endpoint = f"{base_url}/chat/completions"
    system_prompt = str(args.get("system_prompt") or "").strip() or (
        "You are a rigorous technical reviewer. Be concise, concrete, and critical. "
        "Prioritize correctness, architecture risks, missing evidence, and better alternatives."
    )

    request_body = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_prompt(args)},
        ],
        "thinking": {"type": "enabled"},
        "reasoning_effort": reasoning_effort,
        "max_tokens": max_tokens,
        "stream": False,
    }

    try:
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=(15, 180),
        )
    except requests.RequestException as exc:
        raise McpError(-32002, f"DeepSeek request failed: {exc}") from exc

    if response.status_code >= 400:
        text = response.text[:1200]
        raise McpError(
            -32003,
            f"DeepSeek API returned HTTP {response.status_code}",
            {"body": text},
        )

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise McpError(-32004, "DeepSeek response contained no choices", data)

    message = choices[0].get("message") or {}
    reasoning_content = message.get("reasoning_content") or ""
    include_reasoning = bool(args.get("include_reasoning_content") or False)

    output: dict[str, Any] = {
        "model": data.get("model") or DEEPSEEK_MODEL,
        "requested_model": DEEPSEEK_MODEL,
        "thinking": {"type": "enabled", "reasoning_effort": reasoning_effort},
        "content": message.get("content") or "",
        "finish_reason": choices[0].get("finish_reason"),
        "reasoning_present": bool(reasoning_content),
        "reasoning_chars": len(reasoning_content),
        "usage": data.get("usage"),
    }

    if include_reasoning:
        output["reasoning_content"] = reasoning_content

    return tool_text(output)


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method and request_id is None:
        return None

    if method == "initialize":
        protocol_version = params.get("protocolVersion") or "2025-06-18"
        return result_response(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )

    if method == "ping":
        return result_response(request_id, {})

    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None

    if method == "tools/list":
        return result_response(request_id, {"tools": [deepseek_tool_schema()]})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name != "deepseek_review":
            raise McpError(-32601, f"Unknown tool: {name}")
        return result_response(request_id, call_deepseek_review(arguments))

    if method in {"resources/list", "prompts/list"}:
        key = "resources" if method == "resources/list" else "prompts"
        return result_response(request_id, {key: []})

    raise McpError(-32601, f"Method not found: {method}")


def main() -> int:
    while True:
        request_id: Any | None = None
        try:
            message = read_message()
            if message is None:
                return 0
            request_id = message.get("id")
            response = handle_request(message)
            if response is not None:
                write_message(response)
        except McpError as exc:
            write_message(error_response(request_id, exc))
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            write_message(error_response(request_id, McpError(-32603, str(exc))))


if __name__ == "__main__":
    raise SystemExit(main())
