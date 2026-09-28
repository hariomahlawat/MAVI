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
from attributes.corpus.ledger import Ledger
from attributes.corpus.frozen import build_seal, declare_improper_access, open_access_log, seal_evaluation_view, verify_superseding_seal
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


def _labelled(ledger, name, annotator, phase, units, corpus, partition, psha, task, guide_sha, retained, choose=_choice):
    assignment = build_assignment(name, annotator, phase, "independent", units, corpus, partition, psha, task, guide_sha)
    ledger.issue_assignment(assignment, T0)
    rows = [
        {"unitKind": u["unitKind"], "trackId": u["trackId"], "observationId": None, "attributeType": a, "outcome": choose(u, a)[0], "value": choose(u, a)[1], "unscorableReason": choose(u, a)[2]}
        for u in assignment["units"] for a in u["attributeTypes"]
    ]
    batch = build_batch(f"batch-{name}", assignment, T0, rows, 600, task)
    ledger.submit_batch(batch, assignment, T0)
    retained.extend([assignment, batch])
    return assignment, (batch, parse_batch(batch, assignment, task))


def build_chain(tmp: Path, kind: str = "operational", recall: bool = True, tracks_per_source: int = 4, main_guide: str | None = None, seal: bool = True, context: dict | None = None, **policy_overrides: object) -> tuple[dict, Path]:
    """Run the whole S2c.1 workflow and retain every record in a hash-addressed store."""
    store = tmp / "store"
    store.mkdir()
    guide = tmp / "guide.md"
    guide.write_text("# guide\n")
    guide_sha = lf_normalised_sha256(guide)
    raw_corpus = build_corpus(sites=4, cameras_per_site=3, days=12, tracks_per_source=tracks_per_source, kind=kind)
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
    retained: list[dict] = [candidate.document]
    pilot_units = [("track", t, None) for t in sample_pilot_tracks(corpus, partition, 30, "pilot-seed")]
    assignments, batches = {}, []
    for annotator in ("ann-a", "ann-b"):
        a, b = _labelled(ledger, f"pilot-{annotator}", annotator, "pilot", pilot_units, corpus, partition, psha, candidate, guide_sha, retained)
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
        a, b = _labelled(ledger, f"main-{annotator}", annotator, "main", main_units, corpus, partition, psha, task, main_guide or guide_sha, retained)
        main_assignments[a["assignmentId"]], main_batches = a, main_batches + [b]
    main = agreement_report("main", corpus, partition, psha, task.sha256, main_batches, main_assignments, ledger.annotators(), set(), set(ledger.batch_hashes()))
    truth = build_ground_truth(corpus, partition, psha, task, main_batches, [], ledger, main_assignments)
    evaluation, frozen = split_ground_truth(truth, None)
    sealing = seal
    seal = build_seal(corpus, partition, psha, frozen, evaluation, ledger.head, "custodian-1", T0, "held by the custodian outside the evaluation environment")
    if sealing:
        ledger.record_seal(seal, T0)
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
        *((document_sha256(d), d) for d in retained),
    ):
        write_canonical(store / f"{name}.json", document)
    record = json.loads(COMMITTED.read_text())
    record["annotationGuide"] = {"path": "guide.md", "frozenSha256": guide_sha}
    record["attributeTask"]["frozenSha256"] = task.sha256
    record["corpus"] = {"corpusKind": kind, "corpusManifestSha256": corpus.sha256, "partitionManifestSha256": psha, "recurrenceAuditSha256": recurrence_sha, "duplicateAuditSha256": duplicate_sha}
    record["labelling"] = {"pilotReportSha256": document_sha256(pilot), "mainAgreementReportSha256": document_sha256(main), "adjudicationSha256s": [], "groundTruthSha256": document_sha256(sealed_view), "annotationLedgerHead": ledger.head}
    record["seal"] = {"sealSha256": document_sha256(seal), "accessLogHead": log.head} if sealing else {"sealSha256": None, "accessLogHead": None}
    record["limitations"] = list(partition["checks"]["limitations"])
    record["custodian"] = "custodian-1"
    if context is not None:
        context.update(
            corpus=corpus, links=recurrence_links + duplicate_links, hashes={"recurrence": recurrence_sha, "duplicate": duplicate_sha},
            ledger=ledger, task=task, main_batches=main_batches, main_assignments=main_assignments, pilot_units=pilot_units, seal=seal,
        )
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


