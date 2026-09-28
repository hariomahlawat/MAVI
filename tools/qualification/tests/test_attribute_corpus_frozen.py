"""S2c.1: frozen-test seal, access log, invalidation, corpus report and the F1 checker."""

from __future__ import annotations

import copy
import json

import pytest
from attribute_corpus_fixtures import build_corpus, frozen_task, policy

from attributes.corpus import task as task_module
from attributes.corpus.annotation import (
    AnnotationLedger,
    load_evaluation_view,
    build_assignment,
    build_batch,
    build_ground_truth,
    parse_batch,
    split_ground_truth,
)
from attributes.corpus.canonical import CorpusError, document_sha256, write_canonical
from attributes.corpus.frozen import (
    access_frozen,
    build_seal,
    declare_improper_access,
    open_access_log,
    seal_evaluation_view,
    seal_status,
    verify_superseding_seal,
)
from attributes.corpus.ledger import Ledger
from attributes.corpus.manifest import parse_corpus
from attributes.corpus.partition import build_partition
from attributes.corpus.report import corpus_report, render_markdown
from attributes.corpus.task import load_task, parse_task

T0 = "2026-10-20T09:00:00Z"
GUIDE = "d" * 64


def _frozen_task(candidate):
    return frozen_task(candidate)


def _choice(unit, attribute):
    if attribute == "subject-validity":
        return ("value", "valid", None)
    if attribute.endswith("colour"):
        return ("value", "black", None)
    return ("value", "absent", None)


@pytest.fixture()
def sealed(tmp_path):
    corpus = parse_corpus(build_corpus(sites=4, cameras_per_site=3, days=12, tracks_per_source=1))
    partition = build_partition(corpus, policy(), [], {"recurrence": None, "duplicate": None})
    psha = document_sha256(partition)
    candidate = parse_task(task_module.confirm_rules(load_task().document, "owner-1", "2026-10-01T09:00:00Z"))
    task = _frozen_task(candidate)
    ledger = AnnotationLedger(tmp_path / "ledger.jsonl")
    ledger.register_annotator("ann-a", True, T0)
    units = [("track", t, None) for t in sorted(corpus.tracks)]
    assignment = build_assignment("main-a", "ann-a", "main", "single", units, corpus, partition, psha, task, GUIDE)
    ledger.issue_assignment(assignment, T0)
    batch = build_batch("batch-main-a", assignment, T0, [
        {"unitKind": u["unitKind"], "trackId": u["trackId"], "observationId": None, "attributeType": a, "outcome": _choice(u, a)[0], "value": _choice(u, a)[1], "unscorableReason": _choice(u, a)[2]}
        for u in assignment["units"] for a in u["attributeTypes"]
    ], None, task)
    ledger.submit_batch(batch, assignment, T0)
    truth = build_ground_truth(corpus, partition, psha, task, [(batch, parse_batch(batch, assignment, task))], [], ledger, {assignment["assignmentId"]: assignment})
    evaluation, frozen = split_ground_truth(truth, None)
    frozen_path = tmp_path / "custody" / "frozen-ground-truth.json"
    frozen_path.parent.mkdir()
    write_canonical(frozen_path, frozen)
    seal = build_seal(corpus, partition, psha, frozen, evaluation, ledger.head, "custodian-1", T0, "held by the custodian outside the evaluation environment")
    log = open_access_log(tmp_path / "custody" / "access-log.jsonl", seal, T0, create=True)
    return {"corpus": corpus, "partition": partition, "psha": psha, "seal": seal, "log": log, "frozen_path": frozen_path, "frozen": frozen, "truth": truth, "evaluation": evaluation, "ledger": ledger, "tmp": tmp_path}


def test_seal_is_stable_and_any_mutation_changes_it(sealed) -> None:
    again = build_seal(sealed["corpus"], sealed["partition"], sealed["psha"], sealed["frozen"], sealed["evaluation"], sealed["ledger"].head, "custodian-1", T0, "held by the custodian outside the evaluation environment")
    assert document_sha256(again) == document_sha256(sealed["seal"])
    mutated = copy.deepcopy(sealed["frozen"])
    mutated["rows"][0]["final"]["value"] = "white"
    changed = build_seal(sealed["corpus"], sealed["partition"], sealed["psha"], mutated, sealed["evaluation"], sealed["ledger"].head, "custodian-1", T0, "held by the custodian outside the evaluation environment")
    assert document_sha256(changed) != document_sha256(sealed["seal"])


def test_seal_requires_every_frozen_track_labelled(sealed) -> None:
    partial = copy.deepcopy(sealed["frozen"])
    partial["rows"] = partial["rows"][1:]
    first = sealed["frozen"]["rows"][0]["trackId"]
    partial["rows"] = [r for r in partial["rows"] if r["trackId"] != first]
    with pytest.raises(CorpusError, match="seal_frozen_tracks_unlabelled"):
        build_seal(sealed["corpus"], sealed["partition"], sealed["psha"], partial, sealed["evaluation"], sealed["ledger"].head, "custodian-1", T0, "x")


def test_every_access_is_logged_before_anything_is_returned(sealed) -> None:
    digest = access_frozen(sealed["log"], sealed["seal"], sealed["frozen_path"], "custodian-1", "integrity-verify", "S2c.2", T0)
    assert isinstance(digest, str) and len(digest) == 64
    status = seal_status(sealed["log"], sealed["seal"])
    assert status["status"] == "intact" and status["accessCount"] == 1


