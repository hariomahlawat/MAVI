"""Check External Evidence Ledgers and decision summaries (MSR method v1 revision M1).

Usage:
    python tools/qualification/model_selection_check.py ledger <ledger.json>
    python tools/qualification/model_selection_check.py decision <decision.json> --ledger <ledger.json>
    python tools/qualification/model_selection_check.py repository [--repo <path>]

Prints the recomputed classification as JSON and exits 0, or prints the refusal code
and exits 1. See docs/qualification/model-selection/candidate-credibility.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model_selection.credibility import (  # noqa: E402
    CredibilityError,
    read_json,
    validate_decision,
    validate_ledger,
    validate_repository,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    ledger = commands.add_parser("ledger")
    ledger.add_argument("path", type=Path)
    decision = commands.add_parser("decision")
    decision.add_argument("path", type=Path)
    decision.add_argument("--ledger", type=Path, required=True)
    repository = commands.add_parser("repository")
    repository.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "ledger":
            result: object = validate_ledger(read_json(arguments.path))
        elif arguments.command == "decision":
            validate_decision(read_json(arguments.path), read_json(arguments.ledger))
            result = {"decision": "valid"}
        else:
            result = {"checked": validate_repository(arguments.repo)}
    except CredibilityError as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
