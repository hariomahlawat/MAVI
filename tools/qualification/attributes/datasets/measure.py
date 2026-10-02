"""Component measurements over a still-dataset manifest (``mavi-attribute-component-result-v1``).

A result binds exactly the evidence it was computed from:
- the still-dataset manifest SHA-256;
- the method identity (the colour-probe configuration SHA-256);
- the executing code identity (Git commit, a local-changes flag, module SHA-256s).

A result missing any of these is refused. There is no wall-clock field, so a rerun on the
same inputs is byte-identical.

Measurement is evaluation of public stills. It re-authorises every image and label member
it reads, through the #141 machinery: ``benchmark`` samples for ``benchmarking``, every
other role as a ``development`` diagnostic. It verifies every image against its sample
id.

**Colour.** The probe runs only on rows whose truth is a named colour. Missing, unmapped
and unscorable (``ambiguous``) rows are counted, never scored. Abstentions stay in the
denominator. Every figure is an exact ``{numerator, denominator}``.

**Presence** (backpack, bag, headwear) has no per-sample predictor. Only support,
prevalence and missing counts are reported, with no confusion matrix, precision, recall
or F1.

All results are **source-native or proxy component evidence on public stills**, never
MAVI operational accuracy and never qualification evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from fractions import Fraction
from pathlib import Path

from attributes.corpus.canonical import CorpusError, canonical_json, lf_normalised_sha256, require, require_sha256, sha256_hex
from attributes.corpus.task import CANDIDATE_TASK_PATH, load_task

from .adapters import pa100k
from .colour_probe import ABSTENTIONS, ColourProbe, parse_probe_config, probe_sha256
from .mapping import mapping_sha256
from .release import authorise_release_use, release_sha256, verify_release_files
from .still_manifest import ROLE_PURPOSE, load_person_mappings, parse_still_dataset, still_dataset_sha256

RESULT_SCHEMA = "mavi-attribute-component-result-v1"
COLOUR_ATTRIBUTES = ("person-lower-colour", "person-upper-colour")
PRESENCE_ATTRIBUTES = ("person-backpack", "person-bag", "person-headwear")
CLAIM = ("component-level measurement on public still images under source-native or proxy label semantics; "
         "not MAVI operational accuracy and not qualification evidence")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
GROUP_CAVEAT = {
    "synthetic-allocation": "synthetic allocation groups of consecutive image numbers are not identity- or tracklet-disjoint; "
                            "leakage between training, selection and development rows is possible",
    "authentic": "authentic source groups (for example vehicle ids) are kept within one role",
}
PUBLIC_DATA_CAVEAT = ("public datasets are widely used in pretraining and public benchmarks; candidate models may have seen these "
                      "images, so figures are not independent generalisation evidence")
COLOUR_KEYS = {"rows", "truth", "eligible", "unsupportedValues", "abstentions", "predicted", "coverage", "confusion", "perValue", "aggregate"}
PRESENCE_KEYS = {"rows", "truth", "support", "prevalence", "predictions", "predictorNote"}


def measurement_purpose(role: str) -> str:
    """Benchmark samples are measured for benchmarking; every other role is a diagnostic."""
    require(role in ROLE_PURPOSE, f"component_result_role:{role}")
    return "benchmarking" if role == "benchmark" else "development"


def code_identity() -> dict:
    """Git commit, local-changes flag and module hashes, as ``review_inventory`` records them,
    plus the data files results depend on: the mapping records, the probe configuration and
    the task vocabulary, whose value order is the probe's tie order. Hashes are LF-normalised,
    so a Windows checkout and a Linux checkout of the same commit agree."""
    package = Path(__file__).resolve().parent
    qualification = package.parent.parent
    try:
        commit = subprocess.run(["git", "-C", str(qualification), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(qualification), "status", "--porcelain"], capture_output=True, text=True, timeout=30, check=True).stdout.strip() != ""
    except (OSError, subprocess.SubprocessError):
        commit, dirty = None, None
    modules = {p.relative_to(package).as_posix(): lf_normalised_sha256(p) for p in sorted(package.rglob("*.py"))}
    data = {p.relative_to(package).as_posix(): lf_normalised_sha256(p) for p in sorted((package / "data").rglob("*.json"))}
    data["task:" + CANDIDATE_TASK_PATH.name] = lf_normalised_sha256(CANDIDATE_TASK_PATH)
    return {"repository": {"commit": commit or None, "localChanges": dirty}, "moduleSha256": modules, "dataSha256": data}


def _fraction(numerator: int, denominator: int) -> dict | None:
    return None if denominator == 0 else {"numerator": numerator, "denominator": denominator}


def _colour_metrics(entries: list[tuple[dict, dict | None]], values: list[str], unsupported: list[str]) -> dict:
    """``entries`` holds (truth entry, prediction or None when not scored), for one role and attribute."""
    truth = {"missing": 0, "unmapped": 0, "unscorable": 0, "value": 0}
    abstentions = dict.fromkeys(ABSTENTIONS, 0)
    confusion = {v: dict.fromkeys(values, 0) for v in values}
    for entry, prediction in entries:
        truth["missing" if entry["truth"] == "missing" else entry["outcome"]] += 1
        if prediction is None:
            continue
        if prediction["outcome"] == "abstain":
            abstentions[prediction["reason"]] += 1
        else:
            confusion[entry["value"]][prediction["value"]] += 1
    eligible = truth["value"]
    predicted = eligible - sum(abstentions.values())
    correct = sum(confusion[v][v] for v in values)
    per_value, recalls = {}, []
    for value in values:
        support = sum(1 for e, p in entries if e["truth"] == "present" and e["outcome"] == "value" and e["value"] == value)
        as_value = sum(confusion[t][value] for t in values)
        per_value[value] = {"support": support, "predictedAs": as_value, "correct": confusion[value][value],
                            "recallOverSupport": _fraction(confusion[value][value], support),
                            "precisionOverPredicted": _fraction(confusion[value][value], as_value)}
        if support:
            recalls.append(Fraction(confusion[value][value], support))
    macro = sum(recalls, Fraction(0)) / len(recalls) if recalls else None
    return {
        "rows": len(entries), "truth": truth, "eligible": eligible, "unsupportedValues": unsupported,
        "abstentions": abstentions, "predicted": predicted,
        "coverage": _fraction(predicted, eligible),
        "confusion": confusion,
        "perValue": per_value,
        "aggregate": {"correctOverEligible": _fraction(correct, eligible), "correctOverPredicted": _fraction(correct, predicted),
                      "macroRecallOverSupportedValues": None if macro is None else {"numerator": macro.numerator, "denominator": macro.denominator},
                      "supportedValues": len(recalls)},
    }


def _presence_metrics(entries: list[dict]) -> dict:
    truth = {"missing": 0, "source-binary:negative": 0, "source-binary:positive": 0}
    for entry in entries:
        truth["missing" if entry["truth"] == "missing" else f"{entry['outcome']}:{entry['value']}"] += 1
    present = truth["source-binary:negative"] + truth["source-binary:positive"]
    return {"rows": len(entries), "truth": truth, "support": present,
            "prevalence": _fraction(truth["source-binary:positive"], present),
            "predictions": None,
            "predictorNote": "no per-sample presence predictor exists; no confusion matrix, precision, recall or F1 is reported"}


def measure_person(manifest: dict, pa_release: dict, pa_root: Path, upar_release: dict, roles: list[str],
                   probe_config: dict, code: dict | None = None) -> dict:
    """Measure one still-dataset manifest. Refuses unverified or unauthorised input."""
    parse_still_dataset(manifest)
    manifest_sha = still_dataset_sha256(manifest)
    bound = {r["releaseId"]: r["releaseSha256"] for r in manifest["releases"]}
    for release in (pa_release, upar_release):
        require(bound.get(release["releaseId"]) == release_sha256(release), f"component_result_release_not_bound:{release['releaseId']}")
    mappings = load_person_mappings()
    for entry in manifest["mappings"]:
        require(entry["mappingId"] in mappings and mapping_sha256(mappings[entry["mappingId"]]) == entry["mappingSha256"],
                f"component_result_mapping_not_bound:{entry['mappingId']}")
    roles = sorted(set(roles))
    require(roles, "component_result_no_roles")
    for role in roles:
        measurement_purpose(role)
    problems = verify_release_files(pa_release, pa_root)
    require(not problems, f"component_result_release_files:{'; '.join(problems)}")

    releases = {pa_release["releaseId"]: pa_release, upar_release["releaseId"]: upar_release}
    cache: dict[tuple, list[str]] = {}

    def blockers(release_id: str, purposes: tuple[str, ...], member: str) -> list[str]:
        key = (release_id, purposes, member)
        if key not in cache:
            cache[key] = authorise_release_use(releases[release_id], list(purposes), (), member)
        return cache[key]

    samples = [s for s in manifest["samples"] if s["role"] in roles]
    refused = []
    for sample in samples:
        # A diagnostic never stands alone: like a smoke build, it needs the role's own purpose too,
        # so a `development` grant cannot open training, selection or tuning rows by itself.
        purposes = tuple(sorted({ROLE_PURPOSE[sample["role"]], measurement_purpose(sample["role"])}))
        found = [f"{sample['releaseId']}:{b}" for b in blockers(sample["releaseId"], purposes, sample["memberPath"])]
        for entry in sample["attributes"].values():
            if entry["truth"] == "present":
                found += [f"{entry['labelReleaseId']}:{b}" for b in blockers(entry["labelReleaseId"], purposes, entry["labelMember"])]
        if found:
            refused.append(f"{sample['memberPath']}:{sorted(set(found))[0]}")
    require(not refused, f"component_result_unauthorised:{len(refused)}:{refused[0] if refused else ''}")

    probe = ColourProbe(probe_config)
    task = load_task()
    values = {a: list(task.attribute(a).values) for a in COLOUR_ATTRIBUTES}
    unsupported = {a: list(task.attribute(a).conditional_values) for a in COLOUR_ATTRIBUTES}
    colour_entries = {(a, r): [] for a in COLOUR_ATTRIBUTES for r in roles}
    presence_entries = {(a, r): [] for a in PRESENCE_ATTRIBUTES for r in roles}
    with zipfile.ZipFile(Path(pa_root) / pa100k.IMAGE_ARCHIVE) as archive:
        for sample in sorted(samples, key=lambda s: s["sampleId"]):
            scored = [a for a in COLOUR_ATTRIBUTES if sample["attributes"][a]["truth"] == "present" and sample["attributes"][a]["outcome"] == "value"]
            data = archive.read(sample["memberPath"]) if scored else None
            if data is not None:
                require(hashlib.sha256(data).hexdigest() == sample["sampleId"], f"component_result_image_differs:{sample['memberPath']}")
            for attribute in COLOUR_ATTRIBUTES:
                entry = sample["attributes"][attribute]
                colour_entries[(attribute, sample["role"])].append((entry, probe.predict(attribute, data) if attribute in scored else None))
            for attribute in PRESENCE_ATTRIBUTES:
                presence_entries[(attribute, sample["role"])].append(sample["attributes"][attribute])

    attributes = {}
    for attribute in COLOUR_ATTRIBUTES + PRESENCE_ATTRIBUTES:
        mapping_id = next(s["attributes"][attribute]["mappingId"] for s in samples) if samples else None
        semantics = next(s["attributes"][attribute]["semantics"] for s in samples) if samples else None
        rule = next((r for m in mappings.values() for r in m["attributes"] if r["attributeType"] == attribute), None)
        by_role = {}
        for role in roles:
            if attribute in COLOUR_ATTRIBUTES:
                by_role[role] = _colour_metrics(colour_entries[(attribute, role)], values[attribute], unsupported[attribute])
            else:
                by_role[role] = _presence_metrics(presence_entries[(attribute, role)])
        attributes[attribute] = {"kind": "colour" if attribute in COLOUR_ATTRIBUTES else "presence", "semantics": semantics, "mappingId": mapping_id,
                                 "coverageNote": None if rule is None else rule["coverage"],
                                 "method": probe.config["methodId"] if attribute in COLOUR_ATTRIBUTES else PREVALENCE_METHOD,
                                 "byRole": by_role}
    group_kinds = sorted({s["group"]["kind"] for s in samples})
    contamination = {
        "groupKinds": group_kinds,
        "groupCaveat": "; ".join(GROUP_CAVEAT[k] for k in group_kinds) if group_kinds else None,
        "knownExposure": {r["releaseId"]: [f"{e['subject']}: {e['evidence']}" for e in r["knownExposure"]] for r in (pa_release, upar_release)},
        "publicDataCaveat": PUBLIC_DATA_CAVEAT,
    }
    result = {
        "schemaVersion": RESULT_SCHEMA,
        "evidenceLevel": "component",
        "claim": CLAIM,
        "evidence": {"stillDatasetSha256": manifest_sha, "stillDatasetId": manifest["datasetId"], "smoke": manifest["smoke"] is not None,
                     "methodId": probe.config["methodId"], "methodConfigSha256": probe.sha256, "methodConfig": probe.config,
                     "code": code if code is not None else code_identity()},
        "rolesMeasured": roles,
        "measurementPurposes": {r: measurement_purpose(r) for r in roles},
        "contamination": contamination,
        "attributes": attributes,
    }
    return parse_component_result(result)


PREVALENCE_METHOD = "dataset-prevalence-diagnostic-v1"


def _count(value: object, code: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, f"{code}:count")
    return value


def _check_fraction(value: object, code: str) -> None:
    if value is None:
        return
    require(isinstance(value, dict) and set(value) == {"numerator", "denominator"}, f"{code}:fraction")
    numerator, denominator = value["numerator"], value["denominator"]
    require(isinstance(numerator, int) and isinstance(denominator, int) and not isinstance(numerator, bool) and not isinstance(denominator, bool)
            and denominator > 0 and 0 <= numerator <= denominator, f"{code}:fraction")


def _check_colour_metrics(m: dict, values: list[str], code: str) -> None:
    """Types, allowed keys and the identities that tie the counts together."""
    _count(m["rows"], code)
    require(isinstance(m["truth"], dict) and set(m["truth"]) == {"missing", "unmapped", "unscorable", "value"}, f"{code}:truth")
    for v in m["truth"].values():
        _count(v, code)
    _count(m["eligible"], code)
    _count(m["predicted"], code)
    require(isinstance(m["unsupportedValues"], list) and all(isinstance(v, str) for v in m["unsupportedValues"]), f"{code}:unsupported")
    require(isinstance(m["abstentions"], dict) and set(m["abstentions"]) == set(ABSTENTIONS), f"{code}:abstentions")
    for v in m["abstentions"].values():
        _count(v, code)
    confusion = m["confusion"]
    require(isinstance(confusion, dict) and set(confusion) == set(values)
            and all(isinstance(r, dict) and set(r) == set(values) for r in confusion.values()), f"{code}:confusion")
    for row in confusion.values():
        for v in row.values():
            _count(v, code)
    _check_fraction(m["coverage"], code)
    require(isinstance(m["perValue"], dict) and set(m["perValue"]) == set(values), f"{code}:per_value")
    for entry in m["perValue"].values():
        require(isinstance(entry, dict) and set(entry) == {"support", "predictedAs", "correct", "recallOverSupport", "precisionOverPredicted"}, f"{code}:per_value")
        for key in ("support", "predictedAs", "correct"):
            _count(entry[key], code)
        _check_fraction(entry["recallOverSupport"], code)
        _check_fraction(entry["precisionOverPredicted"], code)
    aggregate = m["aggregate"]
    require(isinstance(aggregate, dict) and set(aggregate) == {"correctOverEligible", "correctOverPredicted", "macroRecallOverSupportedValues", "supportedValues"},
            f"{code}:aggregate")
    for key in ("correctOverEligible", "correctOverPredicted", "macroRecallOverSupportedValues"):
        _check_fraction(aggregate[key], code)
    _count(aggregate["supportedValues"], code)
    correct = sum(confusion[v][v] for v in values)
    consistent = (
        sum(m["truth"].values()) == m["rows"]
        and m["eligible"] == m["truth"]["value"]
        and m["predicted"] == m["eligible"] - sum(m["abstentions"].values())
        and sum(sum(r.values()) for r in confusion.values()) == m["predicted"]
        and m["coverage"] == _fraction(m["predicted"], m["eligible"])
        and aggregate["correctOverEligible"] == _fraction(correct, m["eligible"])
        and aggregate["correctOverPredicted"] == _fraction(correct, m["predicted"])
        and all(e["correct"] == confusion[v][v] and e["predictedAs"] == sum(confusion[t][v] for t in values)
                and e["recallOverSupport"] == _fraction(e["correct"], e["support"])
                and e["precisionOverPredicted"] == _fraction(e["correct"], e["predictedAs"]) for v, e in m["perValue"].items())
        and sum(e["support"] for e in m["perValue"].values()) == m["eligible"]
        and aggregate["supportedValues"] == sum(1 for e in m["perValue"].values() if e["support"])
    )
    require(consistent, f"{code}:invariant")


def _check_presence_metrics(m: dict, code: str) -> None:
    _count(m["rows"], code)
    require(isinstance(m["truth"], dict) and set(m["truth"]) == {"missing", "source-binary:negative", "source-binary:positive"}, f"{code}:truth")
    for v in m["truth"].values():
        _count(v, code)
    _count(m["support"], code)
    _check_fraction(m["prevalence"], code)
    positive = m["truth"]["source-binary:positive"]
    consistent = (sum(m["truth"].values()) == m["rows"] and m["support"] == positive + m["truth"]["source-binary:negative"]
                  and m["prevalence"] == _fraction(positive, m["support"]))
    require(consistent, f"{code}:invariant")


def parse_component_result(document: object) -> dict:
    """Refuse a result that does not bind manifest, method and code identity."""
    code = "component_result_invalid"
    require(isinstance(document, dict) and document.get("schemaVersion") == RESULT_SCHEMA, f"{code}:schema")
    evidence = document.get("evidence")
    require(isinstance(evidence, dict), f"{code}:evidence")
    require_sha256(evidence.get("stillDatasetSha256"), f"{code}:manifest_sha256")
    require_sha256(evidence.get("methodConfigSha256"), f"{code}:method_sha256")
    require(isinstance(evidence.get("methodId"), str) and evidence["methodId"], f"{code}:method_id")
    identity = evidence.get("code")
    require(isinstance(identity, dict), f"{code}:code_identity")
    repository = identity.get("repository")
    require(isinstance(repository, dict) and isinstance(repository.get("commit"), str) and _COMMIT_RE.fullmatch(repository["commit"]) is not None,
            f"{code}:code_identity:commit")
    require(isinstance(repository.get("localChanges"), bool), f"{code}:code_identity:local_changes")
    for key in ("moduleSha256", "dataSha256"):
        digests = identity.get(key)
        require(isinstance(digests, dict) and digests, f"{code}:code_identity:{key}")
        for digest in digests.values():
            require_sha256(digest, f"{code}:code_identity:{key}")
    require(document.get("claim") == CLAIM and document.get("evidenceLevel") == "component", f"{code}:claim")
    config = evidence.get("methodConfig")
    parse_probe_config(config)
    require(probe_sha256(config) == evidence["methodConfigSha256"], f"{code}:method_config_differs")
    require(evidence["methodId"] == config["methodId"], f"{code}:method_id")
    roles = document.get("rolesMeasured")
    require(isinstance(roles, list) and roles and roles == sorted(set(roles)) and all(r in ROLE_PURPOSE for r in roles), f"{code}:roles")
    require(document.get("measurementPurposes") == {r: measurement_purpose(r) for r in roles}, f"{code}:measurement_purposes")
    contamination = document.get("contamination")
    require(isinstance(contamination, dict) and isinstance(contamination.get("groupKinds"), list) and isinstance(contamination.get("knownExposure"), dict)
            and isinstance(contamination.get("groupCaveat"), str) and contamination.get("publicDataCaveat") == PUBLIC_DATA_CAVEAT, f"{code}:contamination")
    attributes = document.get("attributes")
    require(isinstance(attributes, dict) and set(attributes) == set(COLOUR_ATTRIBUTES + PRESENCE_ATTRIBUTES), f"{code}:attribute_set")
    task = load_task()
    for attribute, entry in attributes.items():
        require(isinstance(entry, dict) and isinstance(entry.get("byRole"), dict) and sorted(entry["byRole"]) == roles, f"{code}:by_role:{attribute}")
        expected_method = config["methodId"] if attribute in COLOUR_ATTRIBUTES else PREVALENCE_METHOD
        require(entry.get("method") == expected_method, f"{code}:attribute_method:{attribute}")
        for metrics in entry["byRole"].values():
            if attribute in PRESENCE_ATTRIBUTES:
                require(metrics.get("predictions") is None and "confusion" not in metrics and "perValue" not in metrics, f"{code}:presence_prediction_metrics")
                require(isinstance(metrics, dict) and set(metrics) == PRESENCE_KEYS, f"{code}:presence_metrics:{attribute}")
                _check_presence_metrics(metrics, f"{code}:{attribute}")
            else:
                require(isinstance(metrics, dict) and set(metrics) == COLOUR_KEYS, f"{code}:colour_metrics:{attribute}")
                _check_colour_metrics(metrics, list(task.attribute(attribute).values), f"{code}:{attribute}")
    return document


def result_sha256(result: dict) -> str:
    return sha256_hex(canonical_json(result))


def load_manifest_file(path: Path) -> dict:
    """A manifest file must be exactly canonical JSON, so its bytes and its identity agree."""
    data = Path(path).read_bytes()
    manifest = json.loads(data)
    require(canonical_json(manifest) == data, "component_result_manifest_not_canonical")
    return parse_still_dataset(manifest)


__all__ = ["CLAIM", "CorpusError", "RESULT_SCHEMA", "code_identity", "load_manifest_file", "measure_person", "measurement_purpose",
           "parse_component_result", "result_sha256"]
