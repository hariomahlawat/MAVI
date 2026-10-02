"""Person still-dataset manifest (``mavi-attribute-still-dataset-v1``), plan §4 and §6.

One sample per image, identified by the image SHA-256. Each sample binds:
- its release and member path, official split, group (id and kind) and role;
- per MAVI attribute: whether truth is present or missing, the mapped outcome and value,
  ``source-native`` or ``proxy`` semantics, and the label release and mapping it came from.

Roles for PA-100K:
- official test → ``benchmark``;
- official val → ``development``;
- official train → synthetic allocation groups of 500 consecutive image numbers, with a
  seeded 10% of groups going to ``selection`` and the rest to ``training``.

Synthetic groups are **not** identity- or tracklet-disjoint. Public data never gets a
frozen role; there is no such role here.

Every sample is authorised through the shared #141 machinery: the image release and each
label release it uses must be authorised for the role's purpose (``ROLE_PURPOSE``). A
sample that is not authorised is refused and recorded. Exact duplicates follow the plan's
role rule (``_resolve_exact``). Near duplicates are only reported, through the shared
pigeonhole primitive; dHash never removes anything.
"""

from __future__ import annotations

import hashlib
import json
import math
import zipfile
from collections import defaultdict
from pathlib import Path

from attributes.corpus.canonical import CorpusError, canonical_json, hash_rank, require, require_sha256, sha256_hex
from attributes.corpus.duplicates import dhash64, pigeonhole_pairs

from .adapters import pa100k, upar
from .mapping import apply_mapping, mapping_sha256, parse_mapping
from .release import authorise_release_use, release_sha256, verify_release_files

STILL_SCHEMA = "mavi-attribute-still-dataset-v1"
NEAR_REPORT_SCHEMA = "mavi-attribute-still-near-duplicates-v1"
ROLE_PURPOSE = {"training": "training", "development": "tuning", "selection": "selection",
                "benchmark": "benchmarking", "regression": "regression-challenge"}
DIAGNOSTICS_PURPOSE = "development"
EVALUATION_ROLES = ("benchmark", "development", "regression", "selection")
GROUP_KINDS = ("authentic", "synthetic-allocation")
SPLIT_ROLE = {"val": "development", "test": "benchmark"}
MAPPINGS_DIR = Path(__file__).resolve().parent / "data" / "mappings"
PERSON_MAPPINGS = {"pa100k-person-presence-v1": "pa-100k-2017", "upar-task1-person-colour-v1": "upar-challenge-2027-a19ab2fb"}
PERSON_POLICY = {
    "policyId": "pa100k-upar-person-v1",
    "seed": "mavi-s2c-person-v1",
    "blockSize": pa100k.BLOCK_SIZE,
    "selectionFraction": "0.1",
    "nearDuplicate": {"hammingThreshold": 4, "maxPairs": 10000, "bucketCap": 2048},
}
SMOKE = {"seed": "mavi-s2c-person-smoke-v1", "perSplit": {"train": 1600, "val": 200, "test": 200}}


def load_person_mappings() -> dict[str, dict]:
    mappings = {}
    for mapping_id in PERSON_MAPPINGS:
        document = parse_mapping(json.loads((MAPPINGS_DIR / f"{mapping_id}.json").read_text(encoding="utf-8")))
        require(document["mappingId"] == mapping_id, f"still_dataset_mapping_id:{mapping_id}")
        mappings[mapping_id] = document
    return mappings


def selection_blocks(train_blocks: list[str], policy: dict) -> set[str]:
    """The seeded ``selectionFraction`` of training allocation groups, rounded up."""
    count = math.ceil(len(train_blocks) * float(policy["selectionFraction"]))
    ranked = sorted(train_blocks, key=lambda b: (hash_rank(policy["seed"], "selection-block", b), b))
    return set(ranked[:count])


def assign_roles(rows: list[dict], policy: dict) -> dict[str, str]:
    """Role by member path, from the official split and the allocation groups (full release)."""
    train_blocks = sorted({r["group"]["id"] for r in rows if r["sourceSplit"] == "train"})
    chosen = selection_blocks(train_blocks, policy)
    roles = {}
    for row in rows:
        if row["sourceSplit"] == "train":
            roles[row["memberPath"]] = "selection" if row["group"]["id"] in chosen else "training"
        else:
            roles[row["memberPath"]] = SPLIT_ROLE[row["sourceSplit"]]
    return roles


