"""Vehicle-subclass evaluation (S3.2d-1 plan §6, §8): mapping semantics, both scopes, binding and mutation."""

from __future__ import annotations

import copy
import json

import pytest

import eval_fixtures as e
import track_fixtures as f
from eval_fixtures import Scenario, cls, value
from tools.benchmarks.capabilities.vehicle_subclass import evaluate as evaluation
from tools.benchmarks.core.identity import S32Error, canonical_json, document_sha256

CAR = ("car", "car", "exact", None)
TRUCK = ("truck", "truck", "exact", None)
BUS = ("bus", "bus", "exact", None)
MOTO = ("motorcycle", "motorcycle", "exact", None)
VAN = ("van", None, "unsupported", "vehicle-unresolved")
OTHER = ("other", None, "unsupported", "vehicle-unresolved")
PED = ("pedestrian", None, "unsupported", "outside-capability")
RIDER = ("rider", None, "unsupported", "outside-capability")
BICYCLE = ("bicycle", None, "unsupported", "outside-capability")
SEDAN = ("sedan", "car", "subset", None)
TINY = (0.0, 0.0, 0.01, 0.01)  # an observation box far from its object: the IoU gate fails (unverified)


def refused(code: str):
    return pytest.raises(S32Error, match=f"^{code}")


def obj(native, subclass="car", **extra):
    return {"native": native, "subclass": subclass, **extra}


# Recall, support and scope A for exact GT


def test_unmatched_exact_gt_stays_in_scope_a_and_never_lowers_recall(tmp_path):
    result = Scenario(tmp_path, [obj("car"), obj("car"), obj("car", matched=False)], [CAR]).evaluate()
    row = next(item for item in result["scopeA"]["perNativeClass"] if item["nativeClass"] == "car")
    assert (row["gt"]["total"], row["gt"]["assigned"], row["gt"]["unmatched"]) == (3, 2, 1)
    car = cls(result, "car")
    assert car["support"] == 2 and car["recall"] == {"status": "computed",
                                                     "value": {"numerator": 2, "denominator": 2, "value": 1.0}}


def test_undetermined_counts_against_recall_and_evaluable_accuracy_but_not_resolved(tmp_path):
    result = Scenario(tmp_path, [obj("car"), obj("car"), obj("car", None), obj("car", "truck")], [CAR, TRUCK]).evaluate()
    car = cls(result, "car")
    assert car["support"] == 4 and value(car["recall"]["value"]) == 0.5
    assert car["undeterminedShare"] == {"numerator": 1, "denominator": 4, "value": 0.25}
    assert car["accuracyOverEvaluable"]["numerator"] == 2 and car["accuracyOverEvaluable"]["denominator"] == 4
    assert car["accuracyOverResolved"]["numerator"] == 2 and car["accuracyOverResolved"]["denominator"] == 3
    overall = result["scopeB"]["overall"]
    assert (overall["assignedExact"], overall["correct"], overall["resolved"], overall["undetermined"]) == (4, 2, 3, 1)
    # undetermined is not a MAVI class: it enters no precision denominator
    assert cls(result, "car")["precision"]["value"] == {"numerator": 2, "denominator": 2, "value": 1.0}
    assert cls(result, "truck")["precision"]["value"] == {"numerator": 0, "denominator": 1, "value": 0.0}


def test_exact_confusion_has_only_exact_truth_and_every_outcome_column(tmp_path):
    # Subset truth never enters confusion (covered with a subset-only dataset: a subset cannot sit beside an exact
    # car under the mapping rules); unsupported truth never does either.
    result = Scenario(tmp_path, [obj("car"), obj("car", "bus"), obj("van", "car")], [CAR, BUS, VAN]).evaluate()
    confusion = result["scopeB"]["confusion"]
    assert {item["nativeClass"] for item in confusion} == {"bus", "car"}
    assert [item["outcome"] for item in confusion if item["nativeClass"] == "car"] == [
        "car", "truck", "bus", "motorcycle", "undetermined"]
    counts = {(item["nativeClass"], item["outcome"]): item["count"] for item in confusion}
    assert counts[("car", "car")] == 1 and counts[("car", "bus")] == 1 and sum(counts.values()) == 2


