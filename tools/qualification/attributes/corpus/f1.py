"""Fail-closed F1 evidence checker (acceptance register F1; S2c plan §20).

F1: "Annotation guide, double-label agreement/adjudication and corpus partition manifests
are frozen before final evaluation."

The committed evidence record names each retained artefact by SHA-256 and says nothing
else about it. The checker takes nothing on trust. It loads every artefact from the
Corpus Custodian's retained-record store (``--store``), which is a directory outside Git,
and re-derives each identity. It then re-verifies the chain:

* corpus manifest → recurrence and duplicate audits → partition (re-derived with
  ``verify_partition``);
* pilot report → frozen task (``derivedFrom``);
* main agreement report: its hash, evaluation-partition scope, same corpus/partition/task,
  every batch registered in the annotation ledger, and annotator independence as the
  ledger registered it;
* adjudications recorded in the ledger;
* sealed evaluation view, bound to the seal (``load_evaluation_view``);
* seal → partition, evaluation view and ledger head;
* access log, which must start with this seal, extend the recorded head and show no
  improper access;
* camera support recomputed from the partition.

Without a store, or with any artefact missing, the verdict is OPEN. A record may never
claim more than the checker computes, and synthetic fixtures can never produce PASS.
"""

from __future__ import annotations

from pathlib import Path

from .agreement import verify_report_hash
from .annotation import AnnotationLedger, load_evaluation_view
from .canonical import SHA256_RE, CorpusError, document_sha256, lf_normalised_sha256, read_json, require
from .duplicates import parse_duplicate_audit
from .frozen import seal_status
from .ledger import Ledger
from .manifest import parse_corpus
from .partition import PARTITIONS, verify_partition
from .recurrence import parse_recurrence
from .task import parse_task

RECORD_SCHEMA = "mavi-s2c-f1-evidence-record-v1"
REPO = Path(__file__).resolve().parents[4]
ANNOTATION_LEDGER = "annotation-ledger.jsonl"
ACCESS_LOG = "frozen-access-log.jsonl"
MINIMUM_CAMERAS_PER_PARTITION = 3


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


class _Store:
    """Hash-addressed: ``<sha256>.json`` per document, plus the two ledgers by name."""

    def __init__(self, root: Path) -> None:
        require(root.is_dir(), "f1_store_missing")
        self.root = root

    def raw(self, sha256: str, what: str) -> dict:
        path = self.root / f"{sha256}.json"
        require(path.is_file(), f"f1_record_missing:{what}")
        return read_json(path)

    def load(self, sha256: str, what: str) -> dict:
        document = self.raw(sha256, what)
        require(document_sha256(document) == sha256, f"f1_record_hash_mismatch:{what}")
        return document

    def ledger(self, name: str, kind: type[Ledger] = Ledger) -> Ledger:
        path = self.root / name
        require(path.is_file(), f"f1_ledger_missing:{name}")
        return kind(path)