def smoke_subset(rows: list[dict]) -> list[dict]:
    """A deterministic per-split sample (``SMOKE``). Roles still come from the full-release rule."""
    picked = []
    for split, size in SMOKE["perSplit"].items():
        candidates = sorted((r for r in rows if r["sourceSplit"] == split), key=lambda r: (hash_rank(SMOKE["seed"], split, r["memberPath"]), r["memberPath"]))
        require(len(candidates) >= size, f"still_dataset_smoke_too_small:{split}")
        picked += candidates[:size]
    return sorted(picked, key=lambda r: r["memberPath"])


def _resolve_exact(copies: list[dict]) -> tuple[dict | None, list[dict], str | None]:
    """One image (one SHA-256) seen under several members: plan §6, rules in order.

    Returns ``(kept, dropped, conflict)``. ``conflict`` names the roles when two or more of
    development, selection and regression hold copies and no benchmark copy exists; the
    caller refuses the build. Rules: within a role keep the lowest member path; training
    copies lose to any evaluation copy; a benchmark copy is kept over other evaluation
    copies."""
    copies = sorted(copies, key=lambda c: (c["role"], c["memberPath"]))
    roles = {c["role"] for c in copies}
    evaluation = roles & set(EVALUATION_ROLES)
    if "benchmark" in evaluation:
        winner_role = "benchmark"
    elif len(evaluation) > 1:
        return None, [], ",".join(sorted(evaluation))
    elif evaluation:
        winner_role = next(iter(evaluation))
    else:
        winner_role = "training"
    keep = min((c for c in copies if c["role"] == winner_role), key=lambda c: c["memberPath"])
    return keep, [c for c in copies if c is not keep], None


def _near_report(kept: list[dict], fingerprints: dict[str, int], policy: dict) -> dict:
    rules = policy["nearDuplicate"]
    pairs, degenerate = pigeonhole_pairs(fingerprints, rules["hammingThreshold"], None, rules["bucketCap"])
    role = {s["sampleId"]: s["role"] for s in kept}
    ordered = sorted(({"a": a, "b": b, "distance": d, "crossRole": role[a] != role[b], "roles": sorted((role[a], role[b]))} for a, b, d in pairs),
                     key=lambda p: (not p["crossRole"], p["distance"], p["a"], p["b"]))
    return {
        "schemaVersion": NEAR_REPORT_SCHEMA,
        "screeningOnly": "dHash candidates are reported for review and never remove a sample",
        "hammingThreshold": rules["hammingThreshold"],
        "totals": {"pairs": len(ordered), "crossRolePairs": sum(p["crossRole"] for p in ordered), "degenerateBuckets": len(degenerate)},
        "pairs": ordered[: rules["maxPairs"]],
        "truncated": len(ordered) > rules["maxPairs"],
        "degenerateBuckets": degenerate,
    }