# Precision fixtures (plan §6; task §12)


def test_a_vehicle_unresolved_contamination_makes_precision_not_available(tmp_path):
    result = Scenario(tmp_path, [obj("car"), obj("van", "car")], [CAR, VAN]).evaluate()
    car = cls(result, "car")
    assert car["recall"]["status"] == "computed" and value(car["recall"]["value"]) == 1.0
    assert car["precision"]["status"] == "not-available" and car["precision"]["value"] is None
    assert value(car["precision"]["precisionAmongJudgedTracks"]) == 1.0
    assert car["precision"]["unjudgeablePredictions"] == 1


def test_b_without_an_unresolved_car_prediction_precision_is_available(tmp_path):
    for van_outcome in ("truck", None):
        result = Scenario(tmp_path / str(van_outcome), [obj("car"), obj("van", van_outcome)], [CAR, TRUCK, VAN]).evaluate()
        car = cls(result, "car")
        assert car["precision"]["status"] == "computed" and value(car["precision"]["value"]) == 1.0


def test_c_an_outside_capability_track_is_a_judged_false_positive(tmp_path):
    result = Scenario(tmp_path, [obj("car"), obj("car"), obj("pedestrian", "car")], [CAR, PED]).evaluate()
    car = cls(result, "car")
    assert car["precision"]["status"] == "computed"
    assert car["precision"]["value"] == {"numerator": 2, "denominator": 3, "value": 2 / 3}
    assert "pedestrian" in car["precision"]["judgeableNativeClasses"]
    assert result["scopeA"]["outsideCapabilityGt"] == {"total": 1, "vehicleTracksOnOutsideCapabilityGt": 1}


def test_d_predictions_only_on_unresolved_tracks_are_not_available_not_no_judgeable(tmp_path):
    result = Scenario(tmp_path, [obj("car"), obj("van", "truck")], [CAR, TRUCK, VAN]).evaluate()
    truck = cls(result, "truck")
    assert truck["precision"]["status"] == "not-available" and truck["precision"]["unjudgeablePredictions"] == 1
    assert truck["precision"]["precisionAmongJudgedTracks"]["denominator"] == 0
    bus = cls(result, "bus")
    assert bus["precision"]["status"] == "no-judgeable-predictions" and bus["precision"]["value"] is None
    assert bus["precision"]["precisionAmongJudgedTracks"] is None


# Subset and unsupported classes


def test_subset_truth_enters_precision_never_recall_or_confusion(tmp_path):
    result = Scenario(tmp_path, [obj("sedan", "truck"), obj("sedan"), obj("sedan", None)], [SEDAN, TRUCK]).evaluate()
    block = result["scopeB"]["subsetBlocks"][0]
    assert block["nativeClass"] == "sedan" and block["maviClass"] == "car" and block["assigned"] == 3
    assert block["resolvedToMapped"]["numerator"] == 1 and block["undeterminedShare"]["numerator"] == 1
    assert {item["outcome"]: item["count"] for item in block["outcomes"]}["truck"] == 1
    car, truck = cls(result, "car"), cls(result, "truck")
    assert car["recall"]["status"] == "not-in-dataset" and car["support"] == 0
    assert car["requirementStatus"] == {"precision": "not-in-dataset", "recall": "not-in-dataset"}
    assert value(car["precision"]["value"]) == 1.0  # a figure over sedans only, named by its judgeable classes
    assert truck["precision"]["value"] == {"numerator": 0, "denominator": 1, "value": 0.0}  # false positive
    assert not [item for item in result["scopeB"]["confusion"] if item["nativeClass"] == "sedan"]


def test_unsupported_classes_are_listed_with_their_outcomes(tmp_path):
    result = Scenario(tmp_path, [obj("car"), obj("van", "car"), obj("van", None), obj("pedestrian", "truck")],
                      [CAR, VAN, PED]).evaluate()
    excluded = {item["nativeClass"]: item for item in result["scopeB"]["excluded"]}
    assert excluded["van"]["unsupportedKind"] == "vehicle-unresolved" and excluded["van"]["assigned"] == 2
    assert {item["outcome"]: item["count"] for item in excluded["van"]["outcomes"]} == {
        "car": 1, "truck": 0, "bus": 0, "motorcycle": 0, "undetermined": 1}
    assert excluded["pedestrian"]["unsupportedKind"] == "outside-capability" and excluded["pedestrian"]["assigned"] == 1


