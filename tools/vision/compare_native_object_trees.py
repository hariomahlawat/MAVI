#!/usr/bin/env python3
"""Compare two trees of intermediate MSVC/NVCC object files.

The MMCV CUDA build produces 136 objects. When two builds of the same commit
from the same directory with the same toolchain yield different wheels, the
question is whether the compiler produced different code or merely stamped a
different timestamp -- and that question is answered in the objects, before the
linker adds its own variance on top.

Sampling two of the 136 by hand answers it for two. This tool answers it for
all of them, mechanically: every object is parsed, the documented metadata
fields are zeroed, and what remains is compared byte for byte. A single object
that does not reduce to equality is enough to fail, because one divergent
translation unit is one divergent translation unit.

`--require normalized-identical` exits 3 unless every pair is identical or
proved to differ only in named metadata fields.

The tool is offline and reads only the two directories it is given.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from native_binary_metadata import (  # noqa: E402
    ACCEPTABLE_CLASSIFICATIONS,
    compare_native_payloads,
)

SCHEMA_VERSION = "mavi-native-object-tree-comparison-v1"

#: Extensions the MSVC/NVCC toolchain writes as linkable native input. Anything
#: else in the tree (`.cpp`, `.log`, `.tlog`, `.rsp`) is build bookkeeping and
#: is not what the linker consumes.
_OBJECT_SUFFIXES = (".obj", ".o", ".lib", ".a")

#: Unresolved pairs to name in the report before truncating. A build where
#: every object diverges is one situation, not two hundred.
_UNRESOLVED_REPORT_LIMIT = 24


class ObjectTreeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _collect(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        raise ObjectTreeError("object_tree_missing:" + root.name)
    found: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if not path.name.casefold().endswith(_OBJECT_SUFFIXES):
            continue
        relative = path.relative_to(root).as_posix()
        found[relative] = path
    if not found:
        # An empty tree would otherwise report "every object agrees", which is
        # true and useless: the most likely cause is a wrong directory.
        raise ObjectTreeError("object_tree_empty:" + root.name)
    return found


def compare_object_trees(left_root: Path, right_root: Path) -> dict[str, object]:
    left = _collect(left_root)
    right = _collect(right_root)

    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))
    shared = sorted(set(left) & set(right))

    identical: list[str] = []
    normalized: list[str] = []
    unresolved: list[dict[str, object]] = []
    fields_seen: dict[str, int] = {}
    formats_seen: dict[str, int] = {}

    for name in shared:
        left_bytes = left[name].read_bytes()
        right_bytes = right[name].read_bytes()
        if left_bytes == right_bytes:
            identical.append(name)
            native_format = None
        else:
            analysis = compare_native_payloads(left_bytes, right_bytes)
            native_format = analysis.get("format")
            if analysis["classification"] in ACCEPTABLE_CLASSIFICATIONS:
                normalized.append(name)
                for field in analysis.get("normalizedFields", []):
                    key = str(field["name"])
                    fields_seen[key] = fields_seen.get(key, 0) + 1
            else:
                if len(unresolved) < _UNRESOLVED_REPORT_LIMIT:
                    unresolved.append({"object": name, "analysis": analysis})
                else:
                    unresolved.append(
                        {
                            "object": name,
                            "analysis": {
                                "classification": analysis["classification"],
                                "truncated": True,
                            },
                        }
                    )
        if native_format is not None:
            formats_seen[native_format] = formats_seen.get(native_format, 0) + 1

    reproducible = not (only_left or only_right or unresolved)
    if reproducible and not normalized:
        verdict = "identical"
    elif reproducible:
        verdict = "metadata-normalized-identical"
    elif only_left or only_right:
        verdict = "divergent-inventory"
    else:
        verdict = "divergent-content"

    return {
        "schemaVersion": SCHEMA_VERSION,
        "verdict": verdict,
        "left": {"root": left_root.name, "objectCount": len(left)},
        "right": {"root": right_root.name, "objectCount": len(right)},
        "comparedCount": len(shared),
        "identicalCount": len(identical),
        "metadataNormalizedCount": len(normalized),
        "unresolvedCount": len(unresolved),
        "onlyInLeft": only_left[:_UNRESOLVED_REPORT_LIMIT],
        "onlyInRight": only_right[:_UNRESOLVED_REPORT_LIMIT],
        "metadataNormalizedObjects": normalized,
        "unresolved": unresolved[:_UNRESOLVED_REPORT_LIMIT],
        "normalizedFieldCounts": dict(sorted(fields_seen.items())),
        "formatCounts": dict(sorted(formats_seen.items())),
        "note": (
            "Object-level agreement is evidence about the compiler, not about "
            "the wheel: the linker contributes its own variance afterwards. "
            "This is a Development build reproducibility result only and never "
            "satisfies a hardware or Production gate."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require",
        choices=("identical", "normalized-identical"),
        help=(
            "Exit non-zero unless the verdict is at least this strong. "
            "Omit to report without enforcing."
        ),
    )
    args = parser.parse_args()

    try:
        result = compare_object_trees(args.left, args.right)
    except ObjectTreeError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2
    except OSError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "object_tree_comparison_failed",
                    "detail": str(exc)[:200],
                },
                sort_keys=True,
            )
        )
        return 2

    if args.output is not None:
        if args.output.exists():
            print(
                json.dumps(
                    {"ok": False, "code": "object_tree_output_exists"},
                    sort_keys=True,
                )
            )
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    print(json.dumps({"ok": True, "comparison": result}, sort_keys=True))

    if args.require is None:
        return 0
    accepted = {
        "identical": {"identical"},
        "normalized-identical": {"identical", "metadata-normalized-identical"},
    }[args.require]
    return 0 if result["verdict"] in accepted else 3


if __name__ == "__main__":
    raise SystemExit(main())
