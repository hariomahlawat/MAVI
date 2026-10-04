"""``evaluate`` (S3.2d-1 plan §11 step 4): association, then evaluation, then the report, written once.

Inputs are the frozen descriptor, the prepared directory, the T1 exports and sealed trajectories, the mapping, the
association policy, the registered requirements and the measured pipeline profile. The run envelope is built from
their exact identities plus the tooling identity of this process (computed after every module it uses is loaded),
so the association, result and report all carry one ``benchmarkRunId``. The class-free association artefact is
written before scope B reads any prediction. Output: ``<out>/<benchmarkRunId>/{association.json, result.json,
report.md}``, a new directory that appears only on success; an existing one is refused (``output_exists``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.benchmarks import prepare as preparation
from tools.benchmarks.capabilities.vehicle_subclass import evaluate as evaluation
from tools.benchmarks.capabilities.vehicle_subclass import report as reports
from tools.benchmarks.capabilities.vehicle_tracks import association as associations
from tools.benchmarks.capabilities.vehicle_tracks import mavi_tracks
from tools.benchmarks.capabilities.vehicle_tracks import policy as policies
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core import envelope as envelopes
from tools.benchmarks.core import mapping as mappings
from tools.benchmarks.core import mavi
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import (
    OutputDirectory, S32Error, canonical_json, document_sha256, require, sha256_hex, tooling_identity)

RUNNER_VERSION = "1"
ASSOCIATION, RESULT, REPORT = "association.json", "result.json", "report.md"


def _policy(path: Path) -> policies.Policy:
    data = artefacts.read_bytes(path, "association_policy_invalid")
    document = artefacts.parse_json(data, "association_policy_invalid")
    require(canonical_json(document) == data, "association_policy_invalid:not_canonical")
    return policies.load(document)


def _exports(directory: Path) -> dict[str, artefacts.Export]:
    paths = sorted(Path(directory).glob(f"*/{artefacts.EXPORT_FILE_NAME}"), key=lambda path: path.as_posix())
    require(paths, "export_invalid:none")
    return mavi.load_exports(paths)


def evaluate(*, descriptor_path: Path, derived: Path, exports_dir: Path, evidence_root: Path, mapping_path: Path,
             policy_path: Path, requirements_path: Path, profile_path: Path, out: Path,
             tooling: dict[str, Any] | None = None) -> str:
    """Runs association and evaluation and writes ``out/<benchmarkRunId>``; returns the run id."""
    try:
        return _evaluate(descriptor_path, derived, exports_dir, evidence_root, mapping_path, policy_path,
                         requirements_path, profile_path, out, tooling)
    except S32Error:
        raise
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise S32Error(f"benchmark_input_invalid:{type(exc).__name__}") from exc


def _evaluate(descriptor_path, derived, exports_dir, evidence_root, mapping_path, policy_path, requirements_path,
              profile_path, out, tooling) -> str:
    descriptor, descriptor_sha = descriptors.load(descriptor_path)
    descriptors.require_usable(descriptor)
    require(descriptor["manifest"]["entries"], "source_manifest_missing")
    manifest, manifest_sha, documents = preparation.load(derived)
    require(manifest["descriptorSha256"] == descriptor_sha and manifest["datasetId"] == descriptor["datasetId"]
            and manifest["release"] == descriptor["release"], "derivation_invalid:descriptor")
    split = manifest["split"]
    require(descriptors.split(descriptor, split)["labelled"], f"descriptor_invalid:split_unlabelled:{split}")
    source = preparation.adapter(manifest["adapter"]["id"])
    require(manifest["adapter"]["version"] == source.adapter_version, "derivation_invalid:adapter_version")
    mapping, mapping_sha = mappings.load(mapping_path)
    mappings.require_emitted(mappings.check_against(mapping, descriptor), source.native_classes())
    policy = _policy(policy_path)
    requirements, requirements_sha = evaluation.load_requirements(requirements_path)
    profile_sha = sha256_hex(artefacts.read_bytes(profile_path, "pipeline_profile_unreadable"))
    exports = _exports(exports_dir)
    mavi_block = mavi.mavi_identity(exports, profile_sha)
    runs = {export.video["sourceSha256"]: mavi_tracks.project(export, evidence_root) for export in exports.values()}
    require(len(runs) == len(exports), "export_invalid:duplicate_video")
    rows = manifest["sequences"]
    pairs = []
    for row in rows:
        run = runs.pop(row["derivedVideoSha256"], None)
        require(run is not None, f"benchmark_run_missing:{row['sequenceId']}")
        pairs.append((documents[row["sequenceId"]], run))
    require(not runs, "benchmark_run_unexpected")
    identity = tooling if tooling is not None else tooling_identity()
    envelope = envelopes.build(
        dataset={"datasetId": descriptor["datasetId"], "release": descriptor["release"], "split": split,
                 "descriptorSha256": descriptor_sha},
        sequences=[{"sequenceId": row["sequenceId"], "derivedVideoSha256": row["derivedVideoSha256"],
                    "groundTruthSha256": row["groundTruthSha256"]} for row in rows],
        derivation_manifest_sha256=manifest_sha,
        mavi=mavi_block,
        tooling={"adapterId": source.adapter_id, "adapterVersion": source.adapter_version,
                 "mappingSha256": mapping_sha, "associationPolicySha256": policy.sha256,
                 "requirementsSha256": requirements_sha, "runnerVersion": RUNNER_VERSION, **identity},
        exposure=descriptor["exposure"])
    association = associations.associate(envelope=envelope, policy=policy, descriptor=descriptor, sequences=pairs)
    association_bytes = canonical_json(association)
    result = evaluation.evaluate(association=association, descriptor=descriptor, mapping=mapping,
                                 ground_truth=documents, exports=exports, requirements=requirements,
                                 requirements_sha256=requirements_sha)
    report = reports.render(result)
    run_id = envelope["benchmarkRunId"]
    Path(out).mkdir(parents=True, exist_ok=True)  # the results root holds many runs; created only once all checks pass
    with OutputDirectory(Path(out) / run_id) as staging:
        (staging / ASSOCIATION).write_bytes(association_bytes)
        (staging / RESULT).write_bytes(canonical_json(result))
        (staging / REPORT).write_bytes(report)
    return run_id


def _canonical(path: Path, code: str) -> dict[str, Any]:
    """A stored artefact whose bytes are exactly its canonical form (identity is the SHA-256 of those bytes):
    reformatted, re-spaced or newline-terminated copies are refused, never normalised."""
    data = artefacts.read_bytes(path, code)
    document = artefacts.parse_json(data, code)
    require(canonical_json(document) == data, f"{code}:not_canonical")
    return document


def verify(directory: Path) -> dict[str, Any]:
    """A written results directory, re-checked: the association, the result bound to it, the report regenerated."""
    directory = Path(directory)
    association = _canonical(directory / ASSOCIATION, "association_invalid")
    associations.check(association)
    result = _canonical(directory / RESULT, "result_invalid")
    evaluation.check(result, association)
    require(artefacts.read_bytes(directory / REPORT, "report_invalid") == reports.render(result), "report_invalid")
    require(directory.name == result["envelope"]["benchmarkRunId"], "result_invalid:directory")
    return result


__all__ = ["evaluate", "verify", "document_sha256", "json"]