def _seal_args(tmp_path, store, log_name, out_name):
    custody = tmp_path / "custody"
    return [
        "seal", "--corpus", str(custody / "corpus.json"), "--partition", str(custody / "partition.json"),
        "--frozen", str(custody / "frozen.json"), "--evaluation", str(custody / "evaluation.json"),
        "--sealed-evaluation-out", str(custody / f"sealed-{out_name}"), "--ledger", str(store / ANNOTATION_LEDGER),
        "--by", "custodian-1", "--custody-note", "held by the custodian", "--access-log", str(custody / log_name), "--out", str(custody / out_name),
    ]


def test_cli_seals_once_logs_access_and_re_verifies_from_the_store(tmp_path, capsys) -> None:
    record, store = build_chain(tmp_path, seal=False)
    custody = tmp_path / "custody"
    assert main(_seal_args(tmp_path, store, "access.jsonl", "seal.json")) == 0
    seal = json.loads((custody / "seal.json").read_text())
    view = json.loads((custody / "sealed-seal.json").read_text())
    assert view["sealSha256"] == document_sha256(seal)
    assert main(_seal_args(tmp_path, store, "access.jsonl", "again.json")) == 2, "a second seal cannot reset an existing access log"
    assert main(_seal_args(tmp_path, store, "other.jsonl", "again.json")) == 2, "a second seal needs --supersedes"
    access = ["frozen-access", "--seal", str(custody / "seal.json"), "--frozen", str(custody / "frozen.json"), "--actor", "custodian-1", "--purpose", "integrity-verify", "--stage", "S2c.2"]
    assert main([*access, "--access-log", str(custody / "access.jsonl")]) == 0
    assert main([*access, "--access-log", str(custody / "missing.jsonl")]) == 2, "no silent new log"
    write_canonical(store / f"{document_sha256(seal)}.json", seal)
    write_canonical(store / f"{document_sha256(view)}.json", view)
    (store / ACCESS_LOG).write_bytes((custody / "access.jsonl").read_bytes())
    record["seal"] = {"sealSha256": document_sha256(seal), "accessLogHead": Ledger(store / ACCESS_LOG).head}
    record["labelling"]["groundTruthSha256"] = document_sha256(view)
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(record))
    capsys.readouterr()
    assert main(["check-f1", "--record", str(record_path), "--store", str(store)]) == 0
    verdict = json.loads(capsys.readouterr().out)
    # The tmp guide is not under the repository, so only the guide is missing; the whole
    # retained chain re-verified from the store.
    assert verdict["computed"] == "OPEN" and verdict["missing"] == ["annotation guide file"]
    record["annotationGuide"]["path"] = "../../etc/passwd"
    with pytest.raises(CorpusError, match="f1_guide_outside_repository"):
        f1_verdict(record, tmp_path, store)


def test_a_compromised_seal_cannot_be_replaced_by_resealing_the_same_set(tmp_path) -> None:
    """Re-sealing is refused without --supersedes, and a superseding seal must name a new set."""
    record, store = build_chain(tmp_path)
    seal = json.loads((store / f"{record['seal']['sealSha256']}.json").read_text())
    declare_improper_access(open_access_log(store / ACCESS_LOG, seal, T0), seal, "engineer-1", "S2c.3", "opened while debugging", T0)
    assert main(_seal_args(tmp_path, store, "new.jsonl", "new-seal.json")) == 2
    old = tmp_path / "old-seal.json"
    write_canonical(old, seal)
    superseding = [*_seal_args(tmp_path, store, "new.jsonl", "new-seal.json"), "--supersedes", str(old), "--supersedes-reason", "compromised in S2c.3", "--superseded-access-log", str(store / ACCESS_LOG)]
    assert main(superseding) == 2, "the same frozen set cannot be re-sealed"
    assert not (tmp_path / "custody" / "new.jsonl").exists()
    assert AnnotationLedger(store / ANNOTATION_LEDGER).seals()[-1]["sealSha256"] == record["seal"]["sealSha256"]


