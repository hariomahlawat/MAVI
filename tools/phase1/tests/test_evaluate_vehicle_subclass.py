"""Stage 3 vehicle-subclass measurement (ADR-016): labels, outcomes and honest denominators."""

from __future__ import annotations

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
SCHEMA = json.loads((ROOT / "sample-data/ground-truth/phase1-ground-truth.schema.json").read_text(encoding="utf-8"))


def labelled(event_id, start, end, x, subclass):
    value = event(event_id, "Vehicle", start, end, x)
    value["vehicleSubclass"] = subclass
    return value


def vehicle(track_id, start, end, offset, x, subclass=None, vocabulary=VOCABULARY):
    value = track(track_id, "Vehicle", start, end, offset, x)
    value["objectSubclassVocabulary"] = vocabulary
    if subclass is not None:
        value["objectSubclass"] = subclass
    return value


def _scenario():
    gt = ground_truth([
        labelled("v1", 1000, 3000, 0.05, "truck"),
        labelled("v2", 1000, 3000, 0.30, "car"),
        labelled("v3", 1000, 3000, 0.55, "bus"),
        labelled("v4", 5000, 7000, 0.05, "car"),
        labelled("v5", 5000, 7000, 0.30, "car"),
        event("v6", "Vehicle", 5000, 7000, 0.55),  # unlabelled: never scored for subclass
        event("p1", "Person", 8000, 9500, 0.10),
    ])
    tracks = [
        vehicle("t1", 1000, 3000, 2000, 0.05, "truck"),  # correct
        vehicle("t2", 1000, 3000, 2000, 0.30, "truck"),  # wrong: a car read as a truck
        vehicle("t3", 1000, 3000, 2000, 0.55),           # abstained
        vehicle("t4", 5000, 7000, 6000, 0.05, "car"),    # correct
        track("t5", "Vehicle", 5000, 7000, 6000, 0.30),  # processed before Stage 3
        vehicle("t6", 5000, 7000, 6000, 0.55, "bus"),
        track("t7", "Person", 8000, 9500, 9000, 0.10),
    ]
    return gt, tracks


def test_outcomes_confusion_and_denominators_are_explicit():
    gt, tracks = _scenario()
    report = subclass_eval.evaluate(gt, tracks, profile())

    assert report["labelledVehicleEvents"] == 5
    assert report["matchedLabelledEvents"] == 5
    assert report["outcomes"] == {"resolved": 3, "abstained": 1, "notAvailable": 1}
    assert report["correct"] == 2
    assert report["coverageOverMatched"] == pytest.approx(3 / 5)
    assert report["accuracyOverResolved"] == pytest.approx(2 / 3)
    assert report["accuracyOverMatched"] == pytest.approx(2 / 5)
    assert report["confusion"]["car"] == {"car": 1, "truck": 1, "bus": 0, "motorcycle": 0, "undetermined": 0, "not-available": 1}
    assert report["confusion"]["bus"]["undetermined"] == 1
    assert report["perSubclass"]["truck"]["precisionOverPredicted"] == pytest.approx(1 / 2)
    assert report["perSubclass"]["car"]["recallOverMatched"] == pytest.approx(1 / 3)
    assert report["perSubclass"]["motorcycle"]["recallOverMatched"] is None


def test_matching_is_exactly_the_phase1_evaluators():
    gt, tracks = _scenario()
    plain = [{key: value for key, value in t.items() if not key.startswith("objectSubclass")} for t in tracks]
    phase1_pairs = {(m["eventId"], m["trackId"]) for m in phase1.evaluate(gt, plain, profile())["matching"]}
    report = subclass_eval.evaluate(gt, tracks, profile())
    assert {(m["eventId"], m["trackId"]) for m in report["matching"]} <= phase1_pairs
    assert {m["eventId"] for m in report["matching"]} == {"v1", "v2", "v3", "v4", "v5"}


def test_an_unmatched_labelled_event_is_counted_not_scored():
    gt = ground_truth([labelled("v1", 1000, 3000, 0.05, "truck")])
    tracks = [vehicle("t1", 1000, 3000, 2000, 0.70, "truck")]  # far away: no spatial match
    report = subclass_eval.evaluate(gt, tracks, profile())
    assert (report["matchedLabelledEvents"], report["unmatchedLabelledEvents"]) == (0, 1)
    assert report["coverageOverMatched"] is None


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"objectSubclass": "suv"}, "track_subclass_invalid"),
        ({"objectSubclassVocabulary": "mavi-vehicle-subclass-v2"}, "track_subclass_vocabulary_invalid"),
        ({"objectSubclassVocabulary": None, "objectSubclass": "car"}, "track_subclass_without_vocabulary"),
    ],
)
def test_an_invalid_track_subclass_fails_closed(change, code):
    gt = ground_truth([labelled("v1", 1000, 3000, 0.05, "truck")])
    item = vehicle("t1", 1000, 3000, 2000, 0.05, "truck")
    item.update(change)
    with pytest.raises(subclass_eval.SubclassEvaluationError, match=code):
        subclass_eval.evaluate(gt, [item], profile())


def test_the_phase1_evaluator_accepts_and_ignores_the_label():
    gt, tracks = _scenario()
    plain = [{key: value for key, value in t.items() if not key.startswith("objectSubclass")} for t in tracks]
    unlabelled = json.loads(json.dumps(gt))
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


def test_the_cli_writes_its_inputs_and_never_overwrites(tmp_path):
    gt, tracks = _scenario()
    for name, value in (("gt.json", gt), ("tracks.json", tracks), ("profile.json", profile())):
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    argv = ["evaluate_vehicle_subclass.py", "--ground-truth", str(tmp_path / "gt.json"), "--tracks", str(tmp_path / "tracks.json"),
            "--profile", str(tmp_path / "profile.json"), "--out", str(tmp_path / "out.json")]
    sys.argv = argv
    assert subclass_eval.main() == 0
    report = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert report["schemaVersion"] == "mavi-vehicle-subclass-evaluation-v1"
    assert set(report["inputs"]) == {"groundTruthSha256", "tracksSha256", "profileSha256"}
    assert subclass_eval.main() == 2
