"""Per-native-class mappings ``benchmark-class-mapping-v1`` (plan §6; ADR-017 §4).

Kinds are declared, never inferred: ``exact`` (the native definition coincides with one MAVI class; scored),
``subset`` (entirely within one MAVI class without covering it; subset-conditional), ``unsupported`` (excluded
from classification scoring) with ``unsupportedKind`` ``vehicle-unresolved`` (a vehicle whose class cannot be
mapped without assumption: unjudgeable) or ``outside-capability`` (not a Vehicle: a judgeable negative). The
evaluation value is implied by the kind and written out.

Rules beyond the schema: native classes are unique and sorted (one mapping, one identity); at most one native
class is ``exact`` for a MAVI class, and a MAVI class with an ``exact`` native class has no ``subset`` one (an
exact class already covers every member of the MAVI class, so a subset class would describe the same objects
twice); the mapping names exactly the descriptor's native classes (``mapping_incomplete`` otherwise) and the
same dataset and release (``mapping_invalid``). Identity is the SHA-256 of the canonical file bytes.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core.identity import document_sha256, read_artefact, require, validate

SCHEMA = "benchmark-class-mapping-v1"
CODE = "mapping_invalid"
CAPABILITY = "mavi-vehicle-subclass-v1"
EVALUATION = {"exact": "scored", "subset": "subset-conditional", "unsupported": "excluded"}


def check(document: dict[str, Any]) -> dict[str, Any]:
    validate(document, SCHEMA, CODE)
    rows = document["mappings"]
    natives = [row["nativeClass"] for row in rows]
    require(len(natives) == len(set(natives)), f"{CODE}:duplicate_native_class")
    require(natives == sorted(natives), f"{CODE}:order")
    for row in rows:
        require(row["evaluation"] == EVALUATION[row["kind"]], f"{CODE}:evaluation:{row['nativeClass']}")
    exact = Counter(row["maviClass"] for row in rows if row["kind"] == "exact")
    duplicated = sorted(cls for cls, count in exact.items() if count > 1)
    require(not duplicated, f"{CODE}:duplicate_exact:{duplicated[0] if duplicated else ''}")
    overlap = sorted({row["maviClass"] for row in rows if row["kind"] == "subset"} & set(exact))
    require(not overlap, f"{CODE}:exact_and_subset:{overlap[0] if overlap else ''}")
    return document


def load(path: Path) -> tuple[dict[str, Any], str]:
    document, _, sha = read_artefact(path, SCHEMA, CODE)
    return check(document), sha


def mapping_sha256(document: dict[str, Any]) -> str:
    return document_sha256(check(document))


def check_against(document: dict[str, Any], descriptor: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The mapping for this release: rows by native class, exactly covering the descriptor's taxonomy."""
    check(document)
    descriptors.check(descriptor)
    require(document["datasetId"] == descriptor["datasetId"], f"{CODE}:dataset")
    require(document["release"] == descriptor["release"], f"{CODE}:release")
    rows = {row["nativeClass"]: row for row in document["mappings"]}
    declared = set(descriptors.native_classes(descriptor))
    unknown = sorted(set(rows) - declared)
    require(not unknown, f"mapping_incomplete:unknown:{unknown[0] if unknown else ''}")
    missing = sorted(declared - set(rows))
    require(not missing, f"mapping_incomplete:missing:{missing[0] if missing else ''}")
    return rows


def require_emitted(rows: dict[str, dict[str, Any]], emitted: set[str]) -> None:
    """The adapter's declared output classes are exactly the mapped native classes (plan §6: a mapping naming a
    class the adapter never emits, or omitting one it does emit, is refused). ``emitted`` is what the adapter
    can emit, not what one split happens to contain."""
    unknown = sorted(emitted - set(rows))
    require(not unknown, f"mapping_incomplete:unmapped:{unknown[0] if unknown else ''}")
    unused = sorted(set(rows) - emitted)
    require(not unused, f"mapping_incomplete:not_emitted:{unused[0] if unused else ''}")
