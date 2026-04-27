from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from resmax_core.ids import input_hash, make_state_id
from resmax_core.state import SCHEMA_VERSION, utc_now

from . import PRODUCER, REPO_ROOT, REVIEWER_ROLES
from .build_evidence_package import build_evidence_packages, read_json, sha256_file, sha256_text, write_json
from .reviewer_prompts import build_prompt, build_prompt_hash


DEEPSEEK_TOOL = "deepseek_review"
DEFAULT_GENERATOR_MODEL = "resmax_idea"


class McpStdioClient:
    def __init__(self, runner: Path) -> None:
        self.runner = runner
        self.proc: subprocess.Popen[bytes] | None = None
        self.next_id = 1

    def __enter__(self) -> "McpStdioClient":
        self.proc = subprocess.Popen(
            ["bash", str(self.runner)],
            cwd=str(REPO_ROOT),
            env=os.environ.copy(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "resmax-review-runner", "version": SCHEMA_VERSION},
            },
        )
        self.notify("notifications/initialized")
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        finally:
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("MCP client is not running")
        request_id = self.next_id
        self.next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self.proc.stdin.write(_encode_message(payload))
        self.proc.stdin.flush()
        response = self._read_message()
        if "error" in response:
            raise RuntimeError(json.dumps(response["error"], ensure_ascii=False))
        return response.get("result", {})

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("MCP client is not running")
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self.proc.stdin.write(_encode_message(payload))
        self.proc.stdin.flush()

    def _read_message(self) -> dict[str, Any]:
        if not self.proc or not self.proc.stdout:
            raise RuntimeError("MCP client stdout is closed")
        headers: dict[str, str] = {}
        while True:
            line = self.proc.stdout.readline()
            if line in (b"\r\n", b"\n"):
                break
            if not line:
                stderr = self.proc.stderr.read().decode("utf-8", errors="replace") if self.proc.stderr else ""
                raise RuntimeError(f"MCP server exited before response. stderr={stderr}")
            key, _, value = line.decode("ascii").partition(":")
            headers[key.lower()] = value.strip()
        body = self.proc.stdout.read(int(headers["content-length"]))
        return json.loads(body.decode("utf-8"))


