"""External dataset release records and intended-use authorisation (public-data slice §3).

A **release record** (``mavi-attribute-dataset-release-v1``) pins one published dataset
release:
- its official source and pinned retrieval;
- the licence codes, together with the SHA-256 of the retained licence statement;
- every file the operator placed in the controlled store, by size and SHA-256;
- members excluded on review;
- the reusable #138-shaped determination that covers every member;
- known exposure, for example candidates reported trained on it.

There is no network code here: files are placed by the operator and verified by hash.

Three separate steps, never merged:
1. ``parse_release`` checks **structure**. An empty or denied review parses.
2. ``authorise_release_use`` decides whether the determination **authorises a use**:
   - affirmative rights and privacy reviews;
   - licence and purpose coverage;
   - R-5's ruling where the licence needs it;
   - every rights-inventory **operation** the purposes exercise (``PURPOSE_OPERATIONS``);
   - the member is not excluded.

   A purpose never implies an operation.
3. ``artefact_disposition`` decides whether an **artefact** (head, calibration, threshold,
   output mapping) may be delivered on a route. It checks every release in its actual
   lineage for the operations that produced it and the route's own operations
   (``ROUTE_OPERATIONS``: running operationally, and redistributing derived weights for an
   offline kit). This is an engineering disposition, not a legal conclusion; R-5
   interprets the inventory. Wiring it into training manifests and packs is S2c.6.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from attributes.corpus.canonical import (
    CorpusError,
    canonical_json,
    require,
    require_date,
    require_free_text,
    require_int,
    require_keys,
    require_sha256,
    require_token,
    sha256_hex,
)
from attributes.corpus.provenance import PUBLIC, SOURCE_ORIGINS, parse_purposes
from source_acquisition.acquire import git_worktree_ancestor
from source_acquisition.admission import (
    OPEN_LICENCES,
    determination_blockers,
    licence_class,
    normalise_licence,
    parse_determination,
    refuse_local_paths,
)

RELEASE_SCHEMA = "mavi-attribute-dataset-release-v1"

# The rights inventory a dataset determination records, for the declared non-commercial
# profile (MSR method §5). The last two belong to an artefact's delivery route.
INVENTORY_OPERATIONS = ("create-derivatives", "evaluate", "redistribute-derived-weights", "run-operationally", "train")
INVENTORY_STATUSES = ("granted", "not-granted", "not-stated", "pending-r5")
DATASET_USE_OPERATIONS = ("create-derivatives", "evaluate", "train")

# Operations each purpose exercises (plan §3.2). A purpose missing here is refused, not guessed.
PURPOSE_OPERATIONS = {
    "benchmarking": ("evaluate",),
    "selection": ("evaluate",),
    "regression-challenge": ("evaluate",),
    "development": ("evaluate",),
    "tuning": ("create-derivatives", "evaluate"),
    "training": ("create-derivatives", "train"),
}

# Delivery routes (parent plan U10): local acquisition on the host, or inclusion in an
# offline kit, which is what exercises redistribution.
ROUTE_OPERATIONS = {
    "local-acquisition": ("run-operationally",),
    "offline-kit": ("redistribute-derived-weights", "run-operationally"),
}
DISPOSITIONS = ("CLEARED", "NOT_COVERED", "PENDING_R5")

_MEMBER_PATH_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")


class ReleaseError(Exception):
    pass


def _member_path(value: object, code: str) -> str:
    require(isinstance(value, str) and _MEMBER_PATH_RE.fullmatch(value) is not None
            and not any(part in (".", "..") for part in value.split("/")), f"{code}:path")
    return value


def _https(value: object, code: str) -> str:
    require(isinstance(value, str) and value.startswith("https://") and len(value) <= 500, code)
    return value


def _inventory(determination: dict, code: str) -> None:
    inventory = (determination.get("rights") or {}).get("inventory")
    require(isinstance(inventory, dict), f"{code}:inventory")
    require(set(inventory) == set(INVENTORY_OPERATIONS), f"{code}:inventory_operations")
    require(all(v in INVENTORY_STATUSES for v in inventory.values()), f"{code}:inventory_status")


def parse_release(document: object) -> dict:
    """Structure of a release record. Refuses malformed records whole; authorises nothing."""
    code = "dataset_release_invalid"
    require(isinstance(document, dict), code)
    require_keys(document, code, ("schemaVersion", "releaseId", "name", "version", "origin", "officialUrl", "pinnedSource",
                                  "licence", "files", "excludedMembers", "determination", "knownExposure"))
    require(document["schemaVersion"] == RELEASE_SCHEMA, f"{code}:schema")
    refuse_local_paths(document)
    require_token(document["releaseId"], f"{code}:release_id")
    require(isinstance(document["name"], str) and document["name"].strip() != "", f"{code}:name")
    require_free_text(document["name"], f"{code}:name", 200)
    require(isinstance(document["version"], str) and document["version"].strip() != "", f"{code}:version")
    require_free_text(document["version"], f"{code}:version", 200)
    # v1 records public releases only; protected footage has its own (commissioned) path.
    require(document["origin"] in SOURCE_ORIGINS and document["origin"] == PUBLIC, f"{code}:origin")
    _https(document["officialUrl"], f"{code}:official_url")

    pinned = document["pinnedSource"]
    require(isinstance(pinned, dict), f"{code}:pinned_source")
    require_keys(pinned, f"{code}:pinned_source", ("kind", "reference", "retrievedOn"))
    require_token(pinned["kind"], f"{code}:pinned_source")
    require(isinstance(pinned["reference"], str) and pinned["reference"].strip() != "", f"{code}:pinned_source")
    require_date(pinned["retrievedOn"], f"{code}:pinned_source")

    licence = document["licence"]
    require(isinstance(licence, dict), f"{code}:licence")
    require_keys(licence, f"{code}:licence", ("codes", "url", "textSha256"))
    codes = licence["codes"]
    require(isinstance(codes, list) and codes and all(isinstance(c, str) for c in codes), f"{code}:licence_codes")  # before set()
    require(codes == sorted(set(codes)) and all(normalise_licence(c) == c for c in codes), f"{code}:licence_codes")
    if licence["url"] is not None:
        _https(licence["url"], f"{code}:licence_url")
    require_sha256(licence["textSha256"], f"{code}:licence_text")

    files = document["files"]
    require(isinstance(files, list) and files, f"{code}:files")
    for entry in files:
        require(isinstance(entry, dict), f"{code}:files")
        require_keys(entry, f"{code}:files", ("path", "sizeBytes", "sha256"))
        _member_path(entry["path"], f"{code}:files")
        require_int(entry["sizeBytes"], f"{code}:files:size", 0)
        require_sha256(entry["sha256"], f"{code}:files:sha256")
    paths = [f["path"] for f in files]
    require(paths == sorted(set(paths)), f"{code}:files_not_sorted_unique")

    excluded = document["excludedMembers"]
    require(isinstance(excluded, list), f"{code}:excluded")
    for entry in excluded:
        require(isinstance(entry, dict), f"{code}:excluded")
        require_keys(entry, f"{code}:excluded", ("path", "reason"))
        _member_path(entry["path"], f"{code}:excluded")
        require(isinstance(entry["reason"], str) and entry["reason"].strip() != "", f"{code}:excluded_reason")
        require_free_text(entry["reason"], f"{code}:excluded_reason", 500)
    excluded_paths = [e["path"] for e in excluded]
    require(excluded_paths == sorted(set(excluded_paths)), f"{code}:excluded_not_sorted_unique")

    if document["determination"] is not None:
        parse_determination(document["determination"], f"{code}:determination")
        _inventory(document["determination"], f"{code}:determination")

    exposure = document["knownExposure"]
    require(isinstance(exposure, list), f"{code}:exposure")
    for entry in exposure:
        require(isinstance(entry, dict), f"{code}:exposure")
        require_keys(entry, f"{code}:exposure", ("subject", "evidence"))
        require_free_text(entry["subject"], f"{code}:exposure", 200)
        require_free_text(entry["evidence"], f"{code}:exposure", 1000)
    # Like every other list here: one canonical order, so the release identity is stable.
    keys = [(e["subject"], e["evidence"]) for e in exposure]
    require(keys == sorted(set(keys)), f"{code}:exposure_not_sorted_unique")
    return document


def release_sha256(release: dict) -> str:
    return sha256_hex(canonical_json(release))


def _r5_required(codes: list[str]) -> bool:
    """Share-alike, NC/ND, unrecognised or bespoke terms need R-5's interpretation."""
    return any(bool(OPEN_LICENCES.get(c, (False,))[0]) or licence_class(c) != "OPEN" for c in codes)