def build_person_manifest(pa_release: dict, pa_root: Path, upar_release: dict, upar_root: Path, smoke: bool = False,
                          policy: dict = PERSON_POLICY) -> tuple[dict, dict]:
    """Build the person still-dataset manifest and its near-duplicate report.

    Refuses when release files fail verification, the releases are not the ones the
    mappings name, UPAR names an image PA-100K does not contain, an image member is
    missing from the archive, an exact duplicate cannot be resolved by the role rule, or
    no sample is authorised."""
    for release, root in ((pa_release, pa_root), (upar_release, upar_root)):
        problems = verify_release_files(release, root)
        require(not problems, f"still_dataset_release_files:{release['releaseId']}:{'; '.join(problems)}")
    mappings = load_person_mappings()
    releases = {pa_release["releaseId"]: pa_release, upar_release["releaseId"]: upar_release}
    require(set(PERSON_MAPPINGS.values()) == set(releases), "still_dataset_release_ids")

    rows = pa100k.read_rows(pa_root)
    upar_rows, upar_counts = upar.read_rows(upar_root)
    split_of = {r["memberPath"]: r["sourceSplit"] for r in rows}
    stray = sorted(set(upar_rows) - set(split_of))
    require(not stray, f"still_dataset_upar_image_not_in_pa100k:{stray[0] if stray else ''}")
    roles = assign_roles(rows, policy)
    selected = smoke_subset(rows) if smoke else rows

    label_release_of = {rule["attributeType"]: PERSON_MAPPINGS[m] for m, doc in mappings.items() for rule in doc["attributes"]}
    authorised: dict[tuple[str, str], list[str]] = {}

    def release_blockers(release_id: str, purpose: str, member: str | None) -> list[str]:
        if member is not None:
            return authorise_release_use(releases[release_id], [purpose], (), member)
        key = (release_id, purpose)
        if key not in authorised:
            authorised[key] = authorise_release_use(releases[release_id], [purpose])
        return authorised[key]

    candidates, refused, fingerprints = [], [], {}
    with zipfile.ZipFile(Path(pa_root) / pa100k.IMAGE_ARCHIVE) as archive:
        members = set(archive.namelist())
        images = {m for m in members if m.startswith(pa100k.IMAGE_PREFIX) and not m.endswith("/")}
        annotated = {r["memberPath"] for r in rows}
        require(images == annotated, f"still_dataset_archive_differs_from_annotation:{len(images - annotated)}-unlisted:{len(annotated - images)}-missing")
        for row in selected:
            member = row["memberPath"]
            require(member in members, f"still_dataset_image_missing:{member}")
            role = roles[member]
            purpose = ROLE_PURPOSE[role]
            attributes = {}
            for mapping_id, mapping in mappings.items():
                label_release = PERSON_MAPPINGS[mapping_id]
                if mapping["adapter"] == "pa100k":
                    mapped = apply_mapping(mapping, row["labels"])
                else:
                    source = upar_rows.get(member)
                    mapped = apply_mapping(mapping, source["labels"]) if source else {r["attributeType"]: None for r in mapping["attributes"]}
                for attribute, result in mapped.items():
                    attributes[attribute] = {"truth": "missing" if result is None else "present",
                                             "outcome": None if result is None else result["outcome"],
                                             "value": None if result is None else result["value"],
                                             "semantics": mapping_rule_semantics(mapping, attribute),
                                             "labelReleaseId": label_release, "mappingId": mapping_id}
            blockers = [f"{pa_release['releaseId']}:{b}" for b in release_blockers(pa_release["releaseId"], purpose, member)]
            for attribute, entry in attributes.items():
                if entry["truth"] == "present" and label_release_of[attribute] != pa_release["releaseId"]:
                    blockers += [f"{label_release_of[attribute]}:{b}" for b in release_blockers(label_release_of[attribute], purpose, None)]
            if blockers:
                refused.append({"memberPath": member, "role": role, "blockers": sorted(set(blockers))})
                continue
            data = archive.read(member)
            sample_id = hashlib.sha256(data).hexdigest()
            fingerprints.setdefault(sample_id, dhash64(data))
            candidates.append({"sampleId": sample_id, "releaseId": pa_release["releaseId"], "memberPath": member,
                               "sourceSplit": row["sourceSplit"], "group": row["group"], "role": role, "attributes": attributes})

    by_sha: dict[str, list[dict]] = defaultdict(list)
    for sample in candidates:
        by_sha[sample["sampleId"]].append(sample)
    kept, drops, conflicts = [], [], []
    for sample_id in sorted(by_sha):
        keep, dropped, conflict = _resolve_exact(by_sha[sample_id])
        if conflict:
            conflicts.append(f"{sample_id}:{conflict}")
            continue
        kept.append(keep)
        drops += [{"sampleId": sample_id, "memberPath": d["memberPath"], "role": d["role"], "keptMemberPath": keep["memberPath"], "keptRole": keep["role"]} for d in dropped]
    require(not conflicts, f"duplicate_role_conflict:{';'.join(conflicts[:5])}")
    require(kept, "still_dataset_empty_no_authorised_sample")

    report = _near_report(kept, {s["sampleId"]: fingerprints[s["sampleId"]] for s in kept}, policy)
    manifest = {
        "schemaVersion": STILL_SCHEMA,
        "datasetId": "pa100k-upar-person",
        "policy": policy,
        "smoke": SMOKE if smoke else None,
        "roleToPurpose": ROLE_PURPOSE,
        "releases": [{"releaseId": rid, "releaseSha256": release_sha256(releases[rid])} for rid in sorted(releases)],
        "mappings": [{"mappingId": mid, "mappingSha256": mapping_sha256(mappings[mid]), "labelReleaseId": PERSON_MAPPINGS[mid]} for mid in sorted(mappings)],
        "sourceCoverage": {"pa100kRows": {s: sum(1 for r in rows if r["sourceSplit"] == s) for s in pa100k.SPLITS},
                           "uparRowsBySource": upar_counts,
                           "uparPa100kRowsByOfficialSplit": {s: sum(1 for m in upar_rows if split_of[m] == s) for s in pa100k.SPLITS}},
        "refusedSamples": sorted(refused, key=lambda r: r["memberPath"]),
        "exactDuplicateDrops": drops,
        "nearDuplicateReport": {"sha256": sha256_hex(canonical_json(report)), "totals": report["totals"]},
        "counts": _counts(kept),
        "samples": sorted(kept, key=lambda s: s["sampleId"]),
    }
    parse_still_dataset(manifest)
    return manifest, report