def test_selection_stage_access_is_refused_logged_and_compromises_the_seal(sealed) -> None:
    """Mutation 6 (tool side): model selection cannot read the frozen labels quietly."""
    with pytest.raises(CorpusError, match="frozen_access_improper_seal_compromised"):
        access_frozen(sealed["log"], sealed["seal"], sealed["frozen_path"], "engineer-1", "candidate-comparison", "S2c.4", T0)
    with pytest.raises(CorpusError, match="improper"):
        access_frozen(sealed["log"], sealed["seal"], sealed["frozen_path"], "engineer-1", "s5-scoring", "S2c.4", T0)
    status = seal_status(sealed["log"], sealed["seal"])
    assert status["status"] == "compromised" and len(status["improperAccesses"]) == 2


def test_s5_scoring_returns_labels_and_is_counted(sealed) -> None:
    labels = access_frozen(sealed["log"], sealed["seal"], sealed["frozen_path"], "custodian-1", "s5-scoring", "S5", T0)
    assert labels["view"] == "frozen-test"
    assert seal_status(sealed["log"], sealed["seal"])["s5ScoringCount"] == 1


def test_tampered_frozen_labels_or_log_are_detected(sealed) -> None:
    document = json.loads(sealed["frozen_path"].read_text())
    document["rows"][0]["final"]["value"] = "white"
    sealed["frozen_path"].write_text(json.dumps(document))
    with pytest.raises(CorpusError, match="frozen_ground_truth_hash_mismatch"):
        access_frozen(sealed["log"], sealed["seal"], sealed["frozen_path"], "custodian-1", "integrity-verify", "S2c.2", T0)
    path = sealed["tmp"] / "custody" / "access-log.jsonl"
    recorded_head = sealed["log"].head  # retained elsewhere (F1 record / MSR)
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:1]) + "\n")  # the access entry cut away
    with pytest.raises(CorpusError, match="ledger_truncated_or_forked"):
        Ledger(path).require_extends(recorded_head)
    lines[1] = lines[1].replace("integrity-verify", "custody-transfer")
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(CorpusError, match="ledger_entry_tampered"):
        Ledger(path)


def test_a_compromised_seal_requires_a_new_frozen_set(sealed) -> None:
    declare_improper_access(sealed["log"], sealed["seal"], "engineer-1", "S2c.3", "file opened while debugging the harness", T0)
    assert seal_status(sealed["log"], sealed["seal"])["status"] == "compromised"
    reused = build_seal(sealed["corpus"], sealed["partition"], sealed["psha"], sealed["frozen"], sealed["evaluation"], sealed["ledger"].head, "custodian-1", T0, "x", supersedes={"sealSha256": document_sha256(sealed["seal"]), "reason": "compromised in S2c.3"})
    with pytest.raises(CorpusError, match="seal_reuses_compromised_frozen_set"):
        verify_superseding_seal(reused, sealed["seal"], sealed["log"])


def test_corpus_report_carries_diversity_and_the_synthetic_banner(sealed) -> None:
    with pytest.raises(CorpusError, match="corpus_report_requires_evaluation_view"):
        corpus_report(sealed["corpus"], sealed["partition"], sealed["psha"], sealed["truth"])
    report = corpus_report(sealed["corpus"], sealed["partition"], sealed["psha"], sealed["evaluation"])
    assert "frozen-test" not in report["annotatedDifficulty"], "frozen label distributions never enter the report"
    assert report["distributions"]["all"]["sites"] == 4 and report["distributions"]["all"]["cameras"] == 12
    assert set(report["distributions"]) == {"all", "training", "tuning", "selection", "frozen-test"}
    assert report["distributions"]["all"]["lighting"]["night"] > 0
    assert "not a scale, load or 500-camera claim" in report["scope"]
    assert "synthetic fixture" in render_markdown(report)


def test_the_selection_view_must_be_the_one_the_seal_committed(sealed) -> None:
    """Selection code reads only the stamped evaluation view that matches the seal."""
    view = seal_evaluation_view(sealed["evaluation"], sealed["seal"])
    assert load_evaluation_view(view, sealed["seal"]) == sealed["evaluation"]["rows"]
    with pytest.raises(CorpusError, match="evaluation_view_not_sealed"):
        load_evaluation_view(sealed["evaluation"], sealed["seal"])
    relabelled = copy.deepcopy(view)
    relabelled["rows"][0]["final"]["value"] = "white"
    with pytest.raises(CorpusError, match="evaluation_view_not_the_sealed_one"):
        load_evaluation_view(relabelled, sealed["seal"])
    edited = copy.deepcopy(sealed["evaluation"])
    edited["rows"][0]["final"]["value"] = "white"
    with pytest.raises(CorpusError, match="evaluation_view_not_the_sealed_one"):
        seal_evaluation_view(edited, sealed["seal"])


def test_the_seal_refuses_views_from_different_ground_truth(sealed) -> None:
    other = copy.deepcopy(sealed["evaluation"])
    other["annotationLedgerHead"] = "0" * 64
    with pytest.raises(CorpusError, match="seal_views_from_different_ground_truth"):
        build_seal(sealed["corpus"], sealed["partition"], sealed["psha"], sealed["frozen"], other, sealed["ledger"].head, "custodian-1", T0, "x")
    with pytest.raises(CorpusError, match="seal_requires_unsealed_evaluation_view"):
        build_seal(sealed["corpus"], sealed["partition"], sealed["psha"], sealed["frozen"], sealed["frozen"], sealed["ledger"].head, "custodian-1", T0, "x")
