"""Run envelope and MAVI execution identity (S3.2d-1 plan §5)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from tools.benchmarks.core import envelope as e
from tools.benchmarks.core import mavi as m
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import S32Error, canonical_json, document_sha256
from tools.benchmarks.datasets import synthetic as s

ROOT = Path(__file__).resolve().parents[3]
EXPORT_EXAMPLE = ROOT / "contracts" / "examples" / "vehicle-subclass-measurement-export-v1.example.json"
FILES = [{"path": "tools/benchmarks/core/envelope.py", "sha256": "2" * 64},
         {"path": "tools/stage3/artefacts.py", "sha256": "3" * 64}]


def producer() -> dict:
    attestation = json.loads(EXPORT_EXAMPLE.read_text(encoding="utf-8"))["processingRun"]["attestation"]
    return {key: attestation.get(key) for key in (*m.PRODUCER_KEYS, *m.PRODUCER_EXTRA)}


def inputs(**changes) -> dict:
    base = {
        "dataset": {"datasetId": s.DATASET_ID, "release": s.RELEASE, "split": "val", "descriptorSha256": "a" * 64},
        "sequences": [{"sequenceId": "seq-b", "derivedVideoSha256": "5" * 64, "groundTruthSha256": "c" * 64},
                      {"sequenceId": "seq-a", "derivedVideoSha256": "4" * 64, "groundTruthSha256": "b" * 64}],
        "derivation_manifest_sha256": "6" * 64,
        "mavi": {"maviCommit": producer()["maviCommit"], "pipelineProfileSha256": producer()["pipelineProfileSha256"],
                 "producer": producer(), "exportSha256s": ["8" * 64, "7" * 64], "trajectorySha256s": ["9" * 64]},
        "tooling": {"adapterId": "synthetic", "adapterVersion": "1", "mappingSha256": "d" * 64,
                    "associationPolicySha256": "e" * 64, "requirementsSha256": "f" * 64, "runnerVersion": "1",
                    "toolingCommit": "1" * 40, "toolingSha256": document_sha256(FILES),
                    "toolingFiles": copy.deepcopy(FILES)},
        "exposure": {"status": "none-known", "basis": "Synthetic."},
    }
    for path, value in changes.items():
        target = base
        keys = path.split(".")
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
    return base


def test_same_inputs_give_identical_bytes_and_canonical_order():
    first, second = e.build(**inputs()), e.build(**copy.deepcopy(inputs()))
    assert canonical_json(first) == canonical_json(second)
    assert [item["sequenceId"] for item in first["sequences"]] == ["seq-a", "seq-b"]
    assert first["mavi"]["exportSha256s"] == ["7" * 64, "8" * 64]
    body = {key: value for key, value in first.items() if key != "benchmarkRunId"}
    assert first["benchmarkRunId"] == document_sha256(body)


@pytest.mark.parametrize("change", [
    {"dataset.descriptorSha256": "0" * 64},                                      # source bytes / manifest
    {"dataset.split": "train"},
    {"derivation_manifest_sha256": "0" * 64},
    {"mavi.exportSha256s": ["7" * 64]},
    {"mavi.trajectorySha256s": ["0" * 64]},
    {"tooling.mappingSha256": "0" * 64},
    {"tooling.associationPolicySha256": "0" * 64},
    {"tooling.requirementsSha256": "0" * 64},
    {"tooling.toolingCommit": "2" * 40},
    {"exposure": {"status": "possible", "basis": "Detector pretraining may overlap the source imagery."}},
])
def test_every_bound_input_changes_the_run_identity(change):
    assert e.build(**inputs(**change))["benchmarkRunId"] != e.build(**inputs())["benchmarkRunId"]


def test_ground_truth_change_alone_changes_the_run_identity():
    changed = inputs()
    changed["sequences"][1]["groundTruthSha256"] = "0" * 64
    assert e.build(**changed)["benchmarkRunId"] != e.build(**inputs())["benchmarkRunId"]


def test_tooling_behaviour_change_with_the_same_version_labels_changes_the_run_identity():
    files = copy.deepcopy(FILES)
    files[0]["sha256"] = "0" * 64  # an evaluator byte changed; adapterVersion and runnerVersion untouched
    changed = inputs(**{"tooling.toolingFiles": files, "tooling.toolingSha256": document_sha256(files)})
    assert changed["tooling"]["adapterVersion"] == inputs()["tooling"]["adapterVersion"]
    assert e.build(**changed)["benchmarkRunId"] != e.build(**inputs())["benchmarkRunId"]


def test_version_labels_are_recorded_but_not_the_uniqueness_mechanism():
    relabelled = inputs(**{"tooling.runnerVersion": "2"})
    assert e.build(**relabelled)["tooling"]["toolingSha256"] == e.build(**inputs())["tooling"]["toolingSha256"]


def test_check_refuses_a_tampered_envelope():
    envelope = e.build(**inputs())
    tampered = copy.deepcopy(envelope)
    tampered["tooling"]["requirementsSha256"] = "0" * 64
    with pytest.raises(S32Error, match="^envelope_invalid:run_id$"):
        e.check(tampered)
    unsorted = copy.deepcopy(envelope)
    unsorted["sequences"].reverse()
    with pytest.raises(S32Error, match="^envelope_invalid:sequence_order$"):
        e.check(unsorted)
    drifted = copy.deepcopy(envelope)
    drifted["tooling"]["toolingFiles"][0]["sha256"] = "0" * 64
    with pytest.raises(S32Error, match="^envelope_invalid:tooling_sha256$"):
        e.check(drifted)


def test_duplicate_sequences_and_unknown_fields_are_refused():
    duplicated = inputs()
    duplicated["sequences"].append(copy.deepcopy(duplicated["sequences"][0]))
    with pytest.raises(S32Error, match="^envelope_invalid:duplicate_sequence$"):
        e.build(**duplicated)
    with pytest.raises(S32Error, match="^envelope_invalid:schema"):
        e.build(**inputs(**{"tooling.startedUtc": "2026-10-04T00:00:00Z"}))


def test_profile_and_commit_must_agree_with_the_producer():
    with pytest.raises(S32Error, match="^profile_mismatch$"):
        e.build(**inputs(**{"mavi.pipelineProfileSha256": "0" * 64}))
    with pytest.raises(S32Error, match="^envelope_invalid:mavi_commit$"):
        e.build(**inputs(**{"mavi.maviCommit": "another"}))


def test_no_clock_is_read(monkeypatch):
    import datetime
    import time

    def forbidden(*args, **kwargs):
        raise AssertionError("the envelope must not read a clock")

    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(time, "time_ns", forbidden)

    class Frozen(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            forbidden()

        @classmethod
        def utcnow(cls):
            forbidden()

    monkeypatch.setattr(datetime, "datetime", Frozen)
    e.build(**inputs())


def test_envelope_definition_is_identical_in_both_schemas():
    definitions = [json.loads((ROOT / "contracts" / "schemas" / f"{stem}.schema.json").read_text(encoding="utf-8"))
                   ["$defs"] for stem in e.ENVELOPE_SCHEMAS]
    for name in ("envelope", "producer", "exposure", "rational", "fraction"):
        assert definitions[0][name] == definitions[1][name], name


# MAVI execution identity


def export_copy(tmp_path: Path, name: str, edit=None) -> Path:
    document = json.loads(EXPORT_EXAMPLE.read_text(encoding="utf-8"))
    if edit is not None:
        edit(document)
    directory = tmp_path / name
    directory.mkdir()
    path = directory / artefacts.EXPORT_FILE_NAME
    path.write_bytes(canonical_json(document))
    return path


def test_mavi_identity_from_an_export(tmp_path):
    path = export_copy(tmp_path, "run")
    exports = m.load_exports([path])
    profile = next(iter(exports.values())).attestation["pipelineProfileSha256"]
    block = m.mavi_identity(exports, profile)
    vehicles = [t for export in exports.values() for t in m.vehicle_tracks(export)]
    assert block["exportSha256s"] == sorted(exports)
    assert block["trajectorySha256s"] == sorted({t["trajectorySha256"] for t in vehicles})
    assert all(t["objectClass"] == "Vehicle" for t in vehicles)
    assert block["producer"]["pipelineProfileSha256"] == profile == block["pipelineProfileSha256"]
    with pytest.raises(S32Error, match="^profile_mismatch$"):
        m.mavi_identity(exports, "0" * 64)


def test_person_tracks_are_not_selected(tmp_path):
    path = export_copy(tmp_path, "run")
    export = next(iter(m.load_exports([path]).values()))
    assert {t["objectClass"] for t in export.tracks} >= {"Vehicle"}
    assert all(t["objectClass"] == "Vehicle" for t in m.vehicle_tracks(export))
    assert len(m.vehicle_tracks(export)) == sum(t["objectClass"] == "Vehicle" for t in export.tracks)


def test_vehicle_track_without_trajectory_is_refused(tmp_path):
    def drop(document):
        vehicle = next(t for t in document["tracks"] if t["objectClass"] == "Vehicle")
        vehicle["trajectorySha256"] = None

    exports = m.load_exports([export_copy(tmp_path, "run", drop)])
    profile = next(iter(exports.values())).attestation["pipelineProfileSha256"]
    with pytest.raises(S32Error, match="^trajectory_missing:"):
        m.mavi_identity(exports, profile)


def test_mixed_producers_are_refused(tmp_path):
    def second_run(document):
        run = document["processingRun"]
        run["processingRunId"] = run["attestation"]["processingRunId"] = "99999999-9999-4999-8999-999999999999"
        run["videoAssetId"] = run["attestation"]["videoAssetId"] = document["video"]["videoAssetId"] = \
            "88888888-8888-4888-8888-888888888888"
        document["video"]["sourceSha256"] = "0" * 64
        run["attestation"]["maviBuild"] = "another-build"

    paths = [export_copy(tmp_path, "one"), export_copy(tmp_path, "two", second_run)]
    exports = m.load_exports(paths)
    profile = next(iter(exports.values())).attestation["pipelineProfileSha256"]
    with pytest.raises(S32Error, match="^producer_mixed$"):
        m.producer(exports, profile)


def test_trajectories_are_located_by_hash_and_verified(tmp_path):
    data = b"\x82\xa1v\x01\xa6points\x90"
    sha = artefacts.sha256_hex(data)
    sealed = tmp_path / "evidence" / "job" / "attempt-0001" / "trajectories"
    sealed.mkdir(parents=True)
    (sealed / f"track-{sha}.msgpack").write_bytes(data)
    assert m.locate_trajectory(tmp_path / "evidence", sha) == sealed / f"track-{sha}.msgpack"
    with pytest.raises(S32Error, match="^trajectory_missing:"):
        m.locate_trajectory(tmp_path / "evidence", "0" * 64)
    (sealed / f"track-{sha}.msgpack").write_bytes(data + b"\0")
    with pytest.raises(S32Error, match="^trajectory_hash_mismatch:"):
        m.locate_trajectory(tmp_path / "evidence", sha)
    shutil.rmtree(tmp_path / "evidence")
    with pytest.raises(S32Error, match="^trajectory_missing:evidence_root$"):
        m.locate_trajectory(tmp_path / "evidence", sha)