# Scope A populations


def test_outside_capability_gt_never_enters_the_expected_vehicle_denominator(tmp_path):
    objects = [obj("car"), obj("truck", "truck"), obj("pedestrian", "car"), obj("rider", matched=False),
               obj("bicycle", matched=False)]
    result = Scenario(tmp_path, objects, [CAR, TRUCK, PED, RIDER, BICYCLE]).evaluate()
    a = result["scopeA"]
    assert a["expectedVehicleGt"]["total"] == 2 and a["expectedVehicleGt"]["assigned"] == 2
    assert a["associationRate"]["value"] == 1.0
    assert a["outsideCapabilityGt"] == {"total": 3, "vehicleTracksOnOutsideCapabilityGt": 1}
    per = {item["nativeClass"]: item for item in a["perNativeClass"]}
    assert per["rider"]["unsupportedKind"] == "outside-capability" and per["rider"]["gt"]["unmatched"] == 1
    assert a["maviTracks"]["total"] == 3 and a["maviTracks"]["assigned"] == 3


def test_scope_a_buckets_sum_to_their_populations(tmp_path):
    objects = [obj("car"), obj("car", observation=TINY), obj("van", matched=False), obj("pedestrian", "car")]
    result = Scenario(tmp_path, objects, [CAR, VAN, PED]).evaluate()
    for counts in (result["scopeA"]["expectedVehicleGt"], *(s["expectedVehicleGt"] for s in result["scopeA"]["sequences"])):
        assert sum(v for k, v in counts.items() if k != "total") == counts["total"]
    expected = result["scopeA"]["expectedVehicleGt"]
    assert (expected["total"], expected["assigned"], expected["unverified"], expected["unmatched"]) == (3, 1, 1, 1)


@pytest.mark.parametrize("unverified, limited", [(1, False), (2, True)])
def test_coverage_limited_threshold_is_strictly_above_one_tenth(tmp_path, unverified, limited):
    objects = [obj("car", observation=TINY) if index < unverified else obj("car") for index in range(10)]
    result = Scenario(tmp_path, objects, [CAR]).evaluate()
    rate = result["scopeA"]["coverageLimitedGtRate"]
    assert (rate["numerator"], rate["denominator"]) == (unverified, 10)
    assert result["scopeA"]["coverageLimited"] is limited
    assert result["scopeA"]["escalationThreshold"] == {"numerator": 1, "denominator": 10}


# Support floor, statuses, macro and taxonomy coverage


def test_support_floor_statuses_macro_and_taxonomy(tmp_path):
    objects = [obj("car") for _ in range(30)] + [obj("bus", "bus")]
    result = Scenario(tmp_path, objects, [CAR, BUS, VAN]).evaluate()
    car, bus, truck = cls(result, "car"), cls(result, "bus"), cls(result, "truck")
    assert result["requirements"]["supportFloor"] == 30
    assert car["support"] == 30 and car["supportStatus"] == "adequate"
    assert car["requirementStatus"] == {"precision": "no-requirement", "recall": "no-requirement"}
    assert bus["requirementStatus"] == {"precision": "insufficient-support", "recall": "insufficient-support"}
    assert truck["recall"]["status"] == "not-in-dataset"
    assert truck["requirementStatus"] == {"precision": "not-in-dataset", "recall": "not-in-dataset"}
    macro = result["scopeB"]["macro"]
    assert macro["classes"] == ["car"] and value(macro["recall"]) == 1.0
    assert result["scopeB"]["taxonomyCoverage"] == "partial"


def test_macro_over_no_qualifying_class_is_unavailable_and_coverage_none(tmp_path):
    result = Scenario(tmp_path, [obj("sedan")], [SEDAN]).evaluate()
    assert result["scopeB"]["macro"] == {"classes": [], "recall": None, "accuracyOverResolved": None}
    assert result["scopeB"]["taxonomyCoverage"] == "none"


