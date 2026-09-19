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

#: What the compiler emits per translation unit, which is the question this
#: tool asks. Deliberately *not* `.lib`/`.a`: an archive is a linker-stage
#: artefact with its own container format and its own timestamps, and MSVC
#: drops the import library for `_ext` into the same temp directory. Treating
#: it as an object would fail every run on a file the compiler did not write.
_OBJECT_SUFFIXES = (".obj", ".o")
#: Native artefacts that are present but out of scope. Counted and named in the
#: report rather than passed over in silence, so "we did not look at that" is
#: visible to whoever reads the evidence.
_OUT_OF_SCOPE_SUFFIXES = (".lib", ".a", ".exp", ".pdb", ".dll", ".pyd")

#: Unresolved pairs to name in the report before truncating. A build where
#: every object diverges is one situation, not two hundred.
_UNRESOLVED_REPORT_LIMIT = 24

#: Largest object this tool will read. MMCV's biggest `/bigobj` output is
#: about 18 MB, so this is generous for the artefacts in scope.
_MAX_OBJECT_BYTES = 128 * 1024 * 1024


class ObjectTreeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _collect(root: Path, out_of_scope: list[str]) -> dict[str, Path]:
    if not root.is_dir():
        raise ObjectTreeError("object_tree_missing:" + root.name)
    found: dict[str, Path] = {}
    skipped: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if not path.name.casefold().endswith(_OBJECT_SUFFIXES):
            if path.name.casefold().endswith(_OUT_OF_SCOPE_SUFFIXES):
                skipped.append(relative)
            continue
        found[relative] = path
    out_of_scope.extend(sorted(skipped))
    if not found:
        # An empty tree would otherwise report "every object agrees", which is
        # true and useless: the most likely cause is a wrong directory.
        raise ObjectTreeError("object_tree_empty:" + root.name)
    return found


def compare_object_trees(left_root: Path, right_root: Path) -> dict[str, object]:
    left_out_of_scope: list[str] = []
    right_out_of_scope: list[str] = []
    left = _collect(left_root, left_out_of_scope)
    right = _collect(right_root, right_out_of_scope)

    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))
    shared = sorted(set(left) & set(right))

    identical: list[str] = []
    normalized: list[str] = []
    unresolved: list[dict[str, object]] = []
    fields_seen: dict[str, int] = {}
    formats_seen: dict[str, int] = {}
    # Why the unresolved ones were unresolved, counted. With 136 objects, the
    # difference between "one is divergent" and "129 share one parser gap" is
    # the whole diagnosis, and it should not require reading 129 entries.
    reasons_seen: dict[str, int] = {}
    headers_seen: dict[str, int] = {}

    for name in shared:
        # A multi-gigabyte object would otherwise raise `MemoryError`, which is
        # not an `OSError`, and the tool would die with a traceback instead of
        # a refusal. The largest honest MMCV object is ~18 MB.
        for side, path in (("left", left[name]), ("right", right[name])):
            if path.stat().st_size > _MAX_OBJECT_BYTES:
                raise ObjectTreeError(f"object_too_large:{side}:{name}")
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
                reason = str(
                    analysis.get("reason") or analysis["classification"]
                )
                reasons_seen[reason] = reasons_seen.get(reason, 0) + 1
                detail = analysis.get("reasonDetail") or {}
                if detail:
                    signature = (
                        f"version={detail.get('version')} "
                        f"machine={detail.get('machine')} "
                        f"classId={detail.get('classId')}"
                    )
                    headers_seen[signature] = headers_seen.get(signature, 0) + 1
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
        "unresolvedReasonCounts": dict(sorted(reasons_seen.items())),
        "unresolvedHeaderSignatures": dict(sorted(headers_seen.items())),
        "outOfScopeNativeFiles": {
            "left": left_out_of_scope,
            "right": right_out_of_scope,
        },
        "formatCounts": dict(sorted(formats_seen.items())),
        "note": (
            "Object-level agreement is evidence about the compiler, not about "
            "the wheel: the linker contributes its own variance afterwards. "
            "This is a Development build reproducibility result only and never "
            "satisfies a hardware or Production gate. Archives and linked "
            "images found in the tree are listed under outOfScopeNativeFiles "
            "and were not compared; compare the wheel for those."
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
    except (OSError, MemoryError) as exc:
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
