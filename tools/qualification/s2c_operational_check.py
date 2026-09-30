"""Check canonical S2c b-2 method, evidence, joint versions and M2 decisions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_selection import operational, s2c_artifacts  # noqa: E402
from model_selection.canonical import read  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("repository", "contract", "projection"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    try:
        if args.command == "repository":
            result = {"checked": s2c_artifacts.validate_repository(args.repo)}
        else:
            contract = read(args.repo / operational.CONTRACT)
            operational.validate_contract(contract)
            if args.command == "projection":
                print(operational.render_contract_projection(contract))
                return 0
            result = {"contract": "valid"}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"refused": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
