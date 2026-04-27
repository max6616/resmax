from __future__ import annotations

import sys

from . import aggregate_blockers, build_evidence_package, run_reviewers, validate


COMMANDS = {
    "build-packages": build_evidence_package.main,
    "run-reviewers": run_reviewers.main,
    "aggregate": aggregate_blockers.main,
    "validate": validate.main,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        _print_help()
        return 0
    command = args.pop(0)
    handler = COMMANDS.get(command)
    if handler is None:
        print(f"ERROR unknown command: {command}", file=sys.stderr)
        _print_help()
        return 2
    return handler(args)


def _print_help() -> None:
    commands = ", ".join(sorted(COMMANDS))
    print(f"usage: python3 -m resmax_review <command> [options]\ncommands: {commands}")


if __name__ == "__main__":
    raise SystemExit(main())
