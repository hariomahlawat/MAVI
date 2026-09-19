#!/usr/bin/env python3
"""Emit the tracked runtime-requirements projection for one platform variant.

`vision-runtime-component-boundary.yml` regenerates this file from
`src/vision/pyproject.toml` and requires the tracked copy to match it byte for
byte. Until now nothing could produce it: the CPU projections were tracked
already, and C5's CUDA one would have had to be hand-assembled or copied out of
an inline snippet pasted into a console on the host.

That is the same hand-typing this workstream removes everywhere else. The
projection is derived, so deriving it is the only honest way to create it, and
this tool uses the identical functions the gate uses -- a second implementation
would be a second answer to the same question.

Offline, deterministic, and it refuses to overwrite silently.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _candidate in (Path(__file__).resolve().parents[2] / "src" / "vision",):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from mavi_vision.runtime.requirements_projection import (  # noqa: E402
    RuntimeRequirementsError,
    build_runtime_requirements_projection,
    serialize_runtime_requirements_projection,
)

VISION_ROOT = Path(__file__).resolve().parents[2] / "src" / "vision"


def render(platform_variant: str, python_version: str) -> bytes:
    projection = build_runtime_requirements_projection(
        VISION_ROOT / "pyproject.toml",
        platform_variant=platform_variant,
        python_version=python_version,
    )
    return serialize_runtime_requirements_projection(projection)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-variant", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare --output against the derivation instead of writing it",
    )
    args = parser.parse_args()

    try:
        rendered = render(args.platform_variant, args.python_version)
    except RuntimeRequirementsError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2

    if args.output is None:
        sys.stdout.buffer.write(rendered)
        return 0

    if args.check:
        try:
            tracked = args.output.read_bytes()
        except OSError:
            print(
                json.dumps(
                    {"ok": False, "code": "runtime_requirement_projection_missing"},
                    sort_keys=True,
                )
            )
            return 2
        if tracked != rendered:
            print(
                json.dumps(
                    {"ok": False, "code": "runtime_requirement_projection_stale"},
                    sort_keys=True,
                )
            )
            return 2
        print(json.dumps({"ok": True, "checked": str(args.output)}, sort_keys=True))
        return 0

    if args.output.exists() and args.output.read_bytes() != rendered:
        # Never silently rewrite a tracked projection: if it differs, that is a
        # finding about the pyproject or the variant, not a file to clobber.
        print(
            json.dumps(
                {"ok": False, "code": "runtime_requirement_projection_conflict"},
                sort_keys=True,
            )
        )
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rendered)
    print(json.dumps({"ok": True, "written": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
