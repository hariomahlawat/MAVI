"""S2c.1: task vocabulary and corpus manifest contracts."""

from __future__ import annotations

import copy
import json

import pytest
from attribute_corpus_fixtures import build_corpus

from attributes.corpus import task as task_module
from attributes.corpus.canonical import CorpusError, canonical_json, document_sha256, refuse_path_leaks
from attributes.corpus.manifest import parse_corpus, revise_corpus
from attributes.corpus.task import load_task


# ---- task / vocabulary ---------------------------------------------------------------


def test_candidate_task_matches_the_accepted_plan_vocabulary() -> None:
    task = load_task()
    assert task.status == "candidate"
    assert {s.attribute_type for s in task.attributes} == {
        "person-upper-colour", "person-lower-colour", "person-backpack", "person-bag", "person-headwear", "vehicle-colour",
    }
    person_colours = set(task.attribute("person-upper-colour").values)
    assert person_colours == {"black", "white", "grey", "red", "orange", "yellow", "green", "blue", "brown", "pink", "purple"}
    assert set(task.attribute("vehicle-colour").values) == {
        "black", "white", "grey", "silver", "red", "orange", "yellow", "green", "blue", "brown", "beige",
    }
    assert task.attribute("person-upper-colour").conditional_values == ("multicolour",)
    assert task.attribute("person-headwear").conditional is True
    assert task.attribute("person-backpack").values == ("absent", "present")


def test_no_excluded_or_demographic_attribute_can_enter_the_task() -> None:
    document = copy.deepcopy(load_task().document)
    document["attributes"].append(
        {"attributeType": "gender", "objectClass": "person", "kind": "categorical", "values": ["a", "b"], "conditionalValues": [], "conditional": False}
    )
    with pytest.raises(CorpusError, match="excluded_attribute_present"):
        task_module.parse_task(document)


def test_schema_limits_match_the_s2b_worker() -> None:
    from mavi_vision.attributes import pipeline

    assert task_module.MAXIMUM_TYPES_PER_OBJECT_CLASS == pipeline.MAXIMUM_ATTRIBUTE_TYPES_PER_OBJECT_CLASS
    assert task_module.MAXIMUM_VALUES == pipeline.MAXIMUM_ATTRIBUTE_VALUES


@pytest.mark.parametrize(
    ("attribute", "outcome", "value", "reason"),
    [
        ("person-upper-colour", "value", "magenta", None),
        ("person-upper-colour", "value", "unscorable", None),
        ("person-backpack", "value", "maybe", None),
        ("person-backpack", "unscorable", None, "guess"),
        ("person-backpack", "unscorable", "absent", "occluded"),
        ("vehicle-colour", "value", "silver", None),  # a vehicle value on a person Track
    ],
)
def test_invalid_labels_are_refused(attribute: str, outcome: str, value: str | None, reason: str | None) -> None:
    with pytest.raises(CorpusError):
        load_task().validate_label("person", attribute, outcome, value, reason)


def test_unscorable_is_an_outcome_not_a_negative() -> None:
    task = load_task()
    task.validate_label("person", "person-backpack", "unscorable", None, "occluded")
    task.validate_label("person", "person-backpack", "value", "absent", None)
    with pytest.raises(CorpusError):
        task.validate_label("person", "person-backpack", "value", None, "occluded")


def test_rule_confirmation_may_raise_but_never_lower_a_threshold() -> None:
    document = load_task().document
    with pytest.raises(CorpusError, match="rules_override_lowers"):
        task_module.confirm_rules(document, "owner-1", "2026-10-01T09:00:00Z", {"minimumValueAlpha": 0.5})
    confirmed = task_module.confirm_rules(document, "owner-1", "2026-10-01T09:00:00Z", {"minimumValueAlpha": 0.8})
    assert confirmed["pilotDecisionRules"]["minimumValueAlpha"] == 0.8
    assert task_module.parse_task(confirmed).document["pilotDecisionRules"]["status"] == "owner-confirmed"


# ---- corpus manifest -----------------------------------------------------------------


def test_manifest_hash_is_independent_of_producer_order() -> None:
    document = build_corpus(sites=2, cameras_per_site=1, days=2)
    shuffled = copy.deepcopy(document)
    shuffled["sources"].reverse()
    shuffled["tracks"].reverse()
    for track in shuffled["tracks"]:
        track["observations"].reverse()
    assert parse_corpus(document).sha256 == parse_corpus(shuffled).sha256


def test_manifest_hash_covers_content() -> None:
    document = build_corpus(sites=1, cameras_per_site=1, days=1)
    changed = copy.deepcopy(document)
    changed["tracks"][0]["observations"][0]["sha256"] = "b" * 64
    assert parse_corpus(document).sha256 != parse_corpus(changed).sha256


def test_canonical_encoding_is_stable() -> None:
    assert canonical_json({"b": 1, "a": [2, 1]}) == b'{"a":[2,1],"b":1}\n'
    assert document_sha256({"a": 1}) == document_sha256(json.loads('{"a":1}'))


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d["tracks"].append(copy.deepcopy(d["tracks"][0])), "corpus_duplicate_track"),
        (lambda d: d["tracks"][1]["observations"].__setitem__(0, copy.deepcopy(d["tracks"][0]["observations"][0])), "corpus_duplicate_observation"),
        (lambda d: d["tracks"][0]["observations"][0].__setitem__("role", "hero"), "observation:role"),
        (lambda d: d["tracks"][0].__setitem__("observations", d["tracks"][0]["observations"][1:]), "corpus_track_without_representative"),
        (lambda d: d["sources"][0].__setitem__("siteId", "Main Gate North"), "source:site"),
        (lambda d: d["sources"][0].__setitem__("cameraId", "/mnt/evidence/cam1"), "corpus_path_leak"),
        (lambda d: d["sources"][1].__setitem__("processingRunId", d["sources"][0]["processingRunId"]), "corpus_duplicate_processing_run"),
        (lambda d: d.__setitem__("corpusKind", "real"), "corpus_invalid:kind"),
        (lambda d: d["tracks"][0].__setitem__("evidencePath", "C:\\evidence\\x.jpg"), "corpus_path_leak"),
    ],
)
def test_manifest_refusals(mutate, code: str) -> None:
    document = build_corpus(sites=1, cameras_per_site=2, days=1)
    mutate(document)
    with pytest.raises(CorpusError, match=code):
        parse_corpus(document)


def test_path_leak_guard_allows_ordinary_prose_but_not_paths() -> None:
    refuse_path_leaks({"note": "upper/lower garments; see guide §3"})
    for leak in ("/home/user/crops/", "~/evidence", "D:\\evidence", "file:x", "\\\\server\\share", "https://example.invalid/x"):
        with pytest.raises(CorpusError):
            refuse_path_leaks({"note": leak})


def test_a_revision_is_a_new_identity_that_names_its_predecessor() -> None:
    first = parse_corpus(build_corpus(sites=1, cameras_per_site=1, days=2))
    document = copy.deepcopy(first.document)
    document["tracks"] = document["tracks"][1:]
    with pytest.raises(CorpusError, match="corpus_revision"):
        revise_corpus(first, document)
    document["revision"], document["supersedes"] = 2, first.sha256
    revised = revise_corpus(first, document)
    assert revised.sha256 != first.sha256
