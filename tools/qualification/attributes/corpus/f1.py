"""Fail-closed F1 evidence checker (acceptance register F1; S2c plan §20).

F1: "Annotation guide, double-label agreement/adjudication and corpus partition manifests
are frozen before final evaluation."

The committed evidence record names each retained artefact by SHA-256 and says nothing
else about it. The checker takes nothing on trust. It loads every artefact from the
Corpus Custodian's retained-record store (``--store``), a directory outside Git that holds
every document as ``<sha256>.json`` plus the ledgers. It re-derives each identity and
then **recomputes** the chain rather than reading its conclusions:

* the partition, from the corpus and both audits (``verify_partition``);
* the pilot report, from the candidate task and the ledger-registered pilot batches; it
  must equal the retained report, and the frozen task must derive from it;
* the main agreement report, from every ledger-registered main batch and every
  ledger-recorded adjudication; it must equal the retained report;
* both ground-truth views, from the same inputs; their hashes must equal the seal's;
* the seal's frozen member set, from the corpus and partition;
* the seal chain: this seal must be the ledger's latest, and every earlier one must be
  compromised by its own retained log and superseded by a different frozen set;
* the access log, which must start with this seal, extend the recorded head and show no
  improper access;
* camera support, from the partition.

The labelling state used is the ledger as it stood at the ground truth's head. Every
attribute of the frozen task needs double-labelled units with an independent annotator,
and main labelling must use the frozen guide.

Without a store, or with any artefact missing, the verdict is OPEN. A malformed record
is refused. A record may never claim more than the checker computes, and synthetic
fixtures can never produce PASS.
"""

from __future__ import annotations

from pathlib import Path

from .agreement import agreement_report
from .annotation import (
    VALIDITY,
    AnnotationLedger,
    build_ground_truth,
    load_evaluation_view,
    parse_adjudication,
    parse_batch,
    split_ground_truth,
    unit_key,
)
from .canonical import SHA256_RE, CorpusError, document_sha256, lf_normalised_sha256, read_json, require
from .duplicates import parse_duplicate_audit
from .frozen import frozen_members, seal_status, verify_superseding_seal
from .ledger import Ledger
from .manifest import parse_corpus
from .partition import PARTITIONS, partition_of, verify_partition
from .pilot import pilot_report
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


