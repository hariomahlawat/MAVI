"""The benchmark run envelope (plan §5): identity and provenance embedded in the association and result
artefacts. No capability field lives here.

``benchmarkRunId`` is the SHA-256 of the canonical envelope without that member, so every input below is bound:
the dataset release, split and descriptor hash (which covers the source manifest); each sequence's derived-video
and canonical prepared ground-truth hashes; the derivation manifest; the MAVI execution identity (commit, profile,
the single attested producer, exports and trajectories); the tooling (adapter, mapping, association policy,
registered requirements, tooling commit and behaviour hash with its audit file list); and the exposure block,
which decides how a result may be read (§13). Human-readable ``adapterVersion`` and ``runnerVersion`` are
recorded but never relied on for uniqueness: ``toolingSha256`` is. Nothing here reads a clock.

The envelope has one definition, ``$defs/envelope``, written identically in both schemas that embed it
(``benchmark-association-v1``, ``benchmark-vehicle-subclass-result-v1``); a test keeps the copies equal.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from tools.benchmarks.core.identity import (
    S32Error, document_sha256, require, require_tooling)
from tools.benchmarks.core._stage3 import artefacts

CODE = "envelope_invalid"
ENVELOPE_SCHEMAS = ("benchmark-association-v1", "benchmark-vehicle-subclass-result-v1")


@cache
def _validator():
    import jsonschema

    schema = json.loads((artefacts.SCHEMAS / f"{ENVELOPE_SCHEMAS[0]}.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator({"$ref": "#/$defs/envelope", "$defs": schema["$defs"]},
                                           format_checker=jsonschema.FormatChecker())


def _validate(envelope: dict[str, Any]) -> None:
    error = next(iter(_validator().iter_errors(envelope)), None)
    if error is not None:
        raise S32Error(f"{CODE}:schema:{'/'.join(str(part) for part in error.absolute_path)}")


def _sorted_unique(values: list[Any], key, code: str) -> list[Any]:
    keys = [key(value) for value in values]
    require(len(keys) == len(set(keys)), f"{CODE}:duplicate_{code}")
    return sorted(values, key=key)


def build(*, dataset: dict[str, Any], sequences: list[dict[str, Any]], derivation_manifest_sha256: str,
          mavi: dict[str, Any], tooling: dict[str, Any], exposure: dict[str, Any]) -> dict[str, Any]:
    """The envelope for explicit inputs; lists are put in canonical order and ``benchmarkRunId`` is computed."""
    body = {
        "dataset": dict(dataset),
        "sequences": _sorted_unique([dict(item) for item in sequences], lambda item: item.get("sequenceId"),
                                    "sequence"),
        "derivationManifestSha256": derivation_manifest_sha256,
        "mavi": {**mavi,
                 "exportSha256s": sorted(mavi.get("exportSha256s", [])),
                 "trajectorySha256s": sorted(mavi.get("trajectorySha256s", []))},
        "tooling": dict(tooling),
        "exposure": dict(exposure),
    }
    envelope = {"benchmarkRunId": run_id(body), **body}
    return check(envelope)


def run_id(body: dict[str, Any]) -> str:
    require("benchmarkRunId" not in body, f"{CODE}:run_id_in_body")
    return document_sha256(body)


def check(envelope: dict[str, Any]) -> dict[str, Any]:
    """Schema, canonical order, an audit file list that hashes to ``toolingSha256``, and the run id."""
    _validate(envelope)
    ids = [item["sequenceId"] for item in envelope["sequences"]]
    require(ids == sorted(set(ids)), f"{CODE}:sequence_order")
    for name in ("exportSha256s", "trajectorySha256s"):
        values = envelope["mavi"][name]
        require(values == sorted(set(values)), f"{CODE}:{name}_order")
    require(envelope["mavi"]["producer"]["pipelineProfileSha256"] == envelope["mavi"]["pipelineProfileSha256"],
            "profile_mismatch")
    require(envelope["mavi"]["producer"]["maviCommit"] == envelope["mavi"]["maviCommit"], f"{CODE}:mavi_commit")
    require_tooling(envelope["tooling"])
    body = {key: value for key, value in envelope.items() if key != "benchmarkRunId"}
    require(envelope["benchmarkRunId"] == run_id(body), f"{CODE}:run_id")
    return envelope
