"""S2c.1: the F1 checker re-verifies the retained records; it never trusts the record.

The chain below is synthetic. It proves the checker, not F1. Where it is labelled
``operational``, that label is applied only inside a temporary directory, to show that
PASS is reachable only through a fully consistent chain.
"""

from __future__ import annotations

import json
import shutil
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
    build_reveal_packet,
    parse_adjudication,
    parse_batch,
    split_ground_truth,
    unit_key,
)
from attributes.corpus.cli import main
from attributes.corpus.canonical import CorpusError, document_sha256, lf_normalised_sha256, write_canonical
from attributes.corpus.duplicates import build_duplicate_audit, parse_duplicate_audit
from attributes.corpus.f1 import ACCESS_LOG, ANNOTATION_LEDGER, REPO, f1_verdict
from attributes.corpus.ledger import Ledger
from attributes.corpus.frozen import frozen_members
from attributes.corpus.frozen import build_seal, declare_improper_access, open_access_log, seal_evaluation_view, verify_superseding_seal
from attributes.corpus.manifest import parse_corpus, revise_corpus
from attributes.corpus.partition import build_partition
from attributes.corpus.pilot import pilot_report, sample_pilot_tracks
from attributes.corpus.recurrence import RECALL_SAMPLE_PAIRS, draw_recall_sample, parse_recurrence, recurrence_document_sha256
from attributes.corpus.task import attribute_verdicts
from attributes.corpus.task import load_task, parse_task

T0 = "2026-10-20T09:00:00Z"
COMMITTED = REPO / "docs" / "qualification" / "stage2-s2c" / "corpus" / "f1-evidence-record.json"


