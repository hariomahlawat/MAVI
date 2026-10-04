"""Per-native-class mappings (S3.2d-1 plan §6; ADR-017 §4)."""

from __future__ import annotations

import copy

import pytest

from tools.benchmarks.core import mapping as m
from tools.benchmarks.core.identity import S32Error, canonical_json, document_sha256
from tools.benchmarks.datasets import synthetic as s


def refused(code: str):
    return pytest.raises(S32Error, match=f"^{code}")


def row(mapping: dict, native: str) -> dict:
    return next(item for item in mapping["mappings"] if item["nativeClass"] == native)


def test_synthetic_mapping_covers_every_kind():
    mapping = m.check(s.mapping())
    kinds = {(r["kind"], r.get("unsupportedKind")) for r in mapping["mappings"]}
    assert kinds == {("exact", None), ("subset", None), ("unsupported", "outside-capability"),
                     ("unsupported", "vehicle-unresolved")}


def test_subset_mapping_is_valid():
    mapping = copy.deepcopy(s.mapping())
    row(mapping, "car").update(kind="subset", evaluation="subset-conditional")
    m.check(mapping)


@pytest.mark.parametrize("edit, code", [
    (lambda r: r.pop("unsupportedKind"), "mapping_invalid:schema:mappings/3"),          # pedestrian
    (lambda r: r.update(unsupportedKind="maybe"), "mapping_invalid:schema:mappings/3"),
    (lambda r: r.update(maviClass="car"), "mapping_invalid:schema:mappings/3"),          # unsupported with a class
    (lambda r: r.update(evaluation="scored"), "mapping_invalid:schema:mappings/3"),
])
def test_unsupported_row_rules(edit, code):
    mapping = copy.deepcopy(s.mapping())
    edit(row(mapping, "pedestrian"))
    with refused(code):
        m.check(mapping)


@pytest.mark.parametrize("edit", [
    lambda r: r.update(maviClass=None),
    lambda r: r.update(maviClass="van"),
    lambda r: r.update(unsupportedKind="outside-capability"),
    lambda r: r.update(evaluation="excluded"),
    lambda r: r.update(kind="subset"),                          # subset with exact's evaluation value
    lambda r: r.pop("reason"),
])
def test_exact_row_rules(edit):
    mapping = copy.deepcopy(s.mapping())
    edit(row(mapping, "car"))
    with refused("mapping_invalid"):
        m.check(mapping)


def test_duplicate_native_class_is_refused():
    mapping = copy.deepcopy(s.mapping())
    mapping["mappings"].insert(1, copy.deepcopy(mapping["mappings"][1]))
    with refused("mapping_invalid:duplicate_native_class"):
        m.check(mapping)


def test_unsorted_rows_are_refused_so_identity_is_unique():
    mapping = copy.deepcopy(s.mapping())
    mapping["mappings"].reverse()
    with refused("mapping_invalid:order"):
        m.check(mapping)


def test_two_exact_native_classes_for_one_mavi_class_are_refused():
    mapping = copy.deepcopy(s.mapping())
    row(mapping, "truck").update(maviClass="car")
    with refused("mapping_invalid:duplicate_exact:car"):
        m.check(mapping)


def test_subset_beside_an_exact_class_is_refused():
    mapping = copy.deepcopy(s.mapping())
    row(mapping, "van").update(maviClass="car", kind="subset", evaluation="subset-conditional")
    row(mapping, "van").pop("unsupportedKind")
    with refused("mapping_invalid:exact_and_subset:car"):
        m.check(mapping)


def test_mapping_header_must_match_the_release():
    for field, value, code in (("datasetId", "other-set", "mapping_invalid:dataset"),
                               ("release", "v2", "mapping_invalid:release")):
        mapping = copy.deepcopy(s.mapping())
        mapping[field] = value
        with refused(code):
            m.check_against(mapping, s.descriptor())
    mapping = copy.deepcopy(s.mapping())
    mapping["capability"] = "mavi-person-attributes-v1"
    with refused("mapping_invalid:schema:capability"):
        m.check(mapping)


def test_mapping_must_name_exactly_the_taxonomy():
    mapping = copy.deepcopy(s.mapping())
    mapping["mappings"] = [r for r in mapping["mappings"] if r["nativeClass"] != "van"]
    with refused("mapping_incomplete:missing:van"):
        m.check_against(mapping, s.descriptor())
    mapping = copy.deepcopy(s.mapping())
    mapping["mappings"].append({"nativeClass": "zeppelin", "maviClass": None, "kind": "unsupported",
                                "unsupportedKind": "outside-capability", "reason": "Not a road vehicle.",
                                "evaluation": "excluded"})
    with refused("mapping_incomplete:unknown:zeppelin"):
        m.check_against(mapping, s.descriptor())


def test_mapping_must_match_what_the_adapter_emits():
    rows = m.check_against(s.mapping(), s.descriptor())
    m.require_emitted(rows, s.SyntheticAdapter().native_classes())
    with refused("mapping_incomplete:not_emitted:van"):
        m.require_emitted(rows, s.SyntheticAdapter().native_classes() - {"van"})
    with refused("mapping_incomplete:unmapped:tram"):
        m.require_emitted(rows, s.SyntheticAdapter().native_classes() | {"tram"})


def test_identity_is_the_canonical_bytes_and_tracks_every_change():
    base = m.mapping_sha256(s.mapping())
    assert base == document_sha256(s.mapping()) == m.mapping_sha256(copy.deepcopy(s.mapping()))
    changed = copy.deepcopy(s.mapping())
    row(changed, "car").update(reason="Different wording.")
    assert m.mapping_sha256(changed) != base


def test_mapping_file_round_trip(tmp_path):
    path = tmp_path / "mapping.json"
    path.write_bytes(canonical_json(s.mapping()))
    document, sha = m.load(path)
    assert sha == document_sha256(s.mapping())