def test_full_taxonomy_coverage(tmp_path):
    result = Scenario(tmp_path, [obj("car")], [CAR, TRUCK, BUS, MOTO]).evaluate()
    assert result["scopeB"]["taxonomyCoverage"] == "full"


# Worked examples (plan §6)


def test_worked_example_car_bus_van_other(tmp_path):
    objects = [obj("car"), obj("car", "truck"), obj("bus", "bus"), obj("van", "car"), obj("other", "bus")]
    result = Scenario(tmp_path, objects, [CAR, BUS, VAN, OTHER]).evaluate()
    car, bus, truck, moto = (cls(result, name) for name in ("car", "bus", "truck", "motorcycle"))
    assert car["recall"]["status"] == bus["recall"]["status"] == "computed"
    assert car["precision"]["status"] == "not-available" and car["precision"]["unjudgeablePredictions"] == 1
    assert bus["precision"]["status"] == "not-available" and bus["precision"]["unjudgeablePredictions"] == 1
    assert truck["recall"]["status"] == moto["recall"]["status"] == "not-in-dataset"
    assert truck["precision"]["value"] == {"numerator": 0, "denominator": 1, "value": 0.0}  # truck on an exact car
    assert moto["precision"]["status"] == "no-judgeable-predictions"


def test_worked_example_sedan_van_other(tmp_path):
    result = Scenario(tmp_path, [obj("sedan"), obj("van", "car"), obj("other", None)], [SEDAN, VAN, OTHER]).evaluate()
    car = cls(result, "car")
    assert car["recall"]["status"] == "not-in-dataset" and result["scopeB"]["subsetBlocks"][0]["nativeClass"] == "sedan"
    assert car["precision"]["status"] == "not-available"  # a van was predicted car: no unqualified car claim
    assert car["requirementStatus"] == {"precision": "not-in-dataset", "recall": "not-in-dataset"}


# Binding (task §4, §21, §29)


def test_inputs_must_be_the_ones_the_envelope_binds(tmp_path):
    scenario = Scenario(tmp_path, [obj("car"), obj("van", "car")], [CAR, VAN])
    other_mapping = e.mapping_doc([CAR, ("van", "car", "subset", None)])
    with refused("mapping_invalid:exact_and_subset"):
        scenario.evaluate(mapping=other_mapping)
    relabelled = copy.deepcopy(scenario.mapping)
    relabelled["mappings"][1]["reason"] = "Changed wording."
    with refused("result_invalid:mapping_mismatch$"):
        scenario.evaluate(mapping=relabelled)
    with refused("result_invalid:requirements_mismatch$"):
        scenario.evaluate(requirements_sha256="0" * 64)
    changed = copy.deepcopy(scenario.document)
    changed["tracks"][0]["nativeClass"] = "van"
    with refused("result_invalid:ground_truth_mismatch:seq-1$"):
        scenario.evaluate(ground_truth={"seq-1": changed})
    with refused("result_invalid:ground_truth_sequences$"):
        scenario.evaluate(ground_truth={})
    other_descriptor = copy.deepcopy(scenario.descriptor)
    other_descriptor["datasetName"] = "Another name"
    with refused("result_invalid:descriptor_mismatch$"):
        scenario.evaluate(descriptor=other_descriptor)


def test_exports_must_be_the_envelope_exports(tmp_path):
    scenario = Scenario(tmp_path / "a", [obj("car")], [CAR])
    foreign = Scenario(tmp_path / "b", [obj("car", "bus")], [CAR])
    with refused("result_invalid:mavi_export_mismatch$"):
        scenario.evaluate(exports=foreign.exports)


def test_a_tampered_association_is_refused(tmp_path):
    scenario = Scenario(tmp_path, [obj("car")], [CAR])
    tampered = copy.deepcopy(scenario.association)
    tampered["sequences"][0]["pairs"] = []
    with refused("association_invalid:body_sha256$"):
        scenario.evaluate(association=tampered)