def authorise_release_use(release: dict, purposes, operations=(), member: str | None = None) -> list[str]:
    """Blockers that stop this release, or one member of it, being used for these purposes.

    ``operations`` names any operation exercised beyond those the purposes require. Without a
    ``member``, the question is whole-release use, which is blocked while any member is
    excluded. Every
    required operation must be ``granted`` in the determination's rights inventory:
    ``not-granted`` blocks; ``not-stated`` and ``pending-r5`` block pending R-5's
    interpretation. An empty result authorises the use."""
    purposes = list(purposes)
    require(all(isinstance(p, str) for p in purposes), "dataset_use:purposes")
    requested = parse_purposes(sorted(set(purposes)), "dataset_use", PUBLIC)
    for purpose in requested:
        require(purpose in PURPOSE_OPERATIONS, f"dataset_purpose_has_no_operations:{purpose}")
    extra = list(operations)
    for operation in extra:
        require(operation in DATASET_USE_OPERATIONS, f"dataset_operation_not_a_use_operation:{operation}")
    blockers = []
    excluded = {e["path"] for e in release["excludedMembers"]}
    if member is not None:
        _member_path(member, "dataset_use_member")
        if member in excluded:
            blockers.append(f"member-excluded:{member}")
    elif excluded:
        # Whole-release use would include the excluded members: authorise member by member.
        blockers.append(f"release-has-excluded-members:{len(excluded)}")
    determination = release["determination"]
    if determination is None:
        return sorted(blockers + ["determination-missing"])
    codes = release["licence"]["codes"]
    blockers += determination_blockers(determination, codes, requested, _r5_required(codes))
    required = sorted({op for p in requested for op in PURPOSE_OPERATIONS[p]} | set(extra))
    inventory = determination["rights"]["inventory"]
    for operation in required:
        status = inventory.get(operation)
        if status == "granted":
            continue
        blockers.append(f"rights-operation-not-granted:{operation}" if status == "not-granted" else f"rights-operation-pending-r5:{operation}")
    return sorted(set(blockers))


