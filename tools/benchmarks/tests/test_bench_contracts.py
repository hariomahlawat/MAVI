"""The four S3.2d-1 contracts and their examples (S3.2d-1 plan §5)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from tools.benchmarks.core import descriptor as d
from tools.benchmarks.core import envelope as e
from tools.benchmarks.core.identity import SCHEMA_STEMS, canonical_json, document_sha256
from tools.benchmarks.datasets import synthetic as s

ROOT = Path(__file__).resolve().parents[3]


def schema(stem: str) -> dict:
    return json.loads((ROOT / "contracts" / "schemas" / f"{stem}.schema.json").read_text(encoding="utf-8"))


def example(stem: str) -> dict:
    return json.loads((ROOT / "contracts" / "examples" / f"{stem}.example.json").read_text(encoding="utf-8"))


def validator(stem: str):
    return jsonschema.Draft202012Validator(schema(stem), format_checker=jsonschema.FormatChecker())


@pytest.mark.parametrize("stem", SCHEMA_STEMS)
def test_schema_is_valid_strict_and_its_example_validates(stem):
    document = schema(stem)
    jsonschema.Draft202012Validator.check_schema(document)
    assert document["title"] == stem and document["additionalProperties"] is False
    assert document["properties"]["schemaVersion"] == {"const": stem}
    assert not list(validator(stem).iter_errors(example(stem)))


@pytest.mark.parametrize("stem", SCHEMA_STEMS)
def test_every_object_in_every_schema_is_closed(stem):
    def walk(node, where):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node.get("additionalProperties") is False, where
            for key, value in node.items():
                walk(value, f"{where}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{where}/{index}")

    walk(schema(stem), stem)


def test_descriptor_and_mapping_examples_are_the_synthetic_release(tmp_path):
    frozen = d.freeze(s.descriptor(), s.write_source(tmp_path / "source"))
    assert example("benchmark-dataset-release-v1") == frozen
    assert example("benchmark-class-mapping-v1") == s.mapping()


def test_association_example_identities_recompute():
    association = example("benchmark-association-v1")
    e.check(association["envelope"])
    body = {key: association[key] for key in ("policy", "sequences", "alignment")}
    assert association["associationBodySha256"] == document_sha256(body)
    assert association["envelope"]["tooling"]["associationPolicySha256"] == document_sha256(association["policy"])


def test_result_example_identities_recompute():
    result = example("benchmark-vehicle-subclass-result-v1")
    association = example("benchmark-association-v1")
    e.check(result["envelope"])
    assert result["envelope"] == association["envelope"]
    assert result["associationSha256"] == document_sha256(association)
    assert result["mappingSha256"] == document_sha256(example("benchmark-class-mapping-v1"))
    assert result["requirements"]["sha256"] == result["envelope"]["tooling"]["requirementsSha256"]


def test_association_contract_has_no_class_subclass_or_confidence_field():
    substrings = ("class", "confidence")  # covers subclass, nativeClass, maviClass, objectClass, …
    exact = ("outcome", "truth", "prediction", "label")

    def names(node):
        if isinstance(node, dict):
            for key, value in node.get("properties", {}).items():
                yield key
                yield from names(value)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    yield from names(value)
        elif isinstance(node, list):
            for value in node:
                yield from names(value)

    found = {name for name in names(schema("benchmark-association-v1"))
             if any(word in name.lower() for word in substrings) or name.lower() in exact}
    assert not found
    # The matcher itself discriminates: the result contract does carry class fields.
    assert {"maviClass", "nativeClass", "outcome", "truth"} <= set(names(schema("benchmark-vehicle-subclass-result-v1")))


@pytest.mark.parametrize("stem, edit", [
    ("benchmark-class-mapping-v1", lambda doc: doc["mappings"][0].update(kind="exact", maviClass=None)),
    ("benchmark-class-mapping-v1", lambda doc: doc["mappings"][3].pop("unsupportedKind")),
    ("benchmark-dataset-release-v1", lambda doc: doc["manifest"]["entries"][0].update(path="../escape.json")),
    ("benchmark-dataset-release-v1", lambda doc: doc["manifest"]["entries"][0].update(path="C:/x.json")),
    ("benchmark-dataset-release-v1", lambda doc: doc["manifest"]["entries"][0].update(sha256="ABC")),
    ("benchmark-association-v1", lambda doc: doc["policy"].update(minContainment=0.5)),
    ("benchmark-association-v1", lambda doc: doc["sequences"][0]["pairs"][0].update(maviClass="car")),
    ("benchmark-association-v1", lambda doc: doc["envelope"]["tooling"].pop("toolingSha256")),
    ("benchmark-vehicle-subclass-result-v1", lambda doc: doc["scopeB"]["classes"].pop()),
    ("benchmark-vehicle-subclass-result-v1",
     lambda doc: doc["scopeB"]["classes"][0]["precision"].update(status="estimated")),
    ("benchmark-vehicle-subclass-result-v1", lambda doc: doc["scopeA"].pop("scope")),
    # One row per MAVI class: a repeated class with another omitted, a reordered set, a fifth row.
    ("benchmark-vehicle-subclass-result-v1",
     lambda doc: doc["scopeB"]["classes"].__setitem__(1, copy.deepcopy(doc["scopeB"]["classes"][0]))),
    ("benchmark-vehicle-subclass-result-v1", lambda doc: doc["scopeB"]["classes"].reverse()),
    ("benchmark-vehicle-subclass-result-v1",
     lambda doc: doc["scopeB"]["classes"].append(copy.deepcopy(doc["scopeB"]["classes"][0]))),
    # unsupportedKind iff kind is unsupported (as in the mapping contract).
    ("benchmark-vehicle-subclass-result-v1", lambda doc: doc["scopeA"]["perNativeClass"][2].pop("unsupportedKind")),
    ("benchmark-vehicle-subclass-result-v1",
     lambda doc: doc["scopeA"]["perNativeClass"][0].update(unsupportedKind="outside-capability")),
])

def test_invalid_documents_are_rejected_by_the_schema(stem, edit):
    document = copy.deepcopy(example(stem))
    edit(document)
    assert list(validator(stem).iter_errors(document))



def test_rationals_have_one_spelling_and_count_fractions_are_untouched():
    from tools.benchmarks.core.identity import S32Error, require_canonical_rationals

    for stem in SCHEMA_STEMS:
        require_canonical_rationals(example(stem), "invalid")
    association = copy.deepcopy(example("benchmark-association-v1"))
    association["policy"]["minContainment"] = {"numerator": 2, "denominator": 4}  # same value as 1/2
    with pytest.raises(S32Error, match="^association_invalid:not_lowest_terms$"):
        require_canonical_rationals(association, "association_invalid")
    result = copy.deepcopy(example("benchmark-vehicle-subclass-result-v1"))
    result["scopeA"]["alignment"]["sourceRate"] = {"numerator": 10, "denominator": 2}
    with pytest.raises(S32Error, match="^result_invalid:not_lowest_terms$"):
        require_canonical_rationals(result, "result_invalid")
    counts = copy.deepcopy(example("benchmark-vehicle-subclass-result-v1"))
    counts["scopeA"]["associationRate"] = {"numerator": 5, "denominator": 10, "value": 0.5}  # counts, not reduced
    require_canonical_rationals(counts, "result_invalid")


def test_examples_are_lf_utf8_without_bom():
    for stem in SCHEMA_STEMS:
        for kind in ("schemas", "examples"):
            data = (ROOT / "contracts" / kind / f"{stem}.{kind[:-1] if kind == 'examples' else 'schema'}.json"
                    ).read_bytes()
            assert b"\r" not in data and not data.startswith(b"\xef\xbb\xbf")


def test_canonical_form_is_platform_independent():
    document = example("benchmark-dataset-release-v1")
    data = canonical_json(document)
    assert b"\r" not in data and b"\\\\" not in data and data == canonical_json(json.loads(data))