def test_f1_refuses_a_seal_the_ledger_does_not_name_as_latest(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    seal = json.loads((store / f"{record['seal']['sealSha256']}.json").read_text())
    newer = dict(seal, custodyNote="a later seal", supersedes={"sealSha256": document_sha256(seal), "reason": "later"})
    AnnotationLedger(store / ANNOTATION_LEDGER).record_seal(newer, T0)
    with pytest.raises(CorpusError, match="f1_seal_not_latest_in_ledger"):
        f1_verdict(record, tmp_path, store)


def test_f1_recomputes_the_sealed_member_set(tmp_path) -> None:
    record, store = build_chain(tmp_path, seal=False)
    custody = tmp_path / "custody"
    corpus = parse_corpus(json.loads((custody / "corpus.json").read_text()))
    partition = json.loads((custody / "partition.json").read_text())
    evaluation = json.loads((custody / "evaluation.json").read_text())
    ledger = AnnotationLedger(store / ANNOTATION_LEDGER)
    seal = build_seal(corpus, partition, document_sha256(partition), json.loads((custody / "frozen.json").read_text()), evaluation, ledger.head, "custodian-1", T0, "x")
    seal["frozenMembers"]["membersSha256"] = "7" * 64  # hand-edited before sealing
    ledger.record_seal(seal, T0)
    log = open_access_log(store / ACCESS_LOG, seal, T0, create=True)
    view = seal_evaluation_view(evaluation, seal)
    for document in (seal, view):
        write_canonical(store / f"{document_sha256(document)}.json", document)
    record["seal"] = {"sealSha256": document_sha256(seal), "accessLogHead": log.head}
    record["labelling"]["groundTruthSha256"] = document_sha256(view)
    with pytest.raises(CorpusError, match="f1_seal_members_not_reproducible"):
        f1_verdict(record, tmp_path, store)


def test_f1_needs_double_labels_for_every_task_attribute(tmp_path) -> None:
    """An all-person corpus leaves the vehicle attribute unlabelled: F1 stays OPEN."""
    record, store = build_chain(tmp_path, tracks_per_source=1)
    missing = f1_verdict(record, tmp_path, store)["missing"]
    assert missing == ["double-labelled units for vehicle-colour"]


def test_f1_needs_main_labelling_under_the_frozen_guide(tmp_path) -> None:
    record, store = build_chain(tmp_path, main_guide="9" * 64)
    assert f1_verdict(record, tmp_path, store)["missing"] == ["main labelling under the frozen annotation guide"]


def test_a_forged_but_self_consistent_agreement_report_is_refused(tmp_path) -> None:
    """Editing a statistic and re-hashing the report does not help: F1 recomputes it."""
    record, store = build_chain(tmp_path)
    document = json.loads((store / f"{record['labelling']['mainAgreementReportSha256']}.json").read_text())
    document["attributes"][0]["doubleLabelledUnits"] += 1
    del document["reportSha256"]
    document["reportSha256"] = document_sha256(document)
    write_canonical(store / f"{document_sha256(document)}.json", document)
    record["labelling"]["mainAgreementReportSha256"] = document_sha256(document)
    with pytest.raises(CorpusError, match="f1_main_agreement_report_not_reproducible"):
        f1_verdict(record, tmp_path, store)


def test_a_malformed_retained_record_is_refused_not_crashed(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    path = store / f"{record['labelling']['pilotReportSha256']}.json"
    document = json.loads(path.read_text())
    del document["agreement"]
    write_canonical(store / f"{document_sha256(document)}.json", document)
    record["labelling"]["pilotReportSha256"] = document_sha256(document)
    with pytest.raises(CorpusError):
        f1_verdict(record, tmp_path, store)


def test_a_main_report_naming_an_unregistered_batch_is_refused(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    document = json.loads((store / f"{record['labelling']['mainAgreementReportSha256']}.json").read_text())
    document["batchSha256s"] = sorted([*document["batchSha256s"], "c" * 64])
    del document["reportSha256"]
    document["reportSha256"] = document_sha256(document)
    write_canonical(store / f"{document_sha256(document)}.json", document)
    record["labelling"]["mainAgreementReportSha256"] = document_sha256(document)
    with pytest.raises(CorpusError, match="f1_main_agreement_report_not_reproducible"):
        f1_verdict(record, tmp_path, store)


def test_r1_recovery_after_a_compromise_can_reach_pass(tmp_path) -> None:
    """Compromise, re-partition with the pilot pinned to training, re-seal a new frozen set."""
    ctx: dict = {}
    record, store = build_chain(tmp_path, context=ctx)
    corpus, ledger, task = ctx["corpus"], ctx["ledger"], ctx["task"]
    old_seal = ctx["seal"]
    old_sha = document_sha256(old_seal)
    log = open_access_log(store / ACCESS_LOG, old_seal, T0)
    declare_improper_access(log, old_seal, "engineer-1", "S2c.3", "opened while debugging", T0)
    assert f1_verdict(record, tmp_path, store)["computed"] == "OPEN"
    (store / ACCESS_LOG).rename(store / f"frozen-access-log-{old_sha}.jsonl")

    pinned = sorted(u[1] for u in ctx["pilot_units"])
    partition = build_partition(corpus, policy(seed="r1-5", dateBlockDays=2, pinnedTrainingTrackIds=pinned), ctx["links"], ctx["hashes"])
    psha = document_sha256(partition)
    ledger = AnnotationLedger(store / ANNOTATION_LEDGER)
    main = agreement_report("main", corpus, partition, psha, task.sha256, ctx["main_batches"], ctx["main_assignments"], ledger.annotators(), set(), set(ledger.batch_hashes()))
    evaluation, frozen = split_ground_truth(build_ground_truth(corpus, partition, psha, task, ctx["main_batches"], [], ledger, ctx["main_assignments"]), None)
    seal = build_seal(corpus, partition, psha, frozen, evaluation, ledger.head, "custodian-1", T0, "new frozen set", {"sealSha256": old_sha, "reason": "compromised in S2c.3"})
    verify_superseding_seal(seal, old_seal, Ledger(store / f"frozen-access-log-{old_sha}.jsonl"))
    new_log = open_access_log(store / ACCESS_LOG, seal, T0, create=True)
    ledger.record_seal(seal, T0)
    view = seal_evaluation_view(evaluation, seal)
    for document in (partition, main, seal, view):
        write_canonical(store / f"{document_sha256(document)}.json", document)
    record["corpus"]["partitionManifestSha256"] = psha
    record["labelling"]["mainAgreementReportSha256"] = document_sha256(main)
    record["labelling"]["groundTruthSha256"] = document_sha256(view)
    record["seal"] = {"sealSha256": document_sha256(seal), "accessLogHead": new_log.head}
    record["limitations"] = list(partition["checks"]["limitations"])
    assert f1_verdict(record, tmp_path, store) == {"computed": "PASS", "claimed": "OPEN", "missing": []}
    # Without the pilot pinned, a re-partition that moved pilot Tracks out of training is refused.
    unpinned = build_partition(corpus, policy(seed="r1-5", dateBlockDays=2), ctx["links"], ctx["hashes"])
    assert any(dict((a["trackId"], a["partition"]) for a in unpinned["assignments"])[t] != "training" for t in pinned)
    write_canonical(store / f"{document_sha256(unpinned)}.json", unpinned)
    record["corpus"]["partitionManifestSha256"] = document_sha256(unpinned)
    with pytest.raises(CorpusError, match="f1_pilot_track_outside_final_training"):
        f1_verdict(record, tmp_path, store)


def test_a_failed_seal_leaves_no_ledger_entry_and_can_be_retried(tmp_path, capsys) -> None:
    record, store = build_chain(tmp_path, seal=False)
    bad = _seal_args(tmp_path, store, "no-such-dir/access.jsonl", "seal.json")
    assert main(bad) == 2
    assert "seal_output_directory_missing" in capsys.readouterr().err
    assert AnnotationLedger(store / ANNOTATION_LEDGER).seals() == []
    assert main(_seal_args(tmp_path, store, "access.jsonl", "seal.json")) == 0
    assert len(AnnotationLedger(store / ANNOTATION_LEDGER).seals()) == 1