def run_reviewers(
    *,
    ideas: Path,
    out: Path,
    pack: Path | None = None,
    provider: str = "mcp-deepseek",
    roles: tuple[str, ...] = REVIEWER_ROLES,
    generator_model: str = DEFAULT_GENERATOR_MODEL,
    overwrite: bool = False,
    max_tokens: int = 4096,
    retries: int = 1,
    max_ideas: int = 1,
    all_ideas: bool = False,
    concurrency: int = 5,
    allow_same_model_review: bool = False,
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    build_evidence_packages(ideas=ideas, out=out, pack=pack, max_ideas=max_ideas, all_ideas=all_ideas)
    packages = sorted((out / "evidence_packages").glob("*.json"))
    written: list[Path] = []
    skipped = 0
    tasks: list[dict[str, Any]] = []
    total = len(packages) * len(roles)
    current = 0
    for package_path in packages:
        evidence_package = read_json(package_path)
        for role in roles:
            current += 1
            target = out / "raw" / role / f"{evidence_package['idea_id']}.json"
            if target.exists() and not overwrite:
                skipped += 1
                print(
                    f"[review] skip {current}/{total} idea_id={evidence_package['idea_id']} role={role}",
                    flush=True,
                )
                continue
            tasks.append(
                {
                    "index": current,
                    "total": total,
                    "role": role,
                    "target": target,
                    "evidence_package": evidence_package,
                    "package_path": package_path,
                }
            )
    if tasks:
        max_workers = max(1, min(int(concurrency or 1), len(tasks)))
        print(f"[review] dispatch tasks={len(tasks)} concurrency={max_workers} provider={provider}", flush=True)
        if max_workers == 1:
            for task in tasks:
                written.append(
                    _run_review_task(
                        provider=provider,
                        max_tokens=max_tokens,
                        generator_model=generator_model,
                        retries=retries,
                        allow_same_model_review=allow_same_model_review,
                        task=task,
                    )
                )
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(
                        _run_review_task,
                        provider=provider,
                        max_tokens=max_tokens,
                        generator_model=generator_model,
                        retries=retries,
                        allow_same_model_review=allow_same_model_review,
                        task=task,
                    )
                    for task in tasks
                ]
                for future in as_completed(futures):
                    written.append(future.result())
    return {"out": str(out), "written": len(written), "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run external reviewers and write raw ReviewTrace JSON.")
    parser.add_argument("--ideas", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pack", type=Path, default=None)
    parser.add_argument("--provider", choices=["mcp-deepseek", "stub"], default="mcp-deepseek")
    parser.add_argument("--roles", default=",".join(REVIEWER_ROLES))
    parser.add_argument("--generator-model", default=DEFAULT_GENERATOR_MODEL)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--max-ideas", type=int, default=1)
    parser.add_argument("--all-ideas", action="store_true")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--allow-same-model-review", action="store_true")
    args = parser.parse_args(argv)
    roles = tuple(role.strip() for role in args.roles.split(",") if role.strip())
    unsupported = [role for role in roles if role not in REVIEWER_ROLES]
    if unsupported:
        print(f"ERROR unsupported reviewer roles: {', '.join(unsupported)}", file=sys.stderr)
        return 2
    result = run_reviewers(
        ideas=args.ideas,
        out=args.out,
        pack=args.pack,
        provider=args.provider,
        roles=roles,
        generator_model=args.generator_model,
        overwrite=args.overwrite,
        max_tokens=args.max_tokens,
        retries=args.retries,
        max_ideas=args.max_ideas,
        all_ideas=args.all_ideas,
        concurrency=args.concurrency,
        allow_same_model_review=args.allow_same_model_review,
    )
    print(f"[review] ran reviewers provider={args.provider} written={result['written']} skipped={result['skipped']} out={args.out}")
    return 0


def _provider(provider: str, *, max_tokens: int):
    if provider == "stub":
        return StubReviewerProvider(max_tokens=max_tokens)
    if provider == "mcp-deepseek":
        return DeepSeekMcpReviewerProvider(max_tokens=max_tokens)
    raise ValueError(f"unsupported provider: {provider}")


class StubReviewerProvider:
    def __init__(self, *, max_tokens: int) -> None:
        self.max_tokens = max_tokens

    def __enter__(self) -> "StubReviewerProvider":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def review(self, role: str, prompt: str, evidence_package: dict[str, Any]) -> dict[str, Any]:
        evidence_ids = [card.get("state_id", "") for card in evidence_package.get("evidence_cards", []) if card.get("state_id")]
        ready = evidence_package.get("idea_card", {}).get("status") == "phase6_ready"
        payload = {
            "recommended_status": "promote" if ready else "revise",
            "blockers": []
            if ready
            else [
                {
                    "blocker_type": "insufficient_evidence",
                    "severity": "major",
                    "evidence_status": "supported" if evidence_ids else "unknown",
                    "evidence_ids": evidence_ids[:1],
                    "explanation": "Stub reviewer routes non-ready ideas to revision.",
                }
            ],
            "scores": {"novelty": 3, "feasibility": 3, "evidence_confidence": 2, "review_risk": 3},
            "rationale": f"Deterministic stub review for {role}.",
        }
        return {"model": "stub-reviewer", "content": json.dumps(payload, ensure_ascii=False), "usage": {}}


class DeepSeekMcpReviewerProvider:
    def __init__(self, *, max_tokens: int) -> None:
        self.max_tokens = max_tokens
        self.client: McpStdioClient | None = None

    def __enter__(self) -> "DeepSeekMcpReviewerProvider":
        self.client = McpStdioClient(REPO_ROOT / "scripts" / "mcp" / "resmax_multimodel" / "run_server.sh")
        self.client.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.client:
            self.client.__exit__(exc_type, exc, tb)

    def review(self, role: str, prompt: str, evidence_package: dict[str, Any]) -> dict[str, Any]:
        if not self.client:
            raise RuntimeError("DeepSeek MCP provider is not running")
        result = self.client.request(
            "tools/call",
            {
                "name": DEEPSEEK_TOOL,
                "arguments": {
                    "prompt": prompt,
                    "rubric": _review_json_rubric(),
                    "system_prompt": _review_system_prompt(role),
                    "reasoning_effort": "high",
                    "max_tokens": self.max_tokens,
                    "include_reasoning_content": False,
                },
            },
        )
        tool_text = result["content"][0]["text"]
        payload = json.loads(tool_text)
        return {
            "model": payload.get("model") or payload.get("requested_model") or "deepseek-v4-pro",
            "content": payload.get("content") or "",
            "usage": payload.get("usage") or {},
        }


def _run_review_task(
    *,
    provider: str,
    max_tokens: int,
    generator_model: str,
    retries: int,
    allow_same_model_review: bool,
    task: dict[str, Any],
) -> Path:
    role = task["role"]
    evidence_package = task["evidence_package"]
    print(
        "[review] call "
        f"{task['index']}/{task['total']} idea_id={evidence_package['idea_id']} role={role} provider={provider}",
        flush=True,
    )
    with _provider(provider, max_tokens=max_tokens) as caller:
        trace = _review_one_with_retries(
            provider=provider,
            caller=caller,
            role=role,
            evidence_package=evidence_package,
            evidence_package_path=task["package_path"],
            generator_model=generator_model,
            retries=retries,
            allow_same_model_review=allow_same_model_review,
        )
    write_json(task["target"], trace)
    print(
        "[review] wrote "
        f"{task['index']}/{task['total']} idea_id={evidence_package['idea_id']} role={role} "
        f"status={trace['recommended_status']}",
        flush=True,
    )
    return task["target"]


def _review_one(
    *,
    provider: str,
    caller: Any,
    role: str,
    evidence_package: dict[str, Any],
    evidence_package_path: Path,
    generator_model: str,
    allow_same_model_review: bool = False,
) -> dict[str, Any]:
    prompt = build_prompt(role, evidence_package)
    prompt_hash = build_prompt_hash(role, evidence_package)
    response = caller.review(role, prompt, evidence_package)
    raw_response = str(response.get("content") or "").strip()
    if not raw_response:
        raise RuntimeError("empty reviewer response")
    parsed = _parse_review_response(raw_response)
    reviewer_model = str(response.get("model") or provider)
    if reviewer_model == generator_model and not allow_same_model_review:
        return _same_model_not_allowed_trace(
            provider=provider,
            role=role,
            evidence_package=evidence_package,
            evidence_package_path=evidence_package_path,
            generator_model=generator_model,
            reviewer_model=reviewer_model,
            prompt=prompt,
            prompt_hash=prompt_hash,
            raw_response=raw_response,
        )
    blockers = _normalize_blockers(parsed.get("blockers"), evidence_package)
    recommended_status = _normalize_status(parsed.get("recommended_status"))
    scores = _normalize_scores(parsed.get("scores"))
    trace_input = {
        "idea_id": evidence_package["idea_id"],
        "reviewer_role": role,
        "prompt_hash": prompt_hash,
        "raw_response_hash": sha256_text(raw_response),
        "reviewer_model": reviewer_model,
    }
    independence = "low" if reviewer_model == generator_model else "high"
    trace = {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("review_trace", trace_input),
        "created_at": utc_now(),
        "input_hash": input_hash(trace_input),
        "parent_state_ids": [evidence_package.get("package_id", "")],
        "producer": PRODUCER,
        "review_id": make_state_id("review", trace_input),
        "review_trace_id": make_state_id("review_trace", trace_input),
        "idea_id": evidence_package["idea_id"],
        "idea_card_id": evidence_package.get("idea_card", {}).get("state_id", ""),
        "reviewer_role": role,
        "reviewer_model": reviewer_model,
        "generator_model": generator_model,
        "review_independence_confidence": independence,
        "prompt": prompt,
        "prompt_hash": prompt_hash,
        "evidence_package_hash": sha256_file(evidence_package_path),
        "raw_response": raw_response,
        "raw_review": raw_response,
        "blockers": blockers,
        "scores": scores,
        "recommended_status": recommended_status,
        "decision_status": "pending",
    }
    if independence == "low":
        trace["fallback_reason"] = "same model used for generation and review"
    return trace


def _review_one_with_retries(
    *,
    provider: str,
    caller: Any,
    role: str,
    evidence_package: dict[str, Any],
    evidence_package_path: Path,
    generator_model: str,
    retries: int,
    allow_same_model_review: bool = False,
) -> dict[str, Any]:
    attempts = max(0, retries) + 1
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            return _review_one(
                provider=provider,
                caller=caller,
                role=role,
                evidence_package=evidence_package,
                evidence_package_path=evidence_package_path,
                generator_model=generator_model,
                allow_same_model_review=allow_same_model_review,
            )
        except Exception as exc:
            last_error = str(exc)
            if attempt < attempts:
                print(
                    "[review] retry "
                    f"idea_id={evidence_package['idea_id']} role={role} attempt={attempt + 1}/{attempts} "
                    f"reason={last_error[:180]}",
                    flush=True,
                )
    return _review_error_trace(
        provider=provider,
        role=role,
        evidence_package=evidence_package,
        evidence_package_path=evidence_package_path,
        generator_model=generator_model,
        error=last_error or "unknown reviewer execution error",
        attempts=attempts,
    )


def _review_error_trace(
    *,
    provider: str,
    role: str,
    evidence_package: dict[str, Any],
    evidence_package_path: Path,
    generator_model: str,
    error: str,
    attempts: int,
) -> dict[str, Any]:
    prompt = build_prompt(role, evidence_package)
    prompt_hash = build_prompt_hash(role, evidence_package)
    raw_response = f"provider_error after {attempts} attempt(s): {error}"
    trace_input = {
        "idea_id": evidence_package["idea_id"],
        "reviewer_role": role,
        "prompt_hash": prompt_hash,
        "raw_response_hash": sha256_text(raw_response),
        "reviewer_model": provider,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("review_trace", trace_input),
        "created_at": utc_now(),
        "input_hash": input_hash(trace_input),
        "parent_state_ids": [evidence_package.get("package_id", "")],
        "producer": PRODUCER,
        "review_id": make_state_id("review", trace_input),
        "review_trace_id": make_state_id("review_trace", trace_input),
        "idea_id": evidence_package["idea_id"],
        "idea_card_id": evidence_package.get("idea_card", {}).get("state_id", ""),
        "reviewer_role": role,
        "reviewer_model": provider,
        "generator_model": generator_model,
        "review_independence_confidence": "unknown",
        "fallback_reason": "external reviewer call failed; routed to human gate",
        "prompt": prompt,
        "prompt_hash": prompt_hash,
        "evidence_package_hash": sha256_file(evidence_package_path),
        "raw_response": raw_response,
        "raw_review": raw_response,
        "blockers": [
            {
                "blocker_type": "external_reviewer_execution_failed",
                "severity": "fatal",
                "evidence_status": "not_applicable",
                "evidence_ids": [],
                "explanation": raw_response,
            }
        ],
        "scores": {"novelty": 0, "feasibility": 0, "evidence_confidence": 0, "review_risk": 5},
        "recommended_status": "human_gate",
        "decision_status": "pending",
    }


def _same_model_not_allowed_trace(
    *,
    provider: str,
    role: str,
    evidence_package: dict[str, Any],
    evidence_package_path: Path,
    generator_model: str,
    reviewer_model: str,
    prompt: str,
    prompt_hash: str,
    raw_response: str,
) -> dict[str, Any]:
    raw_review = raw_response.strip()
    trace_input = {
        "idea_id": evidence_package["idea_id"],
        "reviewer_role": role,
        "prompt_hash": prompt_hash,
        "raw_response_hash": sha256_text(raw_review),
        "reviewer_model": reviewer_model,
        "gate": "same_model_review_not_allowed",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("review_trace", trace_input),
        "created_at": utc_now(),
        "input_hash": input_hash(trace_input),
        "parent_state_ids": [evidence_package.get("package_id", "")],
        "producer": PRODUCER,
        "review_id": make_state_id("review", trace_input),
        "review_trace_id": make_state_id("review_trace", trace_input),
        "idea_id": evidence_package["idea_id"],
        "idea_card_id": evidence_package.get("idea_card", {}).get("state_id", ""),
        "reviewer_role": role,
        "reviewer_model": reviewer_model,
        "generator_model": generator_model,
        "review_independence_confidence": "low",
        "fallback_reason": "same model used for generation and review; same-model review was not explicitly allowed",
        "prompt": prompt,
        "prompt_hash": prompt_hash,
        "evidence_package_hash": sha256_file(evidence_package_path),
        "raw_response": raw_review,
        "raw_review": raw_review,
        "blockers": [
            {
                "blocker_type": "same_model_review_not_allowed",
                "severity": "fatal",
                "evidence_status": "not_applicable",
                "evidence_ids": [],
                "explanation": (
                    "Reviewer model matched the generator model. Rerun with --allow-same-model-review only after "
                    "explicit approval, or use an independent reviewer model."
                ),
            }
        ],
        "scores": {"novelty": 0, "feasibility": 0, "evidence_confidence": 0, "review_risk": 5},
        "recommended_status": "human_gate",
        "decision_status": "pending",
    }


def _parse_review_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return _invalid_payload("empty reviewer response")
    fenced = _extract_fenced_json(text)
    for candidate in (fenced, text):
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
            return value if isinstance(value, dict) else _invalid_payload("review JSON was not an object")
        except json.JSONDecodeError:
            obj = _first_json_object(candidate)
            if obj is not None:
                return obj
    return _invalid_payload("reviewer response did not contain valid JSON")


def _invalid_payload(reason: str) -> dict[str, Any]:
    return {
        "recommended_status": "human_gate",
        "blockers": [
            {
                "blocker_type": "invalid_review_format",
                "severity": "fatal",
                "evidence_status": "not_applicable",
                "evidence_ids": [],
                "explanation": reason,
            }
        ],
        "scores": {"novelty": 0, "feasibility": 0, "evidence_confidence": 0, "review_risk": 5},
    }


def _extract_fenced_json(text: str) -> str:
    marker = "```json"
    if marker not in text:
        return ""
    after = text.split(marker, 1)[1]
    return after.split("```", 1)[0].strip()


def _first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _normalize_blockers(value: Any, evidence_package: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    evidence_ids = {
        card.get("state_id", "")
        for card in evidence_package.get("evidence_cards", [])
        if card.get("state_id")
    }
    blockers: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        ids = [str(x) for x in item.get("evidence_ids", []) if str(x) in evidence_ids]
        blockers.append(
            {
                "blocker_type": str(item.get("blocker_type") or "reviewer_objection"),
                "severity": _normalize_severity(item.get("severity")),
                "evidence_status": _normalize_evidence_status(item.get("evidence_status")),
                "evidence_ids": ids,
                "explanation": str(item.get("explanation") or "Reviewer raised an objection without explanation."),
            }
        )
    return blockers


def _normalize_severity(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"fatal", "major", "minor", "none"} else "major"


def _normalize_evidence_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"supported", "unsupported", "unknown", "not_applicable"} else "unknown"


def _normalize_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "promoted": "promote",
        "promotion": "promote",
        "needs_revision": "revise",
        "revision": "revise",
        "reject": "kill",
        "killed": "kill",
        "blocked": "human_gate",
    }
    text = aliases.get(text, text)
    return text if text in {"promote", "revise", "kill", "human_gate"} else "human_gate"


def _normalize_scores(value: Any) -> dict[str, int]:
    defaults = {"novelty": 0, "feasibility": 0, "evidence_confidence": 0, "review_risk": 5}
    if not isinstance(value, dict):
        return defaults
    return {key: _score(value.get(key), default) for key, default in defaults.items()}


def _score(value: Any, default: int) -> int:
    try:
        return max(0, min(5, int(value)))
    except (TypeError, ValueError):
        return default


def _review_json_rubric() -> str:
    return (
        "Return only one JSON object with keys: recommended_status, blockers, scores, rationale. "
        "recommended_status must be one of promote, revise, kill, human_gate. "
        "blockers must be an array of objects with blocker_type, severity, evidence_status, evidence_ids, explanation. "
        "severity must be fatal, major, minor, or none. Cite evidence_ids only from the evidence package."
    )


def _review_system_prompt(role: str) -> str:
    return (
        f"You are a strict Resmax Phase 6 {role} reviewer. "
        "Use only the provided evidence package. Return compact valid JSON and no markdown."
    )


def _encode_message(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


if __name__ == "__main__":
    raise SystemExit(main())