def test_a_result_is_bound_to_its_own_association(tmp_path):
    first = Scenario(tmp_path / "a", [obj("car")], [CAR])
    second = Scenario(tmp_path / "b", [obj("car"), obj("car")], [CAR])
    result = first.evaluate()
    evaluation.check(result, first.association)
    with refused("result_invalid:association_run_mismatch$"):
        evaluation.check(result, second.association)
    forged = copy.deepcopy(result)
    forged["requirements"]["sha256"] = "0" * 64
    with refused("result_invalid:requirements_mismatch$"):
        evaluation.check(forged)


def test_requirements_must_be_the_registered_file(tmp_path):
    document, sha = evaluation.load_requirements(e.REQUIREMENTS)
    assert sha == "ca28702f82c6845298a2cf348d7b057024923c7a0a0f4fd496097bf1b7272d75"
    changed = copy.deepcopy(document)
    changed["minimumSupport"]["evaluablePerClass"] = 5
    path = tmp_path / "requirements.json"
    path.write_bytes(canonical_json(changed))
    with refused("requirements_not_registered$"):
        evaluation.load_requirements(path)
    path.write_bytes(canonical_json(document) + b"\n")
    with refused("requirements_invalid:not_canonical$"):
        evaluation.load_requirements(path)


def test_gt_class_outside_the_mapping_is_refused(tmp_path):
    scenario = Scenario(tmp_path, [obj("car")], [CAR, VAN])
    with refused("result_invalid:native_class_unmapped:"):
        Scenario(tmp_path / "x", [obj("tram")], [CAR], mapping=scenario.mapping, descriptor=scenario.descriptor).evaluate()


# Mutation isolation (task §25)


def test_prediction_mutation_changes_scope_b_not_the_association_body(tmp_path):
    base = Scenario(tmp_path / "a", [obj("car"), obj("car")], [CAR, TRUCK])
    mutated = Scenario(tmp_path / "b", [obj("car"), obj("car", "truck")], [CAR, TRUCK])
    assert base.association["associationBodySha256"] == mutated.association["associationBodySha256"]
    assert base.evaluate()["scopeB"] != mutated.evaluate()["scopeB"]


def test_native_class_mutation_changes_interpretation_not_the_association_body(tmp_path):
    base = Scenario(tmp_path / "a", [obj("car"), obj("car")], [CAR, VAN])
    mutated = Scenario(tmp_path / "b", [obj("car"), obj("van", "car")], [CAR, VAN])
    assert base.association["associationBodySha256"] == mutated.association["associationBodySha256"]
    assert base.association["envelope"]["benchmarkRunId"] != mutated.association["envelope"]["benchmarkRunId"]
    assert cls(base.evaluate(), "car")["precision"]["status"] == "computed"
    assert cls(mutated.evaluate(), "car")["precision"]["status"] == "not-available"


def test_mapping_mutation_changes_run_identity_and_interpretation_not_the_association_body(tmp_path):
    base = Scenario(tmp_path / "a", [obj("car"), obj("van", "car")], [CAR, VAN])
    remapped = Scenario(tmp_path / "b", [obj("car"), obj("van", "car")], [CAR, ("van", None, "unsupported",
                                                                                 "outside-capability")])
    assert base.association["associationBodySha256"] == remapped.association["associationBodySha256"]
    assert base.association["envelope"]["benchmarkRunId"] != remapped.association["envelope"]["benchmarkRunId"]
    assert cls(base.evaluate(), "car")["precision"]["status"] == "not-available"
    assert cls(remapped.evaluate(), "car")["precision"]["value"] == {"numerator": 1, "denominator": 2, "value": 0.5}


# Determinism and write-once


def test_evaluation_is_deterministic_and_written_once(tmp_path):
    scenario = Scenario(tmp_path, [obj("car"), obj("van", "car"), obj("pedestrian", None)], [CAR, VAN, PED])
    first, second = scenario.evaluate(), scenario.evaluate()
    assert canonical_json(first) == canonical_json(second)
    assert first["associationSha256"] == document_sha256(scenario.association)
    data = evaluation.write(first, tmp_path / "result.json")
    assert data == canonical_json(first)
    with refused("output_exists$"):
        evaluation.write(first, tmp_path / "result.json")
    assert json.loads(data)["envelope"] == scenario.association["envelope"]
