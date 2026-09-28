"""S2c.1: the F1 checker re-verifies the retained records; it never trusts the record.

The chain below is synthetic. It proves the checker, not F1. Where it is labelled
``operational``, that label is applied only inside a temporary directory, to show that
PASS is reachable only through a fully consistent chain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from attribute_corpus_fixtures import build_corpus, policy, sha

from attributes.corpus import task as task_module
from attributes.corpus.agreement import agreement_report
from attributes.corpus.annotation import (
    AnnotationLedger,
    build_assignment,
    build_batch,
    build_ground_truth,
    parse_batch,
    split_ground_truth,
)
from attributes.corpus.cli import main
from attributes.corpus.canonical import CorpusError, document_sha256, lf_normalised_sha256, write_canonical
from attributes.corpus.duplicates import build_duplicate_audit, parse_duplicate_audit
from attributes.corpus.f1 import ACCESS_LOG, ANNOTATION_LEDGER, REPO, f1_verdict
from attributes.corpus.frozen import build_seal, declare_improper_access, open_access_log, seal_evaluation_view
from attributes.corpus.manifest import parse_corpus
from attributes.corpus.partition import build_partition
from attributes.corpus.pilot import pilot_report, sample_pilot_tracks
from attributes.corpus.recurrence import parse_recurrence
from attributes.corpus.task import load_task, parse_task

T0 = "2026-10-20T09:00:00Z"
COMMITTED = REPO / "docs" / "qualification" / "stage2-s2c" / "corpus" / "f1-evidence-record.json"


def _choice(unit, attribute):
    if attribute == "subject-validity":
        return ("value", "valid", None)
    if attribute.endswith("colour"):
        return ("value", "black", None)
    if attribute == "person-headwear":
        return ("unscorable", None, "not-visible")
    return ("value", "absent", None)


def _labelled(ledger, name, annotator, phase, units, corpus, partition, psha, task, guide_sha):
    assignment = build_assignment(name, annotator, phase, "independent", units, corpus, partition, psha, task, guide_sha)
    ledger.issue_assignment(assignment, T0)
    rows = [
        {"unitKind": u["unitKind"], "trackId": u["trackId"], "observationId": None, "attributeType": a, "outcome": _choice(u, a)[0], "value": _choice(u, a)[1], "unscorableReason": _choice(u, a)[2]}
        for u in assignment["units"] for a in u["attributeTypes"]
    ]
    batch = build_batch(f"batch-{name}", assignment, T0, rows, 600, task)
    ledger.submit_batch(batch, assignment, T0)
    return assignment, (batch, parse_batch(batch, assignment, task))


def build_chain(tmp: Path, kind: str = "operational", recall: bool = True, **policy_overrides: object) -> tuple[dict, Path]:
    """Run the whole S2c.1 workflow and retain every record in a hash-addressed store."""
    store = tmp / "store"
    store.mkdir()
    guide = tmp / "guide.md"
    guide.write_text("# guide\n")
    guide_sha = lf_normalised_sha256(guide)
    raw_corpus = build_corpus(sites=4, cameras_per_site=3, days=12, tracks_per_source=1, kind=kind)
    corpus = parse_corpus(raw_corpus)
    recurrence = {"schemaVersion": "mavi-attribute-recurrence-audit-v1", "corpusManifestSha256": corpus.sha256, "groups": []}
    if recall:
        recurrence["recallSample"] = {"by": "reviewer-1", "date": "2026-10-02", "sampledPairs": 200, "missedRecurrences": 0, "note": "random cross-partition pairs, second reviewer"}
    recurrence_sha, recurrence_links = parse_recurrence(recurrence, corpus)
    fingerprints = {o: sha("fp", o)[:16] for o in sorted(corpus.observations)}
    duplicates = build_duplicate_audit(corpus, fingerprints, 6)
    duplicate_sha, duplicate_links = parse_duplicate_audit(duplicates, corpus)
    partition = build_partition(corpus, policy(**policy_overrides), recurrence_links + duplicate_links, {"recurrence": recurrence_sha, "duplicate": duplicate_sha})
    psha = document_sha256(partition)

    ledger = AnnotationLedger(store / ANNOTATION_LEDGER)
    ledger.register_annotator("ann-a", False, T0)
    ledger.register_annotator("ann-b", True, T0)
    candidate = parse_task(task_module.confirm_rules(load_task().document, "owner-1", "2026-10-01T09:00:00Z"))
    pilot_units = [("track", t, None) for t in sample_pilot_tracks(corpus, partition, 30, "pilot-seed")]
    assignments, batches = {}, []
    for annotator in ("ann-a", "ann-b"):
        a, b = _labelled(ledger, f"pilot-{annotator}", annotator, "pilot", pilot_units, corpus, partition, psha, candidate, guide_sha)
        assignments[a["assignmentId"]], batches = a, batches + [b]
    pilot = pilot_report(candidate, corpus, partition, psha, batches, assignments, ledger.annotators(), set(ledger.batch_hashes()))
    decision = {
        "schemaVersion": "mavi-attribute-task-freeze-decision-v1", "decidedBy": "owner-1", "decidedAt": "2026-10-09T09:00:00Z",
        "valueMerges": [], "attributeMerges": [], "valueRemovals": [], "attributeRemovals": [], "rationale": "fixture freeze",
    }
    frozen_doc = task_module.freeze_task(candidate, pilot, decision)
    task = parse_task(frozen_doc)

    main_units = [("track", t, None) for t in sorted(corpus.tracks)]
    main_assignments, main_batches = {}, []
    for annotator in ("ann-a", "ann-b"):
        a, b = _labelled(ledger, f"main-{annotator}", annotator, "main", main_units, corpus, partition, psha, task, guide_sha)
        main_assignments[a["assignmentId"]], main_batches = a, main_batches + [b]
    main = agreement_report("main", corpus, partition, psha, task.sha256, main_batches, main_assignments, ledger.annotators(), set(), set(ledger.batch_hashes()))
    truth = build_ground_truth(corpus, partition, psha, task, main_batches, [], ledger, main_assignments)
    evaluation, frozen = split_ground_truth(truth, None)
    seal = build_seal(corpus, partition, psha, frozen, evaluation, ledger.head, "custodian-1", T0, "held by the custodian outside the evaluation environment")
    log = open_access_log(store / ACCESS_LOG, seal, T0, create=True)
    sealed_view = seal_evaluation_view(evaluation, seal)
    custody = tmp / "custody"
    custody.mkdir()
    write_canonical(custody / "frozen.json", frozen)
    write_canonical(custody / "evaluation.json", evaluation)
    write_canonical(custody / "corpus.json", raw_corpus)
    write_canonical(custody / "partition.json", partition)

    for name, document in (
        (corpus.sha256, raw_corpus), (recurrence_sha, recurrence), (duplicate_sha, duplicates), (psha, partition),
        (document_sha256(pilot), pilot), (task.sha256, frozen_doc), (document_sha256(main), main),
        (document_sha256(seal), seal), (document_sha256(sealed_view), sealed_view),
    ):
        write_canonical(store / f"{name}.json", document)
    record = json.loads(COMMITTED.read_text())
    record["annotationGuide"] = {"path": "guide.md", "frozenSha256": guide_sha}
    record["attributeTask"]["frozenSha256"] = task.sha256
    record["corpus"] = {"corpusKind": kind, "corpusManifestSha256": corpus.sha256, "partitionManifestSha256": psha, "recurrenceAuditSha256": recurrence_sha, "duplicateAuditSha256": duplicate_sha}
    record["labelling"] = {"pilotReportSha256": document_sha256(pilot), "mainAgreementReportSha256": document_sha256(main), "adjudicationSha256s": [], "groundTruthSha256": document_sha256(sealed_view), "annotationLedgerHead": ledger.head}
    record["seal"] = {"sealSha256": document_sha256(seal), "accessLogHead": log.head}
    record["limitations"] = list(partition["checks"]["limitations"])
    record["custodian"] = "custodian-1"
    return record, store


def test_committed_record_is_open_and_names_the_missing_inputs() -> None:
    verdict = f1_verdict(json.loads(COMMITTED.read_text()))
    assert verdict["claimed"] == verdict["computed"] == "OPEN"
    assert any("operational corpus" in m for m in verdict["missing"])


def test_a_fully_consistent_chain_re_verifies_to_pass(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    verdict = f1_verdict(record, tmp_path, store)
    assert verdict == {"computed": "PASS", "claimed": "OPEN", "missing": []}
    record["claimedStatus"] = "PASS"
    assert f1_verdict(record, tmp_path, store)["computed"] == "PASS"


def test_without_the_store_the_named_hashes_prove_nothing(tmp_path) -> None:
    """Mutation 10: self-asserted hashes can never produce PASS."""
    record, _store = build_chain(tmp_path)
    verdict = f1_verdict(record, tmp_path)
    assert verdict["computed"] == "OPEN" and any("--store" in m for m in verdict["missing"])
    record["claimedStatus"] = "PASS"
    with pytest.raises(CorpusError, match="f1_claims_pass_without_evidence"):
        f1_verdict(record, tmp_path)


def test_synthetic_chain_never_passes(tmp_path) -> None:
    record, store = build_chain(tmp_path, kind="synthetic-fixture")
    assert f1_verdict(record, tmp_path, store)["computed"] == "OPEN"
    record["claimedStatus"] = "PASS"
    with pytest.raises(CorpusError, match="f1_claims_pass_without_evidence"):
        f1_verdict(record, tmp_path, store)


def test_a_record_that_names_a_hash_it_does_not_retain_fails(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    record["labelling"]["mainAgreementReportSha256"] = "e" * 64
    with pytest.raises(CorpusError, match="f1_record_missing:main agreement report"):
        f1_verdict(record, tmp_path, store)


def test_an_edited_retained_record_fails_its_hash(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    path = store / f"{record['labelling']['mainAgreementReportSha256']}.json"
    document = json.loads(path.read_text())
    document["annotators"]["independent"] = ["ann-a", "ann-b"]
    path.write_text(json.dumps(document))
    with pytest.raises(CorpusError, match="f1_record_hash_mismatch:main agreement report"):
        f1_verdict(record, tmp_path, store)


def test_a_relabelled_evaluation_view_is_not_the_sealed_one(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    old = store / f"{record['labelling']['groundTruthSha256']}.json"
    document = json.loads(old.read_text())
    document["rows"][0]["final"]["value"] = "white"
    write_canonical(store / f"{document_sha256(document)}.json", document)
    record["labelling"]["groundTruthSha256"] = document_sha256(document)
    with pytest.raises(CorpusError, match="evaluation_view_not_the_sealed_one"):
        f1_verdict(record, tmp_path, store)


def test_an_improper_access_keeps_f1_open(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    seal = json.loads((store / f"{record['seal']['sealSha256']}.json").read_text())
    log = open_access_log(store / ACCESS_LOG, seal, T0)
    declare_improper_access(log, seal, "engineer-1", "S2c.3", "opened while debugging", T0)
    record["seal"]["accessLogHead"] = log.head
    verdict = f1_verdict(record, tmp_path, store)
    assert verdict["computed"] == "OPEN" and any("improper access" in m for m in verdict["missing"])


def test_a_truncated_access_log_is_detected(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    seal = json.loads((store / f"{record['seal']['sealSha256']}.json").read_text())
    log = open_access_log(store / ACCESS_LOG, seal, T0)
    declare_improper_access(log, seal, "engineer-1", "S2c.3", "opened while debugging", T0)
    record["seal"]["accessLogHead"] = log.head
    path = store / ACCESS_LOG
    path.write_text(path.read_text().splitlines()[0] + "\n")  # the improper access cut away
    with pytest.raises(CorpusError, match="ledger_truncated_or_forked"):
        f1_verdict(record, tmp_path, store)


def test_a_missing_recall_sample_keeps_f1_open(tmp_path) -> None:
    record, store = build_chain(tmp_path, recall=False)
    verdict = f1_verdict(record, tmp_path, store)
    assert verdict["missing"] == ["recurrence audit recall sample"]


def test_a_record_that_hides_partition_limitations_is_refused(tmp_path) -> None:
    record, store = build_chain(tmp_path, minimumCamerasPerPartition=50)
    assert record["limitations"], "the stricter policy records camera shortfalls"
    assert f1_verdict(record, tmp_path, store)["computed"] == "PASS"  # recorded limitations are allowed
    record["limitations"] = []
    with pytest.raises(CorpusError, match="f1_record_omits_partition_limitations"):
        f1_verdict(record, tmp_path, store)


def test_access_log_cannot_be_silently_recreated(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    seal = json.loads((store / f"{record['seal']['sealSha256']}.json").read_text())
    (store / ACCESS_LOG).unlink()
    with pytest.raises(CorpusError, match="access_log_missing_or_empty"):
        open_access_log(store / ACCESS_LOG, seal, T0)
    open_access_log(store / ACCESS_LOG, seal, T0, create=True)
    with pytest.raises(CorpusError, match="access_log_already_exists"):
        open_access_log(store / ACCESS_LOG, seal, T0, create=True)


def test_cli_seals_once_logs_access_and_re_verifies_from_the_store(tmp_path, capsys) -> None:
    record, store = build_chain(tmp_path)
    custody = tmp_path / "custody"
    seal_args = [
        "seal", "--corpus", str(custody / "corpus.json"), "--partition", str(custody / "partition.json"),
        "--frozen", str(custody / "frozen.json"), "--evaluation", str(custody / "evaluation.json"),
        "--sealed-evaluation-out", str(custody / "sealed-evaluation.json"), "--ledger", str(store / ANNOTATION_LEDGER),
        "--by", "custodian-1", "--custody-note", "held by the custodian", "--access-log", str(custody / "access.jsonl"), "--out", str(custody / "seal.json"),
    ]
    assert main(seal_args) == 0
    assert json.loads((custody / "sealed-evaluation.json").read_text())["sealSha256"] == document_sha256(json.loads((custody / "seal.json").read_text()))
    assert main(seal_args) == 2, "a second seal cannot reset an existing access log"
    access = ["frozen-access", "--seal", str(custody / "seal.json"), "--frozen", str(custody / "frozen.json"), "--actor", "custodian-1", "--purpose", "integrity-verify", "--stage", "S2c.2"]
    assert main([*access, "--access-log", str(custody / "access.jsonl")]) == 0
    assert main([*access, "--access-log", str(custody / "missing.jsonl")]) == 2, "no silent new log"
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(record))
    capsys.readouterr()
    assert main(["check-f1", "--record", str(record_path), "--store", str(store)]) == 0
    verdict = json.loads(capsys.readouterr().out)
    # The tmp guide is not under the repository, so only the guide is missing; the whole
    # retained chain re-verified from the store.
    assert verdict["computed"] == "OPEN" and verdict["missing"] == ["annotation guide file"]


def test_a_main_report_naming_an_unregistered_batch_is_refused(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    document = json.loads((store / f"{record['labelling']['mainAgreementReportSha256']}.json").read_text())
    document["batchSha256s"] = sorted([*document["batchSha256s"], "c" * 64])
    del document["reportSha256"]
    document["reportSha256"] = document_sha256(document)
    write_canonical(store / f"{document_sha256(document)}.json", document)
    record["labelling"]["mainAgreementReportSha256"] = document_sha256(document)
    with pytest.raises(CorpusError, match="f1_main_batches_not_in_ledger"):
        f1_verdict(record, tmp_path, store)
