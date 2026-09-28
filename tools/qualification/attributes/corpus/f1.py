"""Fail-closed F1 evidence checker (acceptance register F1; S2c plan §20).

F1: "Annotation guide, double-label agreement/adjudication and corpus partition manifests
are frozen before final evaluation." The record names the retained evidence by hash. The
checker computes the verdict; a record may never *claim* more than the checker computes,
and synthetic fixtures can never produce PASS. Missing external inputs keep F1 OPEN.
"""

from __future__ import annotations

from pathlib import Path

from .canonical import SHA256_RE, CorpusError, lf_normalised_sha256, read_json, require

RECORD_SCHEMA = "mavi-s2c-f1-evidence-record-v1"
REPO = Path(__file__).resolve().parents[4]


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def f1_verdict(record: dict, repo: Path = REPO) -> dict:
    require(record.get("schemaVersion") == RECORD_SCHEMA, "f1_record_schema")
    missing: list[str] = []

    def need(condition: bool, item: str) -> None:
        if not condition:
            missing.append(item)

    guide = record["annotationGuide"]
    guide_path = repo / guide["path"]
    need(guide_path.is_file(), "annotation guide file")
    need(_sha(guide["frozenSha256"]), "annotation guide frozen SHA-256")
    if guide_path.is_file() and _sha(guide["frozenSha256"]):
        need(lf_normalised_sha256(guide_path) == guide["frozenSha256"], "annotation guide unchanged since freeze")
    need(_sha(record["attributeTask"]["frozenSha256"]), "frozen attribute task SHA-256")
    corpus = record["corpus"]
    need(corpus["corpusKind"] == "operational", "operational corpus (synthetic fixtures never count)")
    for key in ("corpusManifestSha256", "partitionManifestSha256", "recurrenceAuditSha256", "duplicateAuditSha256"):
        need(_sha(corpus[key]), f"corpus.{key}")
    labelling = record["labelling"]
    for key in ("pilotReportSha256", "mainAgreementReportSha256", "groundTruthSha256", "annotationLedgerHead"):
        need(_sha(labelling[key]), f"labelling.{key}")
    need(isinstance(labelling["adjudicationSha256s"], list) and all(_sha(s) for s in labelling["adjudicationSha256s"]), "labelling.adjudicationSha256s (may be empty only if no conflict arose)")
    annotators = labelling["annotators"]
    need(isinstance(annotators["count"], int) and annotators["count"] >= 2, "at least two annotators")
    need(isinstance(annotators["independentCount"], int) and annotators["independentCount"] >= 1, "at least one independent annotator")
    seal = record["seal"]
    need(_sha(seal["sealSha256"]) and _sha(seal["accessLogHead"]), "frozen-test seal and access-log head")
    need(seal["status"] == "intact", "frozen-test seal intact")
    support = record["support"]
    per_partition = support["camerasPerPartition"]
    need(isinstance(per_partition, dict) and set(per_partition) == {"training", "tuning", "selection", "frozen-test"} and all(isinstance(v, int) and v >= 3 for v in per_partition.values()), "at least three cameras in every partition")
    need(isinstance(support["unseenFrozenCameras"], int) and support["unseenFrozenCameras"] >= 1, "a frozen-test camera unseen elsewhere")
    need(isinstance(record["limitations"], list), "limitations list (may be empty)")
    need(record.get("custodian") is not None, "named Corpus Custodian (pseudonym)")
    computed = "PASS" if not missing else "OPEN"
    claimed = record.get("claimedStatus")
    require(claimed in ("OPEN", "PASS"), "f1_claimed_status_invalid")
    if claimed == "PASS" and computed != "PASS":
        raise CorpusError("f1_claims_pass_without_evidence:" + "; ".join(missing))
    return {"computed": computed, "claimed": claimed, "missing": missing}


def check_file(path: Path) -> dict:
    return f1_verdict(read_json(path))
