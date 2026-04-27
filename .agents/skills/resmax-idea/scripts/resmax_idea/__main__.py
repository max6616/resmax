from __future__ import annotations

import sys

from . import experiment_plan, generate_candidates, negative_memory, validate


COMMANDS = {
    "compile-experiment-plan": experiment_plan.main,
    "generate": generate_candidates.main,
    "validate": validate.main,
    "write-negative-memory": negative_memory.main,
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
    print(f"usage: python3 -m resmax_idea <command> [options]\ncommands: {commands}")


if __name__ == "__main__":
    raise SystemExit(main())
