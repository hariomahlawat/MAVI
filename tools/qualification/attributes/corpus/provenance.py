"""Source origin, approved purposes and exposure: one vocabulary for acquisition and corpus.

Owner decision C+ (``docs/qualification/stage2-s2c/s2c-owner-decisions-2026-10-01.md`` §8):
public material may be used for every non-frozen engineering purpose, and the frozen
qualification test is drawn only from protected (commissioned or owner-captured) footage
that has not been exposed to any other use.

Both ``source_acquisition`` (which never imports the corpus manifest, partitioning or
frozen code) and the corpus tooling import this module, so there is one definition of
the origins, the purposes and the frozen-eligibility rule. Pure functions only.
"""

from __future__ import annotations

from .canonical import require, require_keys, require_sha256, require_token

# public: published to the world (for example Wikimedia Commons). private: not published, but
# supplied by a third party under its own terms. commissioned: captured for MAVI by a party
# MAVI appointed. owner-captured: captured by the owner. Only the last two are protected.
PUBLIC, PRIVATE, COMMISSIONED, OWNER_CAPTURED = "public", "private", "commissioned", "owner-captured"
SOURCE_ORIGINS = (PUBLIC, PRIVATE, COMMISSIONED, OWNER_CAPTURED)
PROTECTED_ORIGINS = (COMMISSIONED, OWNER_CAPTURED)

FROZEN_QUALIFICATION = "frozen-qualification"
# Approved engineering purposes. None of them is the frozen qualification test.
ENGINEERING_PURPOSES = ("benchmarking", "development", "reference", "regression-challenge", "selection", "training", "tuning")
PURPOSES = tuple(sorted(ENGINEERING_PURPOSES + (FROZEN_QUALIFICATION,)))
# The only uses whose exposure the partitioner itself records (``partition_exposures``).
PARTITION_PURPOSES = ("selection", "training", "tuning")


def parse_purposes(value: object, code: str, origin: str) -> tuple[str, ...]:
    """A non-empty, sorted, duplicate-free list of known purposes.

    ``frozen-qualification`` is accepted only for a protected origin: public or private
    material can never be approved for the frozen test, whatever else is recorded. It may be
    combined only with partition purposes (training, tuning, selection), whose exposure the
    partitioner records; development, reference, benchmarking or challenge use happens
    outside the partitions, so footage approved for it is not a frozen candidate."""
    require(isinstance(value, list) and value and value == sorted(set(value)), f"{code}:purposes")
    require(all(p in PURPOSES for p in value), f"{code}:purpose_unknown")
    if FROZEN_QUALIFICATION in value:
        require(origin in PROTECTED_ORIGINS, f"{code}:frozen_qualification_requires_protected_origin")
        require(all(p in PARTITION_PURPOSES for p in value if p != FROZEN_QUALIFICATION), f"{code}:frozen_qualification_with_untracked_purpose")
    return tuple(value)


def parse_exposures(value: object, code: str) -> tuple[dict, ...]:
    """Earlier uses of the footage, each bound to the record that shows it (for example a
    partition manifest or an acquisition receipt). Sorted and duplicate-free."""
    require(isinstance(value, list), f"{code}:exposures")
    keys = []
    for item in value:
        require(isinstance(item, dict), f"{code}:exposure")
        require_keys(item, f"{code}:exposure", ("use", "recordSha256"))
        require_token(item["use"], f"{code}:exposure_use")
        require_sha256(item["recordSha256"], f"{code}:exposure_record")
        keys.append((item["use"], item["recordSha256"]))
    require(keys == sorted(set(keys)), f"{code}:exposures_not_sorted_unique")
    return tuple(value)


def parse_provenance(value: object, code: str) -> dict:
    """Source provenance carried by a corpus source.

    ``acquisitionReceiptSha256`` binds a public source to its acquisition receipt, which
    holds the provider, page revision and file hashes. The commissioned-capture workflow
    has no receipt yet, so protected origins may leave it null."""
    require(isinstance(value, dict), code)
    require_keys(value, code, ("origin", "approvedPurposes", "acquisitionReceiptSha256", "priorExposures"))
    origin = value["origin"]
    require(origin in SOURCE_ORIGINS, f"{code}:origin")
    parse_purposes(value["approvedPurposes"], code, origin)
    receipt = value["acquisitionReceiptSha256"]
    if origin == PUBLIC:
        require(receipt is not None, f"{code}:public_source_requires_receipt")
    if receipt is not None:
        require_sha256(receipt, f"{code}:receipt")
    parse_exposures(value["priorExposures"], code)
    return value


def frozen_blockers(provenance: dict | None, corpus_kind: str) -> list[str]:
    """Why footage with this provenance may not be in the frozen qualification test.

    This is the machine-checkable part of the ADR-015 §3 contract: an empty result is
    necessary for frozen use, never sufficient (chronology, capture evidence, rights,
    annotation and the seal stay separate gates). Empty only when the origin is protected, ``frozen-qualification`` is an approved
    purpose, and no earlier exposure is recorded. An operational source that declares no
    provenance is never eligible. Synthetic fixtures without provenance keep their
    pre-C+ behaviour: they are never corpus evidence."""
    if provenance is None:
        return [] if corpus_kind == "synthetic-fixture" else ["provenance-undeclared"]
    blockers = []
    if provenance["origin"] not in PROTECTED_ORIGINS:
        blockers.append(f"origin-not-protected:{provenance['origin']}")
    if FROZEN_QUALIFICATION not in provenance["approvedPurposes"]:
        blockers.append("frozen-qualification-not-approved")
    if provenance["priorExposures"]:
        blockers.append("previously-exposed")
    return blockers