def _choice(unit, attribute):
    """Varied labels on which every annotator agrees, so every alpha is defined (1.0)."""
    h = int(sha(unit["trackId"], attribute)[:8], 16)
    if attribute == "subject-validity":
        return ("value", "valid", None)
    if attribute.endswith("colour"):
        return ("unscorable", None, "occluded") if h % 5 == 0 else ("value", ("black", "white", "blue")[h % 3], None)
    if attribute == "person-headwear":
        return ("unscorable", None, "not-visible") if h % 3 == 0 else ("value", ("absent", "present")[(h // 3) % 2], None)
    return ("unscorable", None, "occluded") if h % 7 == 0 else ("value", ("absent", "present")[h % 2], None)


def _labelled(ledger, name, annotator, phase, units, corpus, partition, psha, task, guide_sha, retained, choose=_choice, edit=None):
    assignment = build_assignment(name, annotator, phase, "independent", units, corpus, partition, psha, task, guide_sha)
    if edit:
        edit(assignment)
    ledger.issue_assignment(assignment, T0)
    rows = [
        {"unitKind": u["unitKind"], "trackId": u["trackId"], "observationId": None, "attributeType": a, "outcome": choose(u, a)[0], "value": choose(u, a)[1], "unscorableReason": choose(u, a)[2]}
        for u in assignment["units"] for a in u["attributeTypes"]
    ]
    batch = build_batch(f"batch-{name}", assignment, T0, rows, 600, task)
    ledger.submit_batch(batch, assignment, T0)
    retained.extend([assignment, batch])
    return assignment, (batch, parse_batch(batch, assignment, task))


def _conflicting_choice(unit, attribute):
    """ann-b disagrees with ann-a on the backpack of every fourth person Track."""
    base = _choice(unit, attribute)
    if attribute == "person-backpack" and int(sha(unit["trackId"], "conflict")[:8], 16) % 4 == 0:
        return ("value", "absent", None) if base == ("value", "present", None) else ("value", "present", None)
    return base


def reviewed_recall_sample(corpus, partition, _confirmed=None, decision="not-recurrence", size=RECALL_SAMPLE_PAIRS):
    sample = draw_recall_sample(corpus, partition, size)
    for pair in sample["pairs"]:
        pair["decision"] = decision
    return {**sample, "by": "reviewer-1", "date": "2026-10-02", "note": "second reviewer, reproducible sample"}


def build_chain(tmp: Path, kind: str = "operational", recall: bool = True, tracks_per_source: int = 4, main_guide: str | None = None, seal: bool = True, context: dict | None = None, single_labelled_class: str | None = None, abandoned_pilot: bool = False, pilot_choose_b=None, forge_freeze: bool = False, conflicts: str | None = None, candidate_edit=None, recall_size: int = RECALL_SAMPLE_PAIRS, main_assignment_edit=None, main_corpus_edit=None, **policy_overrides: object) -> tuple[dict, Path]:
    """Run the whole S2c.1 workflow and retain every record in a hash-addressed store."""
    store = tmp / "store"
    store.mkdir()
    guide = tmp / "guide.md"
    guide.write_text("# guide\n")
    committed_candidate = json.loads(COMMITTED.read_text())["attributeTask"]["candidatePath"]
    (tmp / committed_candidate).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / committed_candidate, tmp / committed_candidate)
    guide_sha = lf_normalised_sha256(guide)
    raw_corpus = build_corpus(sites=4, cameras_per_site=3, days=12, tracks_per_source=tracks_per_source, kind=kind)
    corpus = parse_corpus(raw_corpus)
    recurrence = {"schemaVersion": "mavi-attribute-recurrence-audit-v1", "corpusManifestSha256": corpus.sha256, "groups": []}
    recurrence.pop("recallSample", None)
    recurrence_sha, recurrence_links = parse_recurrence(recurrence, corpus)
    fingerprints = {o: sha("fp", o)[:16] for o in sorted(corpus.observations)}
    duplicates = build_duplicate_audit(corpus, fingerprints, 6)
    duplicate_sha, duplicate_links = parse_duplicate_audit(duplicates, corpus)
    partition = build_partition(corpus, policy(**policy_overrides), recurrence_links + duplicate_links, {"recurrence": recurrence_sha, "duplicate": duplicate_sha})
    psha = document_sha256(partition)
    if recall:
        recurrence["recallSample"] = reviewed_recall_sample(corpus, partition, recurrence_links, size=recall_size)
    recurrence_doc_sha = recurrence_document_sha256(recurrence)

    ledger = AnnotationLedger(store / ANNOTATION_LEDGER)
    ledger.register_annotator("ann-a", False, T0)
    ledger.register_annotator("ann-b", True, T0)
    confirmed = task_module.confirm_rules(load_task().document, "owner-1", "2026-10-01T09:00:00Z")
    if candidate_edit:
        candidate_edit(confirmed)
    candidate = parse_task(confirmed)
    retained: list[dict] = [candidate.document]
    pilot_units = [("track", t, None) for t in sample_pilot_tracks(corpus, partition, 160, "pilot-seed")]
    assignments, batches = {}, []
    for annotator in ("ann-a", "ann-b"):
        choose = pilot_choose_b if annotator == "ann-b" and pilot_choose_b else _choice
        a, b = _labelled(ledger, f"pilot-{annotator}", annotator, "pilot", pilot_units, corpus, partition, psha, candidate, guide_sha, retained, choose)
        assignments[a["assignmentId"]], batches = a, batches + [b]
    if abandoned_pilot:  # issued, never submitted: the report below silently omits it
        spare = next(t for t in sample_pilot_tracks(corpus, partition, 400, "spare") if ("track", t, None) not in pilot_units)
        abandoned = build_assignment("pilot-abandoned", "ann-a", "pilot", "independent", [("track", spare, None)], corpus, partition, psha, candidate, guide_sha)
        ledger.issue_assignment(abandoned, T0)
        retained.append(abandoned)
        if abandoned_pilot == "forged-cancellation":  # hidden by a hand-written cancellation
            ledger.append("assignment-cancelled", {"assignmentId": "pilot-abandoned", "actor": "custodian-1", "reason": "hand-written", "replacementAssignmentId": "pilot-ann-b"}, T0)
    pilot = pilot_report(candidate, corpus, partition, psha, batches, assignments, ledger.annotators(), set(ledger.batch_hashes()))
    # The owner follows the pilot: anything it did not keep is removed.
    removals = sorted(name for name, v in attribute_verdicts(candidate, pilot["agreement"], candidate.document["pilotDecisionRules"]).items() if v["recommendation"] != "keep")
    if forge_freeze:
        removals = []  # a hand-forged freeze that keeps what the pilot failed
    decision = {
        "schemaVersion": "mavi-attribute-task-freeze-decision-v1", "decidedBy": "owner-1", "decidedAt": "2026-10-09T09:00:00Z",
        "valueMerges": [], "attributeMerges": [], "valueRemovals": [], "attributeRemovals": removals, "rationale": "fixture freeze",
    }
    if forge_freeze:
        original = task_module.verify_freeze_consistent_with_pilot
        task_module.verify_freeze_consistent_with_pilot = lambda *_: None
        try:
            frozen_doc = task_module.freeze_task(candidate, pilot, decision)
        finally:
            task_module.verify_freeze_consistent_with_pilot = original
    else:
        frozen_doc = task_module.freeze_task(candidate, pilot, decision)
    retained.append(decision)
    task = parse_task(frozen_doc)

    main_units = [("track", t, None) for t in sorted(corpus.tracks)]
    main_assignments, main_batches = {}, []
    for annotator in ("ann-a", "ann-b"):
        units = main_units if annotator == "ann-a" or single_labelled_class is None else [u for u in main_units if corpus.tracks[u[1]].object_class != single_labelled_class]
        choose = _conflicting_choice if annotator == "ann-b" and conflicts else _choice
        labelled_on = corpus
        if main_corpus_edit:  # labels made on another corpus revision (for example re-extracted crops)
            edited = json.loads(json.dumps(raw_corpus))
            main_corpus_edit(edited)
            labelled_on = parse_corpus(edited)
            write_canonical(store / f"{labelled_on.sha256}.json", edited)  # corpora are stored by their identity
        a, b = _labelled(ledger, f"main-{annotator}", annotator, "main", units, labelled_on, partition, psha, task, main_guide or guide_sha, retained, choose, main_assignment_edit)
        main_assignments[a["assignmentId"]], main_batches = a, main_batches + [b]
    adjudications, adjudication_shas = [], []
    if conflicts:
        documents = [b for b, _ in main_batches]
        units = sorted({unit_key("track", u[1], None) for u in main_units if _conflicting_choice({"trackId": u[1]}, "person-backpack") != _choice({"trackId": u[1]}, "person-backpack") and corpus.tracks[u[1]].object_class == "person"})
        shown = documents if conflicts == "genuine" else documents[:1]  # "forged": only ann-a's labels
        packet = build_reveal_packet("reveal-main", "ann-a", units, "main", shown)
        if conflicts == "genuine":
            ledger.issue_reveal(packet, documents, T0)
        else:  # written straight into the ledger, bypassing issue_reveal's completeness check
            full = build_reveal_packet("reveal-main", "ann-a", units, "main", documents)
            ledger.append("reveal-issued", {"packetId": packet["packetId"], "recipientId": "ann-a", "phase": "main", "units": units, "packetSha256": document_sha256(packet), "conflictKeys": full["conflictKeys"], "reasonConflictKeys": []}, T0)
        adjudication = {
            "schemaVersion": "mavi-attribute-adjudication-v1", "adjudicationId": "adj-main", "adjudicatorId": "ann-a", "revealPacketSha256": document_sha256(packet), "decidedAt": T0,
            "decisions": [{"unit": u, "attributeType": "person-backpack", "outcome": "value", "value": "absent", "unscorableReason": None, "rationale": "strap only"} for u in units],
        }
        ledger.record_adjudication(adjudication, T0)
        object_class = {unit_key(u["unitKind"], u["trackId"], u["observationId"]): u["objectClass"] for a in main_assignments.values() for u in a["units"]}
        adjudications = [parse_adjudication(adjudication, task, object_class)]
        adjudication_shas = [document_sha256(adjudication)]
        retained.extend([packet, adjudication])
    adjudicated = {key for decisions in adjudications for key in decisions}
    main = agreement_report("main", corpus, partition, psha, task.sha256, main_batches, main_assignments, ledger.annotators(), adjudicated, set(ledger.batch_hashes()))
    truth = build_ground_truth(corpus, partition, psha, task, main_batches, adjudications, ledger, main_assignments)
    evaluation, frozen = split_ground_truth(truth, None)
    sealing = seal
    seal = build_seal(corpus, partition, psha, frozen, evaluation, ledger.head, "custodian-1", T0, "held by the custodian outside the evaluation environment")
    if sealing:
        ledger.record_seal(seal, corpus, partition, T0)
        log = open_access_log(store / ACCESS_LOG, seal, T0, create=True)
    sealed_view = seal_evaluation_view(evaluation, seal)
    custody = tmp / "custody"
    custody.mkdir()
    write_canonical(custody / "frozen.json", frozen)
    write_canonical(custody / "evaluation.json", evaluation)
    write_canonical(custody / "corpus.json", raw_corpus)
    write_canonical(custody / "partition.json", partition)

    for name, document in (
        (corpus.sha256, raw_corpus), (recurrence_doc_sha, recurrence), (duplicate_sha, duplicates), (psha, partition),
        (document_sha256(pilot), pilot), (task.sha256, frozen_doc), (document_sha256(main), main),
        (document_sha256(seal), seal), (document_sha256(sealed_view), sealed_view),
        *((document_sha256(d), d) for d in retained),
    ):
        write_canonical(store / f"{name}.json", document)
    record = json.loads(COMMITTED.read_text())
    record["annotationGuide"] = {"path": "guide.md", "frozenSha256": guide_sha}
    record["attributeTask"]["frozenSha256"] = task.sha256
    record["corpus"] = {"corpusKind": kind, "corpusManifestSha256": corpus.sha256, "partitionManifestSha256": psha, "recurrenceAuditSha256": recurrence_doc_sha, "duplicateAuditSha256": duplicate_sha}
    record["labelling"] = {"pilotReportSha256": document_sha256(pilot), "mainAgreementReportSha256": document_sha256(main), "adjudicationSha256s": adjudication_shas, "groundTruthSha256": document_sha256(sealed_view), "annotationLedgerHead": ledger.head}
    record["seal"] = {"sealSha256": document_sha256(seal), "accessLogHead": log.head} if sealing else {"sealSha256": None, "accessLogHead": None}
    record["limitations"] = list(partition["checks"]["limitations"])
    record["custodian"] = "custodian-1"
    if context is not None:
        context.update(
            corpus=corpus, links=recurrence_links + duplicate_links, recurrence=recurrence, guide_sha=guide_sha, hashes={"recurrence": recurrence_sha, "duplicate": duplicate_sha},
            ledger=ledger, task=task, partition=partition, main_batches=main_batches, main_assignments=main_assignments, pilot_units=pilot_units, seal=seal,
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
    superseding = [*_seal_args(tmp_path, store, "new.jsonl", "new-seal.json"), "--supersedes", str(old), "--supersedes-reason", "compromised in S2c.3", "--superseded-access-log", str(store / ACCESS_LOG), "--superseded-partition", str(tmp_path / "custody" / "partition.json")]
    assert main(superseding) == 2, "the same frozen set cannot be re-sealed"
    assert not (tmp_path / "custody" / "new.jsonl").exists()
    assert AnnotationLedger(store / ANNOTATION_LEDGER).seals()[-1]["sealSha256"] == record["seal"]["sealSha256"]


def test_f1_refuses_a_seal_the_ledger_does_not_name_as_latest(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    seal = json.loads((store / f"{record['seal']['sealSha256']}.json").read_text())
    newer = dict(seal, custodyNote="a later seal", supersedes={"sealSha256": document_sha256(seal), "reason": "later"})
    # A hand-made ledger entry for a later seal (the tool itself would refuse the reuse).
    AnnotationLedger(store / ANNOTATION_LEDGER).append("seal-created", {"sealSha256": document_sha256(newer), "membersSha256": newer["frozenMembers"]["membersSha256"], "frozenTrackIds": [], "supersedes": document_sha256(seal)}, T0)
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
    with pytest.raises(CorpusError, match="ledger_seal_members_not_reproducible"):
        ledger.record_seal(seal, corpus, partition, T0)
    # Bypassing the tool with a hand-made ledger entry does not help: F1 recomputes.
    ledger.append("seal-created", {"sealSha256": document_sha256(seal), "membersSha256": seal["frozenMembers"]["membersSha256"], "frozenTrackIds": [], "supersedes": None}, T0)
    log = open_access_log(store / ACCESS_LOG, seal, T0, create=True)
    view = seal_evaluation_view(evaluation, seal)
    for document in (seal, view):
        write_canonical(store / f"{document_sha256(document)}.json", document)
    record["seal"] = {"sealSha256": document_sha256(seal), "accessLogHead": log.head}
    record["labelling"]["groundTruthSha256"] = document_sha256(view)
    with pytest.raises(CorpusError, match="f1_seal_members_not_reproducible"):
        f1_verdict(record, tmp_path, store)


def test_f1_needs_double_labels_for_every_task_attribute(tmp_path) -> None:
    """A frozen-task attribute labelled by one annotator only in main: F1 stays OPEN."""
    record, store = build_chain(tmp_path, single_labelled_class="vehicle")
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


def test_r1_recovery_needs_new_footage_and_then_reaches_pass(tmp_path) -> None:
    """Compromise → corpus revision adding a new site → labelling of the new Tracks →
    re-partition that keeps every previously exposed Track out of the frozen test →
    superseding seal. The whole chain re-verifies to PASS."""
    ctx: dict = {}
    record, store = build_chain(tmp_path, context=ctx)
    old_corpus, task, old_partition = ctx["corpus"], ctx["task"], ctx["partition"]
    old_seal = ctx["seal"]
    old_sha = document_sha256(old_seal)
    declare_improper_access(open_access_log(store / ACCESS_LOG, old_seal, T0), old_seal, "engineer-1", "S2c.3", "opened while debugging", T0)
    assert f1_verdict(record, tmp_path, store)["computed"] == "OPEN"
    (store / ACCESS_LOG).rename(store / f"frozen-access-log-{old_sha}.jsonl")
    old_log = Ledger(store / f"frozen-access-log-{old_sha}.jsonl")

    # New footage: a fifth site, as a corpus revision (the old Tracks keep their identity).
    raw = build_corpus(sites=5, cameras_per_site=3, days=12, tracks_per_source=4, kind="operational")
    raw.update(revision=2, supersedes=old_corpus.sha256)
    corpus = revise_corpus(old_corpus, raw)
    recurrence = {"schemaVersion": "mavi-attribute-recurrence-audit-v1", "corpusManifestSha256": corpus.sha256, "groups": []}
    recurrence_sha, recurrence_links = parse_recurrence(recurrence, corpus)
    duplicates = build_duplicate_audit(corpus, {o: sha("fp", o)[:16] for o in sorted(corpus.observations)}, 6)
    duplicate_sha, duplicate_links = parse_duplicate_audit(duplicates, corpus)
    links, hashes = recurrence_links + duplicate_links, {"recurrence": recurrence_sha, "duplicate": duplicate_sha}
    pilot = sorted(u[1] for u in ctx["pilot_units"])
    exposed = sorted(a["trackId"] for a in old_partition["assignments"])

    # Without excluding the exposed Tracks, old Tracks land in the frozen test: refused.
    careless = build_partition(corpus, policy(seed="new-1", pinnedTrainingTrackIds=pilot), links, hashes)
    assert set(exposed) & {m["trackId"] for m in frozen_members(corpus, careless)}

    partition = build_partition(corpus, policy(seed="new-1", pinnedTrainingTrackIds=pilot, excludedFromFrozenTrackIds=exposed), links, hashes)
    psha = document_sha256(partition)
    assert not partition["checks"]["limitations"]
    ledger = AnnotationLedger(store / ANNOTATION_LEDGER)
    retained: list[dict] = []
    new_units = [("track", t, None) for t in sorted(set(corpus.tracks) - set(old_corpus.tracks))]
    assignments, batches = dict(ctx["main_assignments"]), list(ctx["main_batches"])
    for annotator in ("ann-a", "ann-b"):
        a, b = _labelled(ledger, f"main2-{annotator}", annotator, "main", new_units, corpus, partition, psha, task, record["annotationGuide"]["frozenSha256"], retained)
        assignments[a["assignmentId"]], batches = a, batches + [b]
    main = agreement_report("main", corpus, partition, psha, task.sha256, batches, assignments, ledger.annotators(), set(), set(ledger.batch_hashes()))
    evaluation, frozen = split_ground_truth(build_ground_truth(corpus, partition, psha, task, batches, [], ledger, assignments), None)

    def superseding(on_partition, frozen_view, evaluation_view):
        return build_seal(corpus, on_partition, document_sha256(on_partition), frozen_view, evaluation_view, ledger.head, "custodian-1", T0, "new frozen set", {"sealSha256": old_sha, "reason": "compromised in S2c.3"})

    c_eval, c_frozen = split_ground_truth(build_ground_truth(corpus, careless, document_sha256(careless), task, batches, [], ledger, assignments), None)
    careless_seal = superseding(careless, c_frozen, c_eval)
    with pytest.raises(CorpusError, match="seal_frozen_tracks_previously_exposed"):
        verify_superseding_seal(careless_seal, old_seal, old_log, old_corpus, old_partition, careless, corpus)
    with pytest.raises(CorpusError, match="ledger_seal_(reuses_earlier|frozen_tracks_previously_exposed)"):
        ledger.check_seal(careless_seal, corpus, careless)

    # Excluding only the old frozen Tracks is not enough: Tracks that were in training,
    # tuning or selection were exposed too. The ledger refuses; a hand-made entry fails F1.
    old_frozen = sorted(m["trackId"] for m in frozen_members(old_corpus, old_partition))
    half = build_partition(corpus, policy(seed="new-0", dateBlockDays=2, pinnedTrainingTrackIds=pilot, excludedFromFrozenTrackIds=old_frozen), links, hashes)
    half_frozen = {m["trackId"] for m in frozen_members(corpus, half)}
    assert half_frozen & set(exposed) and not half_frozen & set(old_frozen)
    h_eval, h_frozen = split_ground_truth(build_ground_truth(corpus, half, document_sha256(half), task, batches, [], ledger, assignments), None)
    half_seal = superseding(half, h_frozen, h_eval)
    with pytest.raises(CorpusError, match="ledger_seal_frozen_tracks_previously_exposed"):
        ledger.check_seal(half_seal, corpus, half)
    store2 = tmp_path / "store2"
    shutil.copytree(store, store2)
    ledger2 = AnnotationLedger(store2 / ANNOTATION_LEDGER)
    ledger2.append("seal-created", {"sealSha256": document_sha256(half_seal), "membersSha256": half_seal["frozenMembers"]["membersSha256"],
                                    "frozenTrackIds": sorted(half_frozen), "exposedTrackIds": sorted(a["trackId"] for a in half["assignments"]), "supersedes": old_sha}, T0)
    half_log = open_access_log(store2 / ACCESS_LOG, half_seal, T0, create=True)
    half_view = seal_evaluation_view(h_eval, half_seal)
    half_main = agreement_report("main", corpus, half, document_sha256(half), task.sha256, batches, assignments, ledger.annotators(), set(), set(ledger.batch_hashes()))
    half_recurrence = {**recurrence, "recallSample": reviewed_recall_sample(corpus, half, recurrence_links)}
    for name, document in ((corpus.sha256, raw), (recurrence_document_sha256(half_recurrence), half_recurrence), (duplicate_sha, duplicates), *((document_sha256(d), d) for d in (half, partition, half_main, half_seal, half_view, *retained))):
        write_canonical(store2 / f"{name}.json", document)
    half_record = json.loads(json.dumps(record))
    half_record["corpus"] = {"corpusKind": "operational", "corpusManifestSha256": corpus.sha256, "partitionManifestSha256": document_sha256(half), "recurrenceAuditSha256": recurrence_document_sha256(half_recurrence), "duplicateAuditSha256": duplicate_sha}
    half_record["labelling"].update(mainAgreementReportSha256=document_sha256(half_main), groundTruthSha256=document_sha256(half_view), annotationLedgerHead=ledger2.head)
    half_record["seal"] = {"sealSha256": document_sha256(half_seal), "accessLogHead": half_log.head}
    half_record["limitations"] = list(half["checks"]["limitations"])
    with pytest.raises(CorpusError, match="f1_seal_frozen_tracks_previously_exposed"):
        f1_verdict(half_record, tmp_path, store2)

    seal = superseding(partition, frozen, evaluation)
    verify_superseding_seal(seal, old_seal, old_log, old_corpus, old_partition, partition, corpus)
    new_log = open_access_log(store / ACCESS_LOG, seal, T0, create=True)
    ledger.record_seal(seal, corpus, partition, T0)
    view = seal_evaluation_view(evaluation, seal)
    recurrence["recallSample"] = reviewed_recall_sample(corpus, partition, recurrence_links)
    for name, document in ((corpus.sha256, raw), (recurrence_document_sha256(recurrence), recurrence), (duplicate_sha, duplicates), *((document_sha256(d), d) for d in (partition, main, seal, view, *retained))):
        write_canonical(store / f"{name}.json", document)
    record["corpus"] = {"corpusKind": "operational", "corpusManifestSha256": corpus.sha256, "partitionManifestSha256": psha, "recurrenceAuditSha256": recurrence_document_sha256(recurrence), "duplicateAuditSha256": duplicate_sha}
    record["labelling"]["mainAgreementReportSha256"] = document_sha256(main)
    record["labelling"]["groundTruthSha256"] = document_sha256(view)
    record["labelling"]["annotationLedgerHead"] = ledger.head
    record["seal"] = {"sealSha256": document_sha256(seal), "accessLogHead": new_log.head}
    record["limitations"] = list(partition["checks"]["limitations"])
    assert f1_verdict(record, tmp_path, store) == {"computed": "PASS", "claimed": "OPEN", "missing": []}

    # F1 walks the seal chain: the superseded seal's log must be retained and compromised.
    a_log = store / f"frozen-access-log-{old_sha}.jsonl"
    kept = a_log.read_text()
    a_log.unlink()
    with pytest.raises(CorpusError, match=f"f1_ledger_missing:frozen-access-log-{old_sha}"):
        f1_verdict(record, tmp_path, store)
    a_log.write_text(kept.splitlines()[0] + "\n")  # only seal-created: an intact seal
    with pytest.raises(CorpusError, match="f1_superseded_seal_not_compromised"):
        f1_verdict(record, tmp_path, store)
    a_log.write_text(kept)
    # Labels recorded after the sealed ground truth make the sealed truth incomplete.
    ledger.register_annotator("ann-late", True, T0)
    late = build_assignment("late-1", "ann-late", "main", "independent", new_units[:1], corpus, partition, psha, task, record["annotationGuide"]["frozenSha256"])
    ledger.issue_assignment(late, T0)
    write_canonical(store / f"{document_sha256(late)}.json", late)
    with pytest.raises(CorpusError, match="f1_labels_recorded_after_sealed_ground_truth"):
        f1_verdict(record, tmp_path, store)


def test_the_seal_must_carry_its_ground_truth_ledger_head(tmp_path) -> None:
    ctx: dict = {}
    build_chain(tmp_path, seal=False, context=ctx)
    custody = tmp_path / "custody"
    corpus = ctx["corpus"]
    partition = json.loads((custody / "partition.json").read_text())
    ledger = ctx["ledger"]
    ledger.register_annotator("ann-late", True, T0)  # the ledger moved on after the ground truth
    with pytest.raises(CorpusError, match="seal_ledger_head_differs_from_ground_truth"):
        build_seal(corpus, partition, document_sha256(partition), json.loads((custody / "frozen.json").read_text()), json.loads((custody / "evaluation.json").read_text()), ledger.head, "custodian-1", T0, "x")


def test_f1_re_derives_the_frozen_task_from_the_owner_decision(tmp_path) -> None:
    """A retained frozen task that names the real candidate, pilot and decision but adds
    anything else is refused, even before labels are checked."""
    record, store = build_chain(tmp_path)
    task = json.loads((store / f"{record['attributeTask']['frozenSha256']}.json").read_text())
    colour = next(a for a in task["attributes"] if a["kind"] == "categorical")
    colour["values"] = sorted([*colour["values"], "teal"])
    write_canonical(store / f"{document_sha256(task)}.json", task)
    record["attributeTask"]["frozenSha256"] = document_sha256(task)
    with pytest.raises(CorpusError, match="f1_frozen_task_not_reproducible"):
        f1_verdict(record, tmp_path, store)


def test_a_failed_seal_leaves_no_ledger_entry_and_can_be_retried(tmp_path, capsys) -> None:
    record, store = build_chain(tmp_path, seal=False)
    bad = _seal_args(tmp_path, store, "no-such-dir/access.jsonl", "seal.json")
    assert main(bad) == 2
    assert "seal_output_directory_missing" in capsys.readouterr().err
    assert AnnotationLedger(store / ANNOTATION_LEDGER).seals() == []
    assert main(_seal_args(tmp_path, store, "access.jsonl", "seal.json")) == 0
    assert len(AnnotationLedger(store / ANNOTATION_LEDGER).seals()) == 1


def test_a_forged_but_self_consistent_pilot_report_is_refused(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    document = json.loads((store / f"{record['labelling']['pilotReportSha256']}.json").read_text())
    document["timing"]["activeSeconds"] += 1
    del document["reportSha256"]
    document["reportSha256"] = document_sha256(document)
    write_canonical(store / f"{document_sha256(document)}.json", document)
    record["labelling"]["pilotReportSha256"] = document_sha256(document)
    with pytest.raises(CorpusError, match="f1_pilot_report_not_reproducible"):
        f1_verdict(record, tmp_path, store)


def test_f1_refuses_a_ledger_seal_entry_that_misstates_the_frozen_tracks(tmp_path) -> None:
    """The ledger's frozenTrackIds drive the no-reuse rule, so F1 recomputes them."""
    ctx: dict = {}
    record, store = build_chain(tmp_path, seal=False, context=ctx)
    seal, corpus, partition, ledger = ctx["seal"], ctx["corpus"], ctx["partition"], ctx["ledger"]
    ledger.append("seal-created", {"sealSha256": document_sha256(seal), "membersSha256": seal["frozenMembers"]["membersSha256"], "frozenTrackIds": [], "supersedes": None}, T0)
    log = open_access_log(store / ACCESS_LOG, seal, T0, create=True)
    view = seal_evaluation_view(json.loads((tmp_path / "custody" / "evaluation.json").read_text()), seal)
    write_canonical(store / f"{document_sha256(view)}.json", view)
    record["seal"] = {"sealSha256": document_sha256(seal), "accessLogHead": log.head}
    record["labelling"]["groundTruthSha256"] = document_sha256(view)
    with pytest.raises(CorpusError, match="f1_seal_ledger_members_mismatch"):
        f1_verdict(record, tmp_path, store)



# ---- trust boundaries (fifth review round) ---------------------------------------------------


def test_f1_refuses_an_abandoned_pilot_assignment(tmp_path) -> None:
    record, store = build_chain(tmp_path, abandoned_pilot=True)
    with pytest.raises(CorpusError, match="ledger_assignments_unsubmitted:pilot:1"):
        f1_verdict(record, tmp_path, store)


def test_f1_accepts_a_genuine_reveal_and_adjudication(tmp_path) -> None:
    record, store = build_chain(tmp_path, conflicts="genuine")
    assert record["labelling"]["adjudicationSha256s"]
    assert f1_verdict(record, tmp_path, store)["computed"] == "PASS"


def test_f1_refuses_an_adjudication_built_on_an_incomplete_reveal(tmp_path) -> None:
    """A packet showing only the favourable annotator, forged straight into the ledger."""
    record, store = build_chain(tmp_path, conflicts="forged")
    with pytest.raises(CorpusError, match="ledger_reveal_packet_not_canonical|f1_reveal_packet_not_reproducible"):
        f1_verdict(record, tmp_path, store)


def test_f1_refuses_a_frozen_task_that_keeps_what_the_pilot_failed(tmp_path) -> None:
    def disagree(unit, attribute):
        base = _choice(unit, attribute)
        if attribute == "person-bag" and base[0] == "value":
            return ("value", "absent" if base[1] == "present" else "present", None)
        return base

    record, store = build_chain(tmp_path, pilot_choose_b=disagree, forge_freeze=True)
    with pytest.raises(CorpusError, match="freeze_failing_attribute_retained:person-bag"):
        f1_verdict(record, tmp_path, store)


def test_the_recall_sample_is_reproducible_from_seed_and_inputs(tmp_path) -> None:
    ctx: dict = {}
    build_chain(tmp_path, context=ctx)
    corpus, partition = ctx["corpus"], ctx["partition"]
    links = ctx["links"]
    first = draw_recall_sample(corpus, partition, 25)
    assert first == draw_recall_sample(corpus, partition, 25)
    # Seed and population come only from the corpus, the Track assignments and the confirmed
    # groups: an edit that moves no Track (a rejected group's note, say) draws the same pairs.
    renamed = dict(partition, policy={**partition["policy"], "policyId": "renamed-policy"})
    assert draw_recall_sample(corpus, renamed, 25) == first
    # A larger sample extends the smaller one, so regrowing cannot push a found pair out.
    assert draw_recall_sample(corpus, partition, 40)["pairs"][:25] == first["pairs"]
    parts = {a["trackId"]: a["partition"] for a in partition["assignments"]}
    for pair in first["pairs"]:
        a, b = pair["trackIds"]
        assert parts[a] != parts[b] and corpus.tracks[a].object_class == corpus.tracks[b].object_class


def _with_sample(record, store, mutate):
    audit = json.loads((store / f"{record['corpus']['recurrenceAuditSha256']}.json").read_text())
    mutate(audit["recallSample"])
    write_canonical(store / f"{recurrence_document_sha256(audit)}.json", audit)
    record["corpus"]["recurrenceAuditSha256"] = recurrence_document_sha256(audit)
    return record


def test_an_altered_or_foreign_recall_pair_is_refused(tmp_path) -> None:
    record, store = build_chain(tmp_path)

    def swap(sample):  # a pair the method never drew, with a decision on it
        first, second = sample["pairs"][0]["trackIds"][0], sample["pairs"][1]["trackIds"][1]
        sample["pairs"][0] = {"trackIds": sorted([first, second]), "decision": "not-recurrence"}

    with pytest.raises(CorpusError, match="f1_recall_sample_not_reproducible"):
        f1_verdict(_with_sample(record, store, swap), tmp_path, store)
    (tmp_path / "again").mkdir()
    record, store2 = build_chain(tmp_path / "again")
    with pytest.raises(CorpusError, match="f1_recall_sample_population_mismatch"):
        f1_verdict(_with_sample(record, store2, lambda s: s.update(populationSha256="1" * 64)), tmp_path / "again", store2)


def test_a_count_only_recall_claim_is_refused(tmp_path) -> None:
    record, store = build_chain(tmp_path)

    def counts_only(sample):
        for key in ("pairs", "populationSha256", "method", "seed"):
            sample.pop(key)
        sample.update(sampledPairs=200, missedRecurrences=0)

    with pytest.raises(CorpusError, match="recurrence_invalid:recallSample"):
        f1_verdict(_with_sample(record, store, counts_only), tmp_path, store)


def test_a_found_recurrence_not_propagated_keeps_f1_open(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    verdict = f1_verdict(_with_sample(record, store, lambda s: s["pairs"][3].update(decision="recurrence")), tmp_path, store)
    assert verdict["computed"] == "OPEN"
    assert verdict["missing"] == ["recurrence re-audit: the recall sample found 1 recurrences missing from the audit (add them, re-partition, re-sample)"]
    (tmp_path / "unreviewed").mkdir()
    record, store2 = build_chain(tmp_path / "unreviewed")
    verdict = f1_verdict(_with_sample(record, store2, lambda s: s["pairs"][0].update(decision=None)), tmp_path / "unreviewed", store2)
    assert verdict["missing"] == ["recall sample: 1 sampled pairs not reviewed"]


def test_a_failed_seal_write_leaves_nothing_behind_and_retries_cleanly(tmp_path, monkeypatch) -> None:
    """P3-1: a write failure after the access log was prepared leaves no partial artefact."""
    from attributes.corpus import cli

    record, store = build_chain(tmp_path, seal=False)
    custody = tmp_path / "custody"
    real = cli.write_canonical

    def failing(path, document):
        if "sealed-" in path.name:
            raise OSError(28, "No space left on device", str(path))
        return real(path, document)

    monkeypatch.setattr(cli, "write_canonical", failing)
    args = _seal_args(tmp_path, store, "access.jsonl", "seal.json")
    assert main(args) == 2
    assert sorted(p.name for p in custody.iterdir()) == ["corpus.json", "evaluation.json", "frozen.json", "partition.json"]
    assert AnnotationLedger(store / ANNOTATION_LEDGER).seals() == []
    monkeypatch.setattr(cli, "write_canonical", real)
    assert main(args) == 0
    assert (custody / "access.jsonl").exists() and len(AnnotationLedger(store / ANNOTATION_LEDGER).seals()) == 1



# ---- second focused review ---------------------------------------------------------------------


def test_a_tiny_or_reseeded_recall_sample_does_not_pass(tmp_path) -> None:
    record, store = build_chain(tmp_path, recall_size=1)
    assert f1_verdict(record, tmp_path, store)["missing"] == [f"recall sample of exactly {RECALL_SAMPLE_PAIRS} reviewed pairs (has 1)"]
    (tmp_path / "again").mkdir()
    record, store2 = build_chain(tmp_path / "again")
    with pytest.raises(CorpusError, match="f1_recall_sample_seed_not_derived"):
        f1_verdict(_with_sample(record, store2, lambda s: s.update(seed="recall-sample-v1:chosen")), tmp_path / "again", store2)


def test_the_candidate_behind_the_pilot_must_be_the_committed_one(tmp_path) -> None:
    def lowered(document):
        document["pilotDecisionRules"]["minimumValueAlpha"] = -1.0

    record, store = build_chain(tmp_path, candidate_edit=lowered)
    with pytest.raises(CorpusError, match="candidate_rules_lowered:minimumValueAlpha"):
        f1_verdict(record, tmp_path, store)
    (tmp_path / "share").mkdir()
    record, store2 = build_chain(tmp_path / "share", candidate_edit=lambda d: d["pilotDecisionRules"].update(mergeConfusionShare=0.0))
    with pytest.raises(CorpusError, match="candidate_rules_changed:mergeConfusionShare"):
        f1_verdict(record, tmp_path / "share", store2)
    (tmp_path / "vocab").mkdir()

    def more_colours(document):
        entry = next(a for a in document["attributes"] if a["attributeType"] == "vehicle-colour")
        entry["values"] = sorted([*entry["values"], "teal"])

    record, store3 = build_chain(tmp_path / "vocab", candidate_edit=more_colours)
    with pytest.raises(CorpusError, match="candidate_differs_from_committed"):
        f1_verdict(record, tmp_path / "vocab", store3)


def test_seal_never_overwrites_an_existing_output(tmp_path, capsys) -> None:
    record, store = build_chain(tmp_path, seal=False)
    custody = tmp_path / "custody"
    (custody / "seal.json").write_text("{\"kept\": true}\n")
    assert main(_seal_args(tmp_path, store, "access.jsonl", "seal.json")) == 2
    assert "seal_output_exists:seal.json" in capsys.readouterr().err
    assert (custody / "seal.json").read_text() == "{\"kept\": true}\n" and not (custody / "access.jsonl").exists()


def test_f1_replays_the_ledger_and_refuses_a_hand_written_cancellation(tmp_path) -> None:
    """The ledger's own completeness check is fooled by the forged entry; only the replay of
    the cancellation rule refuses it."""
    record, store = build_chain(tmp_path, abandoned_pilot="forged-cancellation")
    with pytest.raises(CorpusError, match="ledger_cancel_replacement_(mismatch|not_fresh)"):
        f1_verdict(record, tmp_path, store)


def test_a_failed_ledger_append_leaves_no_partial_entry_and_the_seal_retries(tmp_path, monkeypatch) -> None:
    """The final seal-created append fails (disk full at fsync): the annotation ledger is
    truncated back, every seal output is removed, and a retry succeeds."""
    from attributes.corpus import ledger as ledger_module

    record, store = build_chain(tmp_path, seal=False)
    before = (store / ANNOTATION_LEDGER).read_bytes()
    real, calls = ledger_module.os.fsync, []

    def failing(fd):
        calls.append(fd)
        if len(calls) == 2:  # 1: the new access log's first entry; 2: seal-created
            raise OSError(28, "No space left on device")
        return real(fd)

    monkeypatch.setattr(ledger_module.os, "fsync", failing)
    args = _seal_args(tmp_path, store, "access.jsonl", "seal.json")
    assert main(args) == 2
    assert (store / ANNOTATION_LEDGER).read_bytes() == before
    Ledger(store / ANNOTATION_LEDGER)  # still a verifiable chain
    assert not (tmp_path / "custody" / "access.jsonl").exists() and not (tmp_path / "custody" / "seal.json").exists()
    monkeypatch.setattr(ledger_module.os, "fsync", real)
    assert main(args) == 0
    assert len(AnnotationLedger(store / ANNOTATION_LEDGER).seals()) == 1


def test_a_rejected_group_nonce_cannot_regenerate_the_recall_sample(tmp_path) -> None:
    """Adding a rejected recurrence group changes the audit and partition hashes but moves no
    Track: the derived seed, the population and the pairs stay the same."""
    ctx: dict = {}
    build_chain(tmp_path, context=ctx)
    corpus, partition, links = ctx["corpus"], ctx["partition"], ctx["links"]
    audit = dict(ctx["recurrence"])
    audit.pop("recallSample", None)
    two = sorted(corpus.tracks)[:2]
    audit["groups"] = [{"groupId": "nonce-1", "subjectKind": corpus.tracks[two[0]].object_class, "trackIds": two, "status": "rejected",
                        "proposer": {"kind": "reviewer", "family": None}, "decision": {"by": "reviewer-1", "date": "2026-10-02", "note": "nonce 8f3a"}}]
    if corpus.tracks[two[0]].object_class != corpus.tracks[two[1]].object_class:
        pytest.skip("fixture Tracks differ in class")
    groups_sha, new_links = parse_recurrence(audit, corpus)
    assert groups_sha != ctx["hashes"]["recurrence"]
    rebuilt = build_partition(corpus, partition["policy"], new_links + [l for l in links if l.kind == "duplicate"], {"recurrence": groups_sha, "duplicate": ctx["hashes"]["duplicate"]})
    assert document_sha256(rebuilt) != document_sha256(partition) and rebuilt["assignments"] == partition["assignments"]
    assert draw_recall_sample(corpus, rebuilt, 50) == draw_recall_sample(corpus, partition, 50)


def test_the_candidate_path_is_pinned_to_the_committed_candidate(tmp_path) -> None:
    record, store = build_chain(tmp_path)
    record["attributeTask"]["candidatePath"] = "guide.md"
    with pytest.raises(CorpusError, match="f1_candidate_path_not_the_committed_candidate"):
        f1_verdict(record, tmp_path, store)



# ---- independent re-review of 6e3fe74 ------------------------------------------------------------


def test_an_edited_assignment_that_drops_attributes_is_refused(tmp_path) -> None:
    """Units may not quietly lose attributes (for example on frozen-test Tracks)."""
    def drop(assignment):
        for unit in assignment["units"]:
            if unit["objectClass"] == "person":
                unit["attributeTypes"] = unit["attributeTypes"][:2]

    record, store = build_chain(tmp_path, main_assignment_edit=drop)
    with pytest.raises(CorpusError, match="f1_assignment_not_reproducible"):
        f1_verdict(record, tmp_path, store)


def test_labels_on_other_imagery_do_not_count(tmp_path) -> None:
    """Main labels made on a corpus revision whose crops differ from the final corpus's."""
    def reextracted(raw):
        raw["revision"] = 2
        raw["supersedes"] = "c" * 64
        raw["tracks"][0]["observations"][0]["sha256"] = "d" * 64

    record, store = build_chain(tmp_path, main_corpus_edit=reextracted)
    with pytest.raises(CorpusError, match="f1_labelled_imagery_changed"):
        f1_verdict(record, tmp_path, store)


def test_a_confirmed_group_inside_one_partition_cannot_reseed_the_recall_sample(tmp_path) -> None:
    ctx: dict = {}
    build_chain(tmp_path, context=ctx)
    corpus, partition, links = ctx["corpus"], ctx["partition"], ctx["links"]
    parts = {a["trackId"]: a["partition"] for a in partition["assignments"]}
    by_partition = {}
    pair = None
    for track in sorted(corpus.tracks):
        key = (parts[track], corpus.tracks[track].object_class)
        if key in by_partition:
            pair = [by_partition[key], track]
            break
        by_partition[key] = track
    audit = dict(ctx["recurrence"])
    audit.pop("recallSample", None)
    audit["groups"] = [{"groupId": "same-side", "subjectKind": corpus.tracks[pair[0]].object_class, "trackIds": sorted(pair), "status": "confirmed",
                        "proposer": {"kind": "reviewer", "family": None}, "decision": {"by": "reviewer-1", "date": "2026-10-02", "note": "same person, same partition"}}]
    groups_sha, new_links = parse_recurrence(audit, corpus)
    rebuilt = build_partition(corpus, partition["policy"], new_links + [l for l in links if l.kind == "duplicate"], {"recurrence": groups_sha, "duplicate": ctx["hashes"]["duplicate"]})
    assert rebuilt["assignments"] == partition["assignments"]
    assert draw_recall_sample(corpus, rebuilt) == draw_recall_sample(corpus, partition)


def test_a_recall_sample_larger_than_the_fixed_size_is_refused(tmp_path) -> None:
    """A free, larger size would let a reviewer draw more pairs and stop before a found one."""
    record, store = build_chain(tmp_path, recall_size=RECALL_SAMPLE_PAIRS + 50)
    assert f1_verdict(record, tmp_path, store)["missing"] == [f"recall sample of exactly {RECALL_SAMPLE_PAIRS} reviewed pairs (has {RECALL_SAMPLE_PAIRS + 50})"]



def test_labels_on_a_track_whose_class_changed_do_not_count(tmp_path) -> None:
    def reclassified(raw):
        raw["revision"] = 2
        raw["supersedes"] = "c" * 64
        track = raw["tracks"][0]
        track["objectClass"] = "vehicle" if track["objectClass"] == "person" else "person"

    record, store = build_chain(tmp_path, main_corpus_edit=reclassified)
    with pytest.raises(CorpusError, match="f1_labelled_imagery_changed|f1_assignment_not_reproducible"):
        f1_verdict(record, tmp_path, store)
