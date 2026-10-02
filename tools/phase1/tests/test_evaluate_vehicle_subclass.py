"""Stage 3 vehicle-subclass measurement (ADR-016): attribution, outcomes and honest denominators."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[3]
PHASE1 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE1))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_evaluate_ground_truth import event, ground_truth, profile, track  # noqa: E402

SPEC = importlib.util.spec_from_file_location("phase1_vehicle_subclass", PHASE1 / "evaluate_vehicle_subclass.py")
assert SPEC and SPEC.loader
subclass_eval = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subclass_eval
SPEC.loader.exec_module(subclass_eval)
phase1 = subclass_eval.evaluator

VOCABULARY = "mavi-vehicle-subclass-v1"
PROFILE_SHA = "a" * 64
OTHER_PROFILE_SHA = "b" * 64
SOURCE = "detector-native:" + PROFILE_SHA
SCHEMA = json.loads((ROOT / "sample-data/ground-truth/phase1-ground-truth.schema.json").read_text(encoding="utf-8"))


def attestation(run: str = "run", video: str = "video", **change) -> dict:
    """The members of a processing-run attestation this evaluator reads (the response has more)."""
    value = {
        "processingRunId": run,
        "videoAssetId": video,
        "modelId": "rtmdet-m-coco-phase1",
        "modelVersion": "1.0.0",
        "modelManifestSha256": "1" * 64,
        "checkpointSha256": "2" * 64,
        "resolvedConfigSha256": "3" * 64,
        "pipelineProfileId": "phase1-detection-tracking-v1",
        "pipelineProfileVersion": "1.3.0-candidate",
        "pipelineProfileSha256": PROFILE_SHA,
        "qualificationSha256": "4" * 64,
        "verificationStatus": "unverified",
        "runtimeProfileId": "mmdetection-phase1-v1",
        "runtimeProfileSha256": "5" * 64,
        "runtimeVariant": "linux-x86_64-cpu",
        "componentBindingSha256": "6" * 64,
        "maviCommit": "c" * 40,
    }
    value.update(change)
    return value


def labelled(event_id, start, end, x, subclass):
    value = event(event_id, "Vehicle", start, end, x)
    value["vehicleSubclass"] = subclass
    return value


def vehicle(track_id, start, end, offset, x, subclass=None, source=SOURCE, vocabulary=VOCABULARY):
    value = track(track_id, "Vehicle", start, end, offset, x)
    value["objectSubclassVocabulary"] = vocabulary
    value["objectSubclassSource"] = source
    if subclass is not None:
        value["objectSubclass"] = subclass
    return value


def _scenario():
    gt = ground_truth([
        labelled("v1", 1000, 3000, 0.05, "truck"),
        labelled("v2", 1000, 3000, 0.30, "car"),
        labelled("v3", 1000, 3000, 0.55, "bus"),
        labelled("v4", 5000, 7000, 0.05, "car"),
        event("v6", "Vehicle", 5000, 7000, 0.55),  # unlabelled: never scored for subclass
        event("p1", "Person", 8000, 9500, 0.10),
    ])
    tracks = [
        vehicle("t1", 1000, 3000, 2000, 0.05, "truck"),  # correct
        vehicle("t2", 1000, 3000, 2000, 0.30, "truck"),  # wrong: a car read as a truck
        vehicle("t3", 1000, 3000, 2000, 0.55),           # abstained
        vehicle("t4", 5000, 7000, 6000, 0.05, "car"),    # correct
        vehicle("t6", 5000, 7000, 6000, 0.55, "bus"),
        track("t7", "Person", 8000, 9500, 9000, 0.10),
    ]
    return gt, tracks


def _evaluate(gt, tracks, attestations=None, measured=PROFILE_SHA):
    return subclass_eval.evaluate(gt, tracks, profile(), attestations or [attestation()], measured)


def test_outcomes_confusion_and_denominators_are_explicit():
    gt, tracks = _scenario()
    report = _evaluate(gt, tracks)

    assert report["labelledVehicleEvents"] == 4
    assert report["matchedLabelledEvents"] == 4
    assert report["outcomes"] == {"resolved": 3, "abstained": 1}
    assert report["correct"] == 2
    assert report["coverageOverMatched"] == pytest.approx(3 / 4)
    assert report["accuracyOverResolved"] == pytest.approx(2 / 3)
    assert report["accuracyOverMatched"] == pytest.approx(2 / 4)
    assert report["confusion"]["car"] == {"car": 1, "truck": 1, "bus": 0, "motorcycle": 0, "undetermined": 0}
    assert report["confusion"]["bus"]["undetermined"] == 1
    assert report["perSubclass"]["truck"]["precisionOverPredicted"] == pytest.approx(1 / 2)
    assert report["perSubclass"]["car"]["recallOverMatched"] == pytest.approx(1 / 2)
    assert report["perSubclass"]["motorcycle"]["recallOverMatched"] is None


def test_the_report_is_bound_to_the_producing_run():
    gt, tracks = _scenario()
    producer = _evaluate(gt, tracks)["producer"]

    assert producer["processingRunIds"] == ["run"]
    assert producer["subclassSource"] == SOURCE
    assert producer["pipelineProfileSha256"] == PROFILE_SHA
    for key in ("modelManifestSha256", "checkpointSha256", "resolvedConfigSha256", "runtimeProfileSha256",
                "qualificationSha256", "componentBindingSha256", "runtimeVariant", "pipelineProfileVersion"):
        assert producer[key] == attestation()[key], key
    assert producer["maviCommit"] == "c" * 40


def test_predictions_from_another_pipeline_profile_are_refused():
    gt, tracks = _scenario()
    # The run was attested under another profile than the one being measured...
    with pytest.raises(subclass_eval.SubclassEvaluationError, match="attestation_pipeline_profile_mismatch"):
        _evaluate(gt, tracks, [attestation(pipelineProfileSha256=OTHER_PROFILE_SHA)])
    # ...or a Track's source names another profile than its run's attestation.
    tracks[0]["objectSubclassSource"] = "detector-native:" + OTHER_PROFILE_SHA
    with pytest.raises(subclass_eval.SubclassEvaluationError, match="track_subclass_source_mismatch"):
        _evaluate(gt, tracks)


def test_runs_from_different_producers_cannot_be_pooled():
    gt, tracks = _scenario()
    tracks[-1]["processingRunId"] = "run-2"
    for change in ({"checkpointSha256": "9" * 64}, {"maviCommit": "d" * 40}):
        with pytest.raises(subclass_eval.SubclassEvaluationError, match="attestation_producers_differ"):
            _evaluate(gt, tracks, [attestation(), attestation(run="run-2", **change)])
    # The same producer across two runs pools.
    report = _evaluate(gt, tracks, [attestation(), attestation(run="run-2")])
    assert report["producer"]["processingRunIds"] == ["run", "run-2"]


@pytest.mark.parametrize(
    ("attestations", "code"),
    [
        ([], "attestation_missing"),
        ([attestation(modelManifestSha256=None)], "attestation_field_invalid:modelManifestSha256"),
        ([attestation(pipelineProfileSha256="A" * 64)], "attestation_field_invalid:pipelineProfileSha256"),
        ([attestation(componentBindingSha256="short")], "attestation_field_invalid:componentBindingSha256"),
        ([attestation(runtimeVariant=" ")], "attestation_field_invalid:runtimeVariant"),
        ([attestation(), attestation()], "attestation_run_duplicate"),
    ],
)
def test_absent_or_malformed_attestation_fails_closed(attestations, code):
    gt, tracks = _scenario()
    with pytest.raises(subclass_eval.SubclassEvaluationError, match=code):
        subclass_eval.evaluate(gt, tracks, profile(), attestations, PROFILE_SHA)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"processingRunId": "unattested"}, "track_run_not_attested"),
        ({"videoAssetId": "another-video"}, "track_video_not_the_attested_run"),
        ({"objectSubclassSource": None}, "track_subclass_provenance_missing"),
        ({"objectSubclassVocabulary": None}, "track_subclass_provenance_missing"),
        ({"objectSubclassVocabulary": "mavi-vehicle-subclass-v2"}, "track_subclass_vocabulary_invalid"),
        ({"objectSubclass": "suv"}, "track_subclass_invalid"),
    ],
)
def test_an_unattributable_vehicle_track_fails_closed(change, code):
    gt, tracks = _scenario()
    tracks[0].update(change)
    with pytest.raises(subclass_eval.SubclassEvaluationError, match=code):
        _evaluate(gt, tracks)


def test_an_attestation_that_contributed_no_tracks_is_refused():
    gt, tracks = _scenario()
    with pytest.raises(subclass_eval.SubclassEvaluationError, match="attestation_without_tracks"):
        _evaluate(gt, tracks, [attestation(), attestation(run="idle-run")])


@pytest.mark.parametrize("field", ["processingRunId", "id"])
def test_a_non_string_identifier_fails_with_a_code(field):
    gt, tracks = _scenario()
    tracks[0][field] = ["not", "a", "string"]
    with pytest.raises(subclass_eval.SubclassEvaluationError):
        _evaluate(gt, tracks)


def test_a_person_track_carrying_subclass_data_fails_closed():
    gt, tracks = _scenario()
    tracks[-1]["objectSubclassSource"] = SOURCE
    with pytest.raises(subclass_eval.SubclassEvaluationError, match="track_subclass_on_person"):
        _evaluate(gt, tracks)


def test_matching_is_exactly_the_phase1_evaluators():
    gt, tracks = _scenario()
    plain = [{key: value for key, value in t.items() if not key.startswith("objectSubclass")} for t in tracks]
    phase1_pairs = {(m["eventId"], m["trackId"]) for m in phase1.evaluate(gt, plain, profile())["matching"]}
    report = _evaluate(gt, tracks)
    assert {(m["eventId"], m["trackId"]) for m in report["matching"]} <= phase1_pairs
    assert {m["eventId"] for m in report["matching"]} == {"v1", "v2", "v3", "v4"}


def test_the_subclass_members_never_reach_the_phase1_track_validator():
    gt, tracks = _scenario()
    with pytest.raises(phase1.EvaluationError, match="track_invalid"):
        phase1.evaluate(gt, tracks, profile())
    assert _evaluate(gt, tracks)["matchedLabelledEvents"] == 4


def test_an_unmatched_labelled_event_is_counted_not_scored():
    gt = ground_truth([labelled("v1", 1000, 3000, 0.05, "truck")])
    tracks = [vehicle("t1", 1000, 3000, 2000, 0.70, "truck")]  # far away: no spatial match
    report = _evaluate(gt, tracks)
    assert (report["matchedLabelledEvents"], report["unmatchedLabelledEvents"]) == (0, 1)
    assert report["coverageOverMatched"] is None


def test_the_phase1_evaluator_accepts_and_ignores_the_label():
    gt, tracks = _scenario()
    plain = [{key: value for key, value in t.items() if not key.startswith("objectSubclass")} for t in tracks]
    unlabelled = copy.deepcopy(gt)
    for item in unlabelled["events"]:
        item.pop("vehicleSubclass", None)
    assert phase1.evaluate(gt, plain, profile()) == phase1.evaluate(unlabelled, plain, profile())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.update(objectClass="Person", vehicleSubclass="car"),
        lambda e: e.update(vehicleSubclass="bicycle"),
        lambda e: e.update(vehicleSubclass=None),
    ],
)
def test_an_invalid_label_is_refused_by_the_evaluator_and_the_schema(mutate):
    gt = ground_truth([labelled("v1", 1000, 3000, 0.05, "truck")])
    mutate(gt["events"][0])
    with pytest.raises(phase1.EvaluationError, match="ground_truth_vehicle_subclass_invalid"):
        phase1.validate_ground_truth(gt, profile())
    assert list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(gt))


def test_a_labelled_ground_truth_satisfies_the_published_schema():
    gt, _ = _scenario()
    assert not list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(gt))


def test_the_cli_binds_every_input_and_never_overwrites(tmp_path, monkeypatch):
    gt, tracks = _scenario()
    pipeline_profile = tmp_path / "pipeline-profile.json"
    pipeline_profile.write_text('{"profileId": "x"}\n', encoding="utf-8")
    measured = hashlib.sha256(pipeline_profile.read_bytes()).hexdigest()
    for track_ in tracks:
        if "objectSubclassSource" in track_:
            track_["objectSubclassSource"] = "detector-native:" + measured
    files = {"gt.json": gt, "tracks.json": tracks, "profile.json": profile(),
             "attestation.json": attestation(pipelineProfileSha256=measured)}
    for name, value in files.items():
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    argv = ["evaluate_vehicle_subclass.py", "--ground-truth", str(tmp_path / "gt.json"), "--tracks", str(tmp_path / "tracks.json"),
            "--profile", str(tmp_path / "profile.json"), "--pipeline-profile", str(pipeline_profile),
            "--attestation", str(tmp_path / "attestation.json"), "--out", str(tmp_path / "out.json")]
    monkeypatch.setattr(sys, "argv", argv)
    assert subclass_eval.main() == 0
    report = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert report["schemaVersion"] == "mavi-vehicle-subclass-evaluation-v2"
    assert report["inputs"]["pipelineProfileSha256"] == measured == report["producer"]["pipelineProfileSha256"]
    assert report["inputs"]["attestationSha256"] == [hashlib.sha256((tmp_path / "attestation.json").read_bytes()).hexdigest()]
    assert subclass_eval.main() == 2

    # A different pipeline profile file under measurement is refused, not silently scored.
    pipeline_profile.write_text('{"profileId": "y"}\n', encoding="utf-8")
    (tmp_path / "out.json").unlink()
    assert subclass_eval.main() == 2
    assert not (tmp_path / "out.json").exists()