def _verify_chain(record: dict, store: _Store, missing: list[str]) -> None:
    refs, labelling, seal_ref = record["corpus"], record["labelling"], record["seal"]
    # Corpus and audits are identified by their normalised hashes (producer order is free).
    corpus = parse_corpus(store.raw(refs["corpusManifestSha256"], "corpus manifest"))
    require(corpus.sha256 == refs["corpusManifestSha256"], "f1_record_hash_mismatch:corpus manifest")
    require(corpus.corpus_kind == refs["corpusKind"], "f1_corpus_kind_mismatch")
    recurrence_doc = store.raw(refs["recurrenceAuditSha256"], "recurrence audit")
    recurrence_sha, recurrence_links = parse_recurrence(recurrence_doc, corpus)
    require(recurrence_sha == refs["recurrenceAuditSha256"], "f1_record_hash_mismatch:recurrence audit")
    duplicate_sha, duplicate_links = parse_duplicate_audit(store.raw(refs["duplicateAuditSha256"], "duplicate audit"), corpus)
    require(duplicate_sha == refs["duplicateAuditSha256"], "f1_record_hash_mismatch:duplicate audit")
    partition = store.load(refs["partitionManifestSha256"], "partition manifest")
    partition_sha = refs["partitionManifestSha256"]
    verify_partition(corpus, partition, recurrence_links + duplicate_links, {"recurrence": recurrence_sha, "duplicate": duplicate_sha})
    if recurrence_doc.get("recallSample") is None:
        missing.append("recurrence audit recall sample")

    ledger = store.ledger(ANNOTATION_LEDGER, AnnotationLedger)
    ledger.require_extends(labelling["annotationLedgerHead"])
    registered = ledger.batch_hashes()
    annotators = ledger.annotators()

    pilot = store.load(labelling["pilotReportSha256"], "pilot report")
    require(pilot.get("schemaVersion") == "mavi-attribute-pilot-report-v1", "f1_pilot_report_schema")
    require(pilot["corpusKind"] == corpus.corpus_kind, "f1_pilot_report_corpus_kind")
    verify_report_hash(pilot["agreement"])
    require(pilot["agreement"]["phase"] == "pilot" and pilot["agreement"]["corpusManifestSha256"] == corpus.sha256, "f1_pilot_report_identity")
    require(set(pilot["agreement"]["batchSha256s"]) <= set(registered), "f1_pilot_batches_not_in_ledger")
    task = parse_task(store.load(record["attributeTask"]["frozenSha256"], "frozen attribute task"))
    require(task.status == "frozen", "f1_task_not_frozen")
    require(task.document["derivedFrom"]["pilotReportSha256"] == pilot["reportSha256"], "f1_task_not_derived_from_pilot")
    require(task.document["derivedFrom"]["candidateTaskSha256"] == pilot["taskSha256"], "f1_pilot_task_mismatch")

    main = store.load(labelling["mainAgreementReportSha256"], "main agreement report")
    verify_report_hash(main)
    require(main["phase"] == "main" and main["scope"] == "evaluation-partitions", "f1_main_report_scope")
    require((main["corpusManifestSha256"], main["partitionManifestSha256"], main["taskSha256"]) == (corpus.sha256, partition_sha, task.sha256), "f1_main_report_identity")
    require(set(main["batchSha256s"]) <= set(registered), "f1_main_batches_not_in_ledger")
    raters = {registered[b] for b in main["batchSha256s"]}
    independent = sorted(a for a in raters if annotators.get(a))
    require(main["annotators"]["count"] == len(raters) and main["annotators"]["independent"] == independent, "f1_main_report_annotators_disagree_with_ledger")
    if len(raters) < 2:
        missing.append("at least two annotators in main labelling")
    if not independent:
        missing.append("at least one annotator independent of model selection and tuning")
    for attribute in main["attributes"]:
        if attribute["doubleLabelledUnits"] == 0:
            missing.append(f"double-labelled units for {attribute['attributeType']}")
        elif attribute["doubleLabelledWithIndependentAnnotator"] < attribute["doubleLabelledUnits"]:
            missing.append(f"an independent annotator on every double-labelled unit of {attribute['attributeType']}")

    recorded = ledger.adjudication_hashes()
    for sha in labelling["adjudicationSha256s"]:
        store.load(sha, "adjudication")
        require(sha in recorded, "f1_adjudication_not_in_ledger")

    seal = store.load(seal_ref["sealSha256"], "frozen-test seal")
    require((seal["corpusManifestSha256"], seal["partitionManifestSha256"]) == (corpus.sha256, partition_sha), "f1_seal_identity")
    require(seal["supersedes"] is None or _sha(seal["supersedes"]["sealSha256"]), "f1_seal_supersedes")
    ledger.require_extends(seal["annotationLedgerHead"])
    truth = store.load(labelling["groundTruthSha256"], "sealed evaluation view")
    load_evaluation_view(truth, seal)
    require((truth["corpusManifestSha256"], truth["partitionManifestSha256"], truth["taskSha256"]) == (corpus.sha256, partition_sha, task.sha256), "f1_ground_truth_identity")
    ledger.require_extends(truth["annotationLedgerHead"])
    used = {row["adjudicationSha256"] for row in truth["rows"] if row["adjudicationSha256"]}
    require(used <= set(labelling["adjudicationSha256s"]), "f1_ground_truth_uses_unlisted_adjudication")

    log = store.ledger(ACCESS_LOG)
    require(bool(log.entries) and log.entries[0]["kind"] == "seal-created" and log.entries[0]["payload"]["sealSha256"] == seal_ref["sealSha256"], "f1_access_log_not_bound_to_seal")
    log.require_extends(seal_ref["accessLogHead"])
    if seal_status(log, seal)["status"] != "intact":
        missing.append("frozen-test seal intact (the access log records an improper access)")

    checks = partition["checks"]
    for partition_name in PARTITIONS:
        if checks["cameraCounts"][partition_name] < MINIMUM_CAMERAS_PER_PARTITION:
            missing.append(f"at least {MINIMUM_CAMERAS_PER_PARTITION} cameras in {partition_name}")
    if not checks["unseenFrozenCameras"]:
        missing.append("a frozen-test camera unseen in every other partition")
    require(set(checks["limitations"]) <= set(record["limitations"]), "f1_record_omits_partition_limitations")


def f1_verdict(record: dict, repo: Path = REPO, store: Path | None = None) -> dict:
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
    need(record["corpus"]["corpusKind"] == "operational", "operational corpus (synthetic fixtures never count)")
    need(record.get("custodian") is not None, "named Corpus Custodian (pseudonym)")
    need(isinstance(record["limitations"], list), "limitations list (may be empty)")
    labelling = record["labelling"]
    references = [
        record["attributeTask"]["frozenSha256"],
        *(record["corpus"][k] for k in ("corpusManifestSha256", "partitionManifestSha256", "recurrenceAuditSha256", "duplicateAuditSha256")),
        *(labelling[k] for k in ("pilotReportSha256", "mainAgreementReportSha256", "groundTruthSha256", "annotationLedgerHead")),
        record["seal"]["sealSha256"],
        record["seal"]["accessLogHead"],
    ]
    require(isinstance(labelling["adjudicationSha256s"], list) and all(_sha(s) for s in labelling["adjudicationSha256s"]), "f1_adjudication_list_invalid")
    if not all(_sha(r) for r in references):
        missing.append("retained evidence named by SHA-256 (frozen task, corpus, audits, partition, pilot, main agreement, sealed evaluation view, ledger head, seal, access-log head)")
    elif store is None:
        missing.append("retained-record store supplied for re-verification (--store)")
    elif isinstance(record["limitations"], list):
        _verify_chain(record, _Store(store), missing)
    computed = "PASS" if not missing else "OPEN"
    claimed = record.get("claimedStatus")
    require(claimed in ("OPEN", "PASS"), "f1_claimed_status_invalid")
    if claimed == "PASS" and computed != "PASS":
        raise CorpusError("f1_claims_pass_without_evidence:" + "; ".join(missing))
    return {"computed": computed, "claimed": claimed, "missing": missing}


def check_file(path: Path, repo: Path = REPO, store: Path | None = None) -> dict:
    return f1_verdict(read_json(path), repo, store)