def artefact_disposition(lineage: list[dict], operations, route: str) -> dict:
    """Disposition of one artefact for one delivery route, from its **actual** lineage.

    ``lineage`` holds the parsed release records whose images or labels the producing step
    read; nothing else in a wider manifest counts. ``operations`` are the dataset operations
    that produced it (for example ``train`` and ``create-derivatives``). Every release must
    have an affirmative determination and grant those operations plus the route's.
    ``NOT_COVERED`` when any is ``not-granted`` or privacy is denied; ``PENDING_R5`` for any
    other gap (missing determination or review, unresolved right, missing R-5 ruling);
    ``CLEARED`` otherwise. Blockers are prefixed with the release id."""
    require(route in ROUTE_OPERATIONS, f"artefact_route_unknown:{route}")
    produced = list(operations)
    for operation in produced:
        require(operation in DATASET_USE_OPERATIONS, f"dataset_operation_not_a_use_operation:{operation}")
    require(isinstance(lineage, list), "artefact_lineage")
    ids = [r["releaseId"] for r in lineage]
    require(len(ids) == len(set(ids)), "artefact_lineage_duplicate")
    required = sorted(set(produced) | set(ROUTE_OPERATIONS[route]))
    blockers, denied = [], False
    for release in sorted(lineage, key=lambda r: r["releaseId"]):
        prefix = release["releaseId"]
        determination = release["determination"]
        if determination is None:
            blockers.append(f"{prefix}:determination-missing")
            continue
        codes = release["licence"]["codes"]
        for blocker in determination_blockers(determination, codes, (), _r5_required(codes)):
            denied = denied or blocker == "privacy-denied"
            blockers.append(f"{prefix}:{blocker}")
        inventory = determination["rights"]["inventory"]
        for operation in required:
            status = inventory.get(operation)
            if status == "granted":
                continue
            if status == "not-granted":
                denied = True
                blockers.append(f"{prefix}:rights-operation-not-granted:{operation}")
            else:
                blockers.append(f"{prefix}:rights-operation-pending-r5:{operation}")
    disposition = "CLEARED" if not blockers else ("NOT_COVERED" if denied else "PENDING_R5")
    return {"disposition": disposition, "blockers": sorted(blockers)}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_release_files(release: dict, root: Path) -> list[str]:
    """Check every operator-placed file under ``root`` against the record. Returns problems.

    The store must be outside every Git worktree; a file may not resolve outside the store."""
    resolved = Path(root).expanduser().resolve()
    worktree = git_worktree_ancestor(resolved)
    if worktree is not None:
        raise ReleaseError(f"release store is inside the Git worktree {worktree}; refusing")
    problems = []
    for entry in release["files"]:
        target = (resolved / entry["path"]).resolve()
        if resolved not in target.parents:
            problems.append(f"{entry['path']}: escapes the store")
            continue
        if not target.is_file():
            problems.append(f"{entry['path']}: missing")
            continue
        if target.stat().st_size != entry["sizeBytes"]:
            problems.append(f"{entry['path']}: size differs")
            continue
        if _sha256_file(target) != entry["sha256"]:
            problems.append(f"{entry['path']}: sha256 differs")
    return problems


__all__ = [
    "CorpusError", "DATASET_USE_OPERATIONS", "DISPOSITIONS", "ROUTE_OPERATIONS", "artefact_disposition", "INVENTORY_OPERATIONS", "INVENTORY_STATUSES", "PURPOSE_OPERATIONS", "RELEASE_SCHEMA",
    "ReleaseError", "authorise_release_use", "parse_release", "release_sha256", "verify_release_files",
]
