"""Validate the S2c.2b-1 quality/statistical method contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model_selection.quality_statistics import (  # noqa: E402
    QualityStatisticsError,
    read_contract,
    validate_contract,
    validate_repository,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    contract = commands.add_parser("contract")
    contract.add_argument("path", type=Path)
    repository = commands.add_parser("repository")
    repository.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    try:
        if args.command == "contract":
            validate_contract(read_contract(args.path))
            result = {"contract": "valid"}
        else:
            result = {"checked": validate_repository(args.repo)}
    except QualityStatisticsError as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