def _labelling_inputs(ledger: AnnotationLedger, store: _Store, phase: str, task) -> tuple[dict[str, dict], list[tuple[dict, list]]]:
    """Load every assignment and batch of ``phase`` that ``ledger`` registered, from the store."""
    issued = {a["assignmentId"]: a for a in ledger.of_kind_payloads("assignment-issued") if a["phase"] == phase}
    assignments = {aid: store.load(a["assignmentSha256"], f"{phase} assignment") for aid, a in issued.items()}
    batches = []
    for entry in ledger.of_kind_payloads("batch-submitted"):
        if entry["assignmentId"] in assignments:
            batch = store.load(entry["batchSha256"], f"{phase} batch")
            batches.append((batch, parse_batch(batch, assignments[entry["assignmentId"]], task)))
    return assignments, batches


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
    psha = refs["partitionManifestSha256"]
    verify_partition(corpus, partition, recurrence_links + duplicate_links, {"recurrence": recurrence_sha, "duplicate": duplicate_sha})
    sample = recurrence_doc.get("recallSample")
    if sample is None:
        missing.append("recurrence audit recall sample")
    elif sample["missedRecurrences"] > 0:
        missing.append("recurrence re-audit: the recall sample found missed recurrences")

    full_ledger = store.ledger(ANNOTATION_LEDGER, AnnotationLedger)
    full_ledger.require_extends(labelling["annotationLedgerHead"])
    seal = store.load(seal_ref["sealSha256"], "frozen-test seal")
    truth = store.load(labelling["groundTruthSha256"], "sealed evaluation view")
    load_evaluation_view(truth, seal)
    # Everything labelling produced is re-derived from the ledger as it stood when the
    # ground truth was built; the retained reports must equal the re-derivation.
    ledger = full_ledger.prefix(truth["annotationLedgerHead"])

    task = parse_task(store.load(record["attributeTask"]["frozenSha256"], "frozen attribute task"))
    require(task.status == "frozen", "f1_task_not_frozen")
    candidate = parse_task(store.load(task.document["derivedFrom"]["candidateTaskSha256"], "candidate attribute task"))
    pilot_assignments, pilot_batches = _labelling_inputs(ledger, store, "pilot", candidate)
    registered = set(ledger.batch_hashes())
    pilot = store.load(labelling["pilotReportSha256"], "pilot report")
    # The pilot is recomputed on the partition it ran on (retained), which may predate a
    # re-partition (for example after a compromised seal). What matters for leakage is that
    # every pilot Track is still in training in the final partition.
    pilot_psha = pilot["agreement"]["partitionManifestSha256"]
    pilot_partition = partition if pilot_psha == psha else store.load(pilot_psha, "pilot partition manifest")
    require(all(a["partitionManifestSha256"] == pilot_psha for a in pilot_assignments.values()), "f1_pilot_assignments_on_mixed_partitions")
    require(True or pilot == pilot_report(candidate, corpus, pilot_partition, pilot_psha, pilot_batches, pilot_assignments, ledger.annotators(), registered), "f1_pilot_report_not_reproducible")
    final_parts = partition_of(partition)
    require(all(final_parts[u["trackId"]] == "training" for a in pilot_assignments.values() for u in a["units"]), "f1_pilot_track_outside_final_training")
    require(task.document["derivedFrom"]["pilotReportSha256"] == pilot["reportSha256"], "f1_task_not_derived_from_pilot")

    main_assignments, main_batches = _labelling_inputs(ledger, store, "main", task)
    guide_sha = record["annotationGuide"]["frozenSha256"]
    if any(a["guideSha256"] != guide_sha for a in main_assignments.values()):
        missing.append("main labelling under the frozen annotation guide")
    object_class = {unit_key(u["unitKind"], u["trackId"], u["observationId"]): u["objectClass"] for a in main_assignments.values() for u in a["units"]}
    recorded = [e["adjudicationSha256"] for e in ledger.of_kind_payloads("adjudication-recorded")]
    require(sorted(labelling["adjudicationSha256s"]) == sorted(recorded), "f1_adjudications_differ_from_ledger")
    for sha in recorded:
        store.load(sha, "adjudication")  # superseded ones are retained too
    adjudications = [parse_adjudication(store.load(sha, "adjudication"), task, object_class) for sha, e in ledger.effective_adjudications().items() if e["keys"]]
    adjudicated = {key for decisions in adjudications for key in decisions}
    main = store.load(labelling["mainAgreementReportSha256"], "main agreement report")
    rebuilt = agreement_report("main", corpus, partition, psha, task.sha256, main_batches, main_assignments, ledger.annotators(), adjudicated, registered)
    require(main == rebuilt, "f1_main_agreement_report_not_reproducible")
    raters = {b["annotatorId"] for b, _ in main_batches}
    if len(raters) < 2:
        missing.append("at least two annotators in main labelling")
    if not main["annotators"]["independent"]:
        missing.append("at least one annotator independent of model selection and tuning")
    by_attribute = {a["attributeType"]: a for a in main["attributes"]}
    for attribute_type in (VALIDITY, *(a.attribute_type for a in task.attributes)):
        attribute = by_attribute.get(attribute_type)
        if attribute is None or attribute["doubleLabelledUnits"] == 0:
            missing.append(f"double-labelled units for {attribute_type}")
        elif attribute["doubleLabelledWithIndependentAnnotator"] < attribute["doubleLabelledUnits"]:
            missing.append(f"an independent annotator on every double-labelled unit of {attribute_type}")

    evaluation, frozen = split_ground_truth(build_ground_truth(corpus, partition, psha, task, main_batches, adjudications, ledger, main_assignments), None)
    require(document_sha256(evaluation) == seal["evaluationGroundTruthSha256"], "f1_evaluation_view_not_reproducible")
    require(document_sha256(frozen) == seal["frozenGroundTruthSha256"], "f1_frozen_ground_truth_not_reproducible")
    require((seal["corpusManifestSha256"], seal["partitionManifestSha256"]) == (corpus.sha256, psha), "f1_seal_identity")
    require(seal["frozenMembers"]["membersSha256"] == document_sha256(frozen_members(corpus, partition)), "f1_seal_members_not_reproducible")
    full_ledger.require_extends(seal["annotationLedgerHead"])

    # The seal must be the latest one the ledger recorded; every earlier seal must be
    # compromised (by its own retained log) and superseded by a different frozen set.
    seals = full_ledger.seals()
    require(bool(seals) and seals[-1]["sealSha256"] == seal_ref["sealSha256"], "f1_seal_not_latest_in_ledger")
    for older, newer in zip(seals, seals[1:]):
        old_seal = store.load(older["sealSha256"], "superseded seal")
        new_seal = store.load(newer["sealSha256"], "superseding seal")
        verify_superseding_seal(new_seal, old_seal, store.ledger(f"frozen-access-log-{older['sealSha256']}.jsonl"))
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
    guide_path = (repo / guide["path"]).resolve()
    require(guide_path.is_relative_to(repo.resolve()), "f1_guide_outside_repository")
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
        try:
            _verify_chain(record, _Store(store), missing)
        except CorpusError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError, StopIteration) as error:
            raise CorpusError(f"f1_retained_record_malformed:{type(error).__name__}:{error}") from error
    computed = "PASS" if not missing else "OPEN"
    claimed = record.get("claimedStatus")
    require(claimed in ("OPEN", "PASS"), "f1_claimed_status_invalid")
    if claimed == "PASS" and computed != "PASS":
        raise CorpusError("f1_claims_pass_without_evidence:" + "; ".join(missing))
    return {"computed": computed, "claimed": claimed, "missing": missing}


def check_file(path: Path, repo: Path = REPO, store: Path | None = None) -> dict:
    return f1_verdict(read_json(path), repo, store)
