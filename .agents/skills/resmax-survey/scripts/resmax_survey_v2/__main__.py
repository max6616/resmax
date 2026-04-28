from __future__ import annotations

import sys

from . import (
    assign_paper_roles,
    build_pack,
    build_roi_lens,
    compile_spec,
    compile_tension,
    extract_evidence,
    extract_reviewer_pressure,
    materialize_sources,
    plan_queries,
    record_source_replenishment,
    retrieve_macro,
    select_subdirection,
    validate,
    validate_pack,
    validate_roi_pack,
)


COMMANDS = {
    "compile-spec": compile_spec.main,
    "plan-queries": plan_queries.main,
    "retrieve-macro": retrieve_macro.main,
    "select-subdirection": select_subdirection.main,
    "materialize-sources": materialize_sources.main,
    "record-source-replenishment": record_source_replenishment.main,
    "extract-evidence": extract_evidence.main,
    "compile-tension": compile_tension.main,
    "build-pack": build_pack.main,
    "validate-pack": validate_pack.main,
    "extract-reviewer-pressure": extract_reviewer_pressure.main,
    "assign-paper-roles": assign_paper_roles.main,
    "build-roi-lens": build_roi_lens.main,
    "validate-roi-pack": validate_roi_pack.main,
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
    print(f"usage: python3 -m resmax_survey_v2 <command> [options]\ncommands: {commands}")


if __name__ == "__main__":
    raise SystemExit(main())