def mapping_rule_semantics(mapping: dict, attribute: str) -> str:
    return next(r["semantics"] for r in mapping["attributes"] if r["attributeType"] == attribute)


def _counts(samples: list[dict]) -> dict:
    roles = defaultdict(int)
    truth = defaultdict(lambda: defaultdict(int))
    for s in samples:
        roles[s["role"]] += 1
        for attribute, entry in s["attributes"].items():
            truth[attribute][entry["truth"] if entry["truth"] == "missing" else (entry["outcome"] + ":" + str(entry["value"]))] += 1
    return {"samples": len(samples), "roles": dict(sorted(roles.items())),
            "attributes": {a: dict(sorted(v.items())) for a, v in sorted(truth.items())}}


def parse_still_dataset(document: dict) -> dict:
    """Structural check of a still-dataset manifest; refuses unknown roles (so no frozen role)."""
    code = "still_dataset_invalid"
    require(isinstance(document, dict) and document.get("schemaVersion") == STILL_SCHEMA, f"{code}:schema")
    require(document.get("roleToPurpose") == ROLE_PURPOSE, f"{code}:role_to_purpose")
    release_ids = {r["releaseId"] for r in document["releases"]}
    mapping_ids = {m["mappingId"] for m in document["mappings"]}
    for entry in document["releases"]:
        require_sha256(entry["releaseSha256"], f"{code}:release_sha256")
    for entry in document["mappings"]:
        require_sha256(entry["mappingSha256"], f"{code}:mapping_sha256")
    ids = [s["sampleId"] for s in document["samples"]]
    require(ids == sorted(set(ids)), f"{code}:samples_not_sorted_unique")
    for sample in document["samples"]:
        require_sha256(sample["sampleId"], f"{code}:sample_id")
        require(sample["role"] in ROLE_PURPOSE, f"{code}:role:{sample['role']}")
        require(sample["releaseId"] in release_ids, f"{code}:sample_release")
        require(sample["group"]["kind"] in GROUP_KINDS, f"{code}:group_kind")
        for attribute, entry in sample["attributes"].items():
            require(entry["truth"] in ("missing", "present"), f"{code}:truth:{attribute}")
            require((entry["truth"] == "missing") == (entry["outcome"] is None), f"{code}:outcome:{attribute}")
            require(entry["semantics"] in ("proxy", "source-native"), f"{code}:semantics:{attribute}")
            require(entry["labelReleaseId"] in release_ids and entry["mappingId"] in mapping_ids, f"{code}:lineage:{attribute}")
    return document


def still_dataset_sha256(manifest: dict) -> str:
    return sha256_hex(canonical_json(manifest))


__all__ = ["CorpusError", "PERSON_POLICY", "ROLE_PURPOSE", "STILL_SCHEMA", "assign_roles", "build_person_manifest",
           "load_person_mappings", "parse_still_dataset", "selection_blocks", "smoke_subset", "still_dataset_sha256"]
