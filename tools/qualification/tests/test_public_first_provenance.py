"""Owner decision C+: public-first development, protected frozen qualification.

* A public file is acquired for named engineering purposes through a purpose approval. The
  approval reuses a hash-bound rights/privacy determination and never changes the file's
  B0 decision or admission state.
* Public, private, unapproved or previously exposed footage can never enter the frozen
  qualification test: refused at manifest, revision, partition, verification and seal.
* B0 states, decisions and pre-C+ corpora behave exactly as before.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json

import pytest
from attribute_corpus_fixtures import PROTECTED_PROVENANCE, build_corpus, policy
from test_attribute_corpus_frozen import sealed  # noqa: F401  (pytest fixture)
from test_source_acquisition import MEDIA, TITLE, UPLOAD_URL, FakeNet, admitted, meta, transport

from attributes.corpus.canonical import CorpusError, document_sha256
from attributes.corpus.frozen import build_seal
from attributes.corpus.manifest import parse_corpus, revise_corpus
from attributes.corpus.partition import FROZEN, LinkGroup, build_partition, partition_exposures, partition_of, verify_partition
from attributes.corpus.provenance import ENGINEERING_PURPOSES, FROZEN_QUALIFICATION, frozen_blockers, parse_purposes
from source_acquisition import acquire as acq
from source_acquisition import admission, cli

AUDITS = {"recurrence": "1" * 64, "duplicate": "2" * 64}  # operational partitions need both audit hashes
SHA1 = hashlib.sha1(MEDIA).hexdigest()
RECEIPT = "e" * 64
OTHER = "File:Market street Kolkata 2026.webm"


def reference_only() -> dict:
    """A B0 REFERENCE_ONLY decision, as recorded by the human reviewer."""
    return admitted(state="REFERENCE_ONLY", intendedRole="development-reference", reason="handheld; reference only (B0)")


def rejected() -> dict:
    return admitted(state="REJECTED", reason="festival crowd; rejected for operational qualification (B0)")


def determination(**over) -> dict:
    """One reviewed release-level determination, reusable by every file it covers."""
    record = {
        "determinationId": "commons-cc-street-2026", "reviewedOn": "2026-10-03",
        "purposes": ["benchmarking", "development", "reference", "regression-challenge", "training"],
        "licenceCodes": ["cc-by-4.0", "cc-by-nc-sa-4.0", "cc-by-sa-3.0-nl", "cc-by-sa-4.0"],
        "rights": {"reviewedBy": "Hari Om Ahlawat", "determination": "PERMITTED_FOR_ENGINEERING_USE", "evidence": "file-page licences; internal processing only"},
        "privacy": {"reviewedBy": "Hari Om Ahlawat", "disposition": "PERMITTED", "basis": "street scenes; no identity processing; pseudonymous crops"},
        "r5Ruling": {"ruledBy": "R-5", "ruling": "PERMITTED", "reference": "R-5 ruling 2026-10-03 #1 (CC BY-SA internal adaptation)"},
    }
    record.update(over)
    return record


def entry(**over) -> dict:
    record = {"fileTitle": TITLE, "pageRevisionId": 777, "fileSha1": SHA1, "purposes": ["regression-challenge", "training"],
              "determinationId": "commons-cc-street-2026", "b0Decision": None}
    record.update(over)
    return record


def document(entries, determinations=None, **over) -> dict:
    doc = {"schemaVersion": admission.PURPOSE_APPROVALS_SCHEMA, "approvedBy": "Hari Om Ahlawat", "approvedOn": "2026-10-03",
           "determinations": determinations or [determination()], "approvals": entries}
    doc.update(over)
    return doc


def approval(det: dict | None = None, **over) -> dict:
    """One resolved approval, exactly as ``load_purpose_approvals`` returns it."""
    return admission.parse_purpose_approvals(document([entry(**over)], [det or determination()]))[0]


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "controlled-store"
    root.mkdir()
    return root


def _receipts(store):
    return [json.loads(p.read_bytes()) for p in sorted((store / "receipts").glob("*.json"))]


def _downloaded(net) -> bool:
    return any(u == UPLOAD_URL for u, _ in net.requests)


# ---------------------------------------------------------------- purpose-aware acquisition


def test_reference_only_stays_reference_only_while_approved_for_training(store):
    decision = reference_only()
    before = copy.deepcopy(decision)
    net = FakeNet()
    summary = acq.acquire(store, [decision], transport(net), [approval(b0Decision="REFERENCE_ONLY")])
    [receipt] = _receipts(store)
    assert decision == before  # the human B0 decision is not rewritten
    assert receipt["admissionState"] == "REFERENCE_ONLY" and receipt["requestedState"] == "REFERENCE_ONLY"
    assert receipt["intendedRole"] == "development-reference"
    assert receipt["acquisitionBases"] == ["PURPOSE_APPROVAL"] and receipt["sourceOrigin"] == "public"
    pa = receipt["purposeApproval"]
    assert pa["status"] == "APPROVED" and pa["purposes"] == ["regression-challenge", "training"] and pa["b0Decision"] == "REFERENCE_ONLY"
    assert pa["determinationSha256"] == document_sha256(determination())
    assert receipt["acquisition"]["status"] == "ACQUIRED" and _downloaded(net)
    assert summary["counts"] == {"REFERENCE_ONLY": 1} and summary["purposeApproved"] == 1
    assert acq.verify(store) == []


def test_reference_only_without_approval_is_still_not_downloaded(store):
    net = FakeNet()
    acq.acquire(store, [reference_only()], transport(net))
    [receipt] = _receipts(store)
    assert receipt["admissionState"] == "REFERENCE_ONLY" and receipt["acquisition"] is None and receipt["acquisitionBases"] == []
    assert not _downloaded(net)


def test_a_new_purpose_specific_acquisition_needs_no_b0_decision(store):
    net = FakeNet()
    summary = acq.acquire(store, [], transport(net), [approval(purposes=["benchmarking"])])
    [receipt] = _receipts(store)
    assert receipt["requestedState"] is None and receipt["reviewedBy"] is None  # no B0 decision is created
    assert receipt["admissionState"] == admission.derive_state(meta(), None)[0] == "DISCOVERED"
    assert receipt["acquisitionBases"] == ["PURPOSE_APPROVAL"] and summary["purposeApproved"] == 1


def test_one_determination_covers_many_files_without_copying_reviews():
    doc = document([entry(), entry(fileTitle=OTHER, pageRevisionId=777, purposes=["benchmarking", "reference"])])
    first, second = admission.parse_purpose_approvals(doc)
    assert first["determination"] == second["determination"]
    assert admission.purpose_approval_blockers(meta(), first) == []
    assert admission.purpose_approval_blockers(meta(title=OTHER), second) == []
    s1 = admission.build_receipt(meta(), None, "0" * 64, None, first)["purposeApproval"]
    s2 = admission.build_receipt(meta(title=OTHER), None, "0" * 64, None, second)["purposeApproval"]
    assert s1["determinationSha256"] == s2["determinationSha256"] and s1["approvalSha256"] != s2["approvalSha256"]
    # Editing the shared determination changes every bound approval hash.
    edited = admission.parse_purpose_approvals(document([entry()], [determination(reviewedOn="2026-10-04")]))[0]
    assert admission.build_receipt(meta(), None, "0" * 64, None, edited)["purposeApproval"]["determinationSha256"] != s1["determinationSha256"]


@pytest.mark.parametrize("purposes", [[FROZEN_QUALIFICATION], ["frozen-qualification", "training"]])
def test_public_files_can_never_be_approved_for_frozen_qualification(store, tmp_path, purposes, capsys):
    with pytest.raises(CorpusError, match="frozen_qualification_requires_protected_origin"):
        approval(purposes=purposes)
    with pytest.raises(CorpusError, match="frozen_qualification_requires_protected_origin"):
        approval(det=determination(purposes=purposes))
    hand_made = dict(approval(), purposes=purposes)  # bypassing the loader is refused too
    with pytest.raises(CorpusError, match="frozen_qualification_requires_protected_origin"):
        admission.purpose_approval_blockers(meta(), hand_made)
    path = tmp_path / "approvals.json"
    path.write_text(json.dumps(document([entry(purposes=purposes)])), encoding="utf-8")
    assert cli.main(["acquire", "--store", str(store), "--contact", "ops@example.org", "--purpose-approvals", str(path)]) == 2
    assert "frozen_qualification" in capsys.readouterr().err


@pytest.mark.parametrize("det,over,blocker", [
    ({"r5Ruling": None}, {}, "r5-ruling-missing"),
    ({"rights": {"reviewedBy": "x", "determination": "PERMITTED_FOR_PILOT_ACQUISITION", "evidence": "e"}}, {}, "rights-determination-missing"),
    ({"privacy": {"disposition": "PERMITTED"}}, {}, "privacy-determination-missing"),
    ({"privacy": {"reviewedBy": "Hari Om Ahlawat", "disposition": "DENIED", "basis": "close-range faces"}}, {}, "privacy-denied"),
    ({"purposes": ["benchmarking"]}, {}, "purpose-not-covered-by-determination"),
    ({"licenceCodes": ["cc-by-4.0"]}, {}, "licence-not-covered-by-determination"),
    ({}, {"pageRevisionId": 776}, "approved-revision-differs-from-current"),
    ({}, {"fileSha1": "0" * 40}, "approved-revision-differs-from-current"),
])
def test_an_incomplete_approval_names_its_gap_and_downloads_nothing(store, det, over, blocker):
    resolved = approval(det=determination(**det), **over)
    assert blocker in admission.purpose_approval_blockers(meta(), resolved)
    net = FakeNet()
    acq.acquire(store, [], transport(net), [resolved])
    [receipt] = _receipts(store)
    assert receipt["purposeApproval"]["status"] == "BLOCKED" and receipt["acquisitionBases"] == [] and receipt["acquisition"] is None
    assert not _downloaded(net)


def test_a_b0_rejection_cannot_be_bypassed_by_a_new_purpose(store):
    decision = rejected()
    before = copy.deepcopy(decision)
    # Declared, but no decisions file supplied: the rejection check still applies.
    assert "b0-rejection-review-missing" in admission.purpose_approval_blockers(meta(), approval(b0Decision="REJECTED"))
    # Supplied decision that the approval does not declare: refused, nothing downloaded.
    with pytest.raises(CorpusError, match="b0_decision_mismatch"):
        admission.purpose_approval_blockers(meta(), approval(), decision)
    net = FakeNet()
    assert acq.acquire(store, [decision], transport(net), [approval()])["failed"] == 1 and not _downloaded(net)
    privacy = approval(b0Decision="REJECTED", b0RejectionReview={"reviewedBy": "Hari Om Ahlawat", "rightsOrPrivacyRejection": True, "basis": "close-range faces"})
    assert "b0-rights-or-privacy-rejection" in admission.purpose_approval_blockers(meta(), privacy, decision)
    review = {"reviewedBy": "Hari Om Ahlawat", "rightsOrPrivacyRejection": False, "basis": "rejected for crowd density only"}
    content = approval(b0Decision="REJECTED", b0RejectionReview=review)
    assert admission.purpose_approval_blockers(meta(), content, decision) == []
    for missing in ("reviewedBy", "basis"):
        unnamed = approval(b0Decision="REJECTED", b0RejectionReview={**review, missing: None})
        assert "b0-rejection-review-missing" in admission.purpose_approval_blockers(meta(), unnamed, decision)
    acq.acquire(store, [decision], transport(FakeNet()), [content])
    receipt = [r for r in _receipts(store) if r["acquisitionBases"]][0]
    assert decision == before and receipt["admissionState"] == "REJECTED" and receipt["requestedState"] == "REJECTED"


def test_r5_settles_share_alike_and_unrecognised_licence_codes_but_never_nc_nd_or_a_missing_licence():
    assert admission.purpose_approval_blockers(meta(license="cc-by-4.0"), approval(det=determination(r5Ruling=None))) == []
    assert admission.purpose_approval_blockers(meta(license="cc-by-sa-3.0-nl"), approval()) == []
    assert "r5-ruling-missing" in admission.purpose_approval_blockers(meta(license="cc-by-sa-3.0-nl"), approval(det=determination(r5Ruling=None)))
    assert "licence-restricts-derivatives-or-use" in admission.purpose_approval_blockers(meta(license="cc-by-nc-sa-4.0"), approval())
    no_licence = admission.purpose_approval_blockers(meta(license=None), approval())
    assert "file-licence-missing" in no_licence and "file-licence-unknown" in no_licence
    assert "not-continuous-video" in admission.purpose_approval_blockers(meta(mediatype="BITMAP", mime="image/jpeg"), approval())


@pytest.mark.parametrize("edit,code", [
    (lambda d: d["approvals"][0].update(purposes=[]), "purposes"),
    (lambda d: d["approvals"][0].update(purposes=["tuning", "training"]), "purposes"),
    (lambda d: d["approvals"][0].update(purposes=["operational"]), "purpose_unknown"),
    (lambda d: d["approvals"][0].update(determinationId="nope"), "determination_unknown"),
    (lambda d: d["approvals"][0].update(b0Decision="ADMISSIBLE"), "b0_decision"),
    (lambda d: d["approvals"].append(entry()), "duplicate_file"),
    (lambda d: d["approvals"][0].pop("b0Decision"), "missing:b0Decision"),
    (lambda d: d["determinations"].append(determination()), "determination_duplicate"),
    (lambda d: d["determinations"][0].update(licenceCodes=["CC-BY-4.0"]), "licence_codes"),
    (lambda d: d["determinations"][0]["privacy"].update(basis="see C:\\Users\\ops\\note.txt"), "local_path"),
    (lambda d: d.update(approvedOn="03/10/2026"), "date"),
    (lambda d: d.update(schemaVersion="mavi-s2c-source-purpose-approvals-v0"), "schema"),
])
def test_a_malformed_approvals_document_is_refused_whole(edit, code):
    doc = document([entry()])
    edit(doc)
    with pytest.raises(CorpusError, match=code):
        admission.parse_purpose_approvals(doc)


def test_cli_acquire_requires_decisions_or_approvals(store, capsys):
    assert cli.main(["acquire", "--store", str(store), "--contact", "ops@example.org"]) == 2
    assert "--purpose-approvals" in capsys.readouterr().err


# ---------------------------------------------------------------- B0 semantics unchanged


def test_b0_states_and_decision_outcomes_are_unchanged_by_approvals():
    assert admission.STATES == ("DISCOVERED", "RIGHTS_PENDING", "PROVENANCE_PENDING", "ADMITTED_FOR_PILOT", "REFERENCE_ONLY", "REJECTED")
    assert admission.HUMAN_STATES == ("ADMITTED_FOR_PILOT", "REFERENCE_ONLY", "REJECTED")
    for decision in (None, reference_only(), rejected(), admitted()):
        expected = admission.derive_state(meta(), decision)
        declared = None if decision is None else decision["state"]
        for extra in (None, approval(b0Decision=declared)):
            receipt = admission.build_receipt(meta(), copy.deepcopy(decision), "0" * 64, None, extra)
            assert (receipt["admissionState"], receipt["blockers"]) == (expected[0], sorted(expected[1]))
    pilot = admission.build_receipt(meta(), admitted(), "0" * 64, None)
    assert pilot["acquisitionBases"] == ["ADMITTED_FOR_PILOT"] and pilot["purposeApproval"] is None


# ---------------------------------------------------------------- frozen qualification enforcement


def _provenance(origin, purposes=("selection", "training", "tuning"), exposures=(), receipt=RECEIPT) -> dict:
    return {"origin": origin, "approvedPurposes": sorted(purposes), "acquisitionReceiptSha256": receipt, "priorExposures": list(exposures)}


def _mixed_corpus(public_sites=(0, 1), **provenance) -> dict:
    raw = build_corpus(sites=5, cameras_per_site=3, days=12, tracks_per_source=1, kind="operational")
    for source in raw["sources"]:
        if int(source["siteId"].split("-")[1]) in public_sites:
            source["provenance"] = provenance or _provenance("public")
    return raw


def test_public_provenance_can_never_carry_the_frozen_purpose():
    raw = _mixed_corpus(**_provenance("public", purposes=(FROZEN_QUALIFICATION, "training")))
    with pytest.raises(CorpusError, match="frozen_qualification_requires_protected_origin"):
        parse_corpus(raw)
    no_receipt = _mixed_corpus(**_provenance("public", receipt=None))
    with pytest.raises(CorpusError, match="public_source_requires_receipt"):
        parse_corpus(no_receipt)


@pytest.mark.parametrize("ineligible", [
    _provenance("public"),
    _provenance("private"),
    _provenance("commissioned"),  # protected, but frozen use not approved
    _provenance("owner-captured", purposes=(FROZEN_QUALIFICATION, "training"), exposures=[{"use": "partition-training", "recordSha256": "f" * 64}]),
])
def test_ineligible_footage_never_enters_the_frozen_test(ineligible):
    corpus = parse_corpus(_mixed_corpus(**ineligible))
    partition = build_partition(corpus, policy(heldOutSites=1), [], AUDITS)
    frozen = [t for t, p in partition_of(partition).items() if p == FROZEN]
    assert frozen and all(not frozen_blockers(corpus.source_of(t).provenance, corpus.corpus_kind) for t in frozen)
    public_tracks = [t for t in corpus.tracks if corpus.source_of(t).site_id in ("site-0", "site-1")]
    assert all(partition_of(partition)[t] != FROZEN for t in public_tracks)
    assert any(x.startswith("frozen_ineligible_clusters:") for x in partition["checks"]["limitations"])
    verify_partition(corpus, partition, [], AUDITS)


def test_operational_footage_without_provenance_is_never_frozen():
    corpus = parse_corpus(build_corpus(sites=4, kind="operational", provenance=None))
    partition = build_partition(corpus, policy(), [], AUDITS)
    assert FROZEN not in set(partition_of(partition).values())
    with pytest.raises(CorpusError, match="partition_empty:frozen-test"):
        verify_partition(corpus, partition, [], AUDITS)


def test_a_hand_edited_partition_cannot_freeze_public_footage():
    corpus = parse_corpus(_mixed_corpus())
    partition = build_partition(corpus, policy(heldOutSites=1), [], AUDITS)
    forged = copy.deepcopy(partition)
    public = next(a for a in forged["assignments"] if corpus.source_of(a["trackId"]).site_id == "site-0")
    for cluster in forged["clusters"]:
        if cluster["clusterId"] == public["clusterId"]:
            cluster["partition"] = FROZEN
    for entry in forged["assignments"]:
        if entry["clusterId"] == public["clusterId"]:
            entry["partition"] = FROZEN
    with pytest.raises(CorpusError, match="partition_frozen_track_not_eligible"):
        verify_partition(corpus, forged, [], AUDITS)


def test_the_seal_refuses_frozen_tracks_whose_footage_is_not_eligible(sealed):  # noqa: F811
    corpus = sealed["corpus"]
    public = {sid: dataclasses.replace(s, provenance=_provenance("public")) for sid, s in corpus.sources.items()}
    relabelled = dataclasses.replace(corpus, sources=public)  # same identity, ineligible footage
    with pytest.raises(CorpusError, match="seal_frozen_tracks_not_eligible"):
        build_seal(relabelled, sealed["partition"], sealed["psha"], sealed["frozen"], sealed["evaluation"], sealed["ledger"].head,
                   "custodian-1", "2026-10-20T09:00:00Z", "held by the custodian outside the evaluation environment")


# ---------------------------------------------------------------- exposure history


def test_partition_exposure_carried_into_a_revision_blocks_a_later_freeze():
    raw = build_corpus(sites=4, cameras_per_site=3, days=12, tracks_per_source=1, kind="operational")
    corpus = parse_corpus(raw)
    partition = build_partition(corpus, policy(), [], AUDITS)
    exposures = partition_exposures(corpus, partition)
    assert exposures and all(e["recordSha256"] == document_sha256(partition) for es in exposures.values() for e in es)
    assert all(not e["use"].endswith("frozen-test") for es in exposures.values() for e in es)
    revised = copy.deepcopy(raw)
    revised.update(revision=2, supersedes=corpus.sha256)
    for source in revised["sources"]:
        source["provenance"]["priorExposures"] = exposures.get(source["sourceId"], [])
    second = revise_corpus(corpus, revised)
    for track_id, part in partition_of(partition).items():
        blocked = frozen_blockers(second.source_of(track_id).provenance, second.corpus_kind)
        assert ("previously-exposed" in blocked) == (part != FROZEN)


def test_a_revision_cannot_drop_exposure_or_change_origin():
    raw = build_corpus(sites=3, kind="operational", provenance=_provenance("owner-captured", exposures=[{"use": "development", "recordSha256": "f" * 64}]))
    corpus = parse_corpus(raw)
    for edit, code in ((lambda p: p.update(priorExposures=[]), "corpus_revision_exposure_dropped"),
                       (lambda p: p.update(origin="commissioned"), "corpus_revision_origin_changed")):
        revised = copy.deepcopy(raw)
        revised.update(revision=2, supersedes=corpus.sha256)
        edit(revised["sources"][0]["provenance"])
        with pytest.raises(CorpusError, match=code):
            revise_corpus(corpus, revised)


# ---------------------------------------------------------------- backward compatibility


def test_pre_c_plus_fixture_partitions_are_unchanged_by_eligible_provenance():
    legacy = parse_corpus(build_corpus(sites=4, provenance=None))
    declared = parse_corpus(build_corpus(sites=4, provenance=PROTECTED_PROVENANCE))
    a = build_partition(legacy, policy(), [], AUDITS)
    b = build_partition(declared, policy(), [], AUDITS)
    assert a["clusters"] == b["clusters"] and a["assignments"] == b["assignments"] and a["moves"] == b["moves"] and a["checks"] == b["checks"]
    assert "provenance" not in legacy.document["sources"][0]


def test_vocabulary_is_closed():
    assert FROZEN_QUALIFICATION not in ENGINEERING_PURPOSES
    assert set(ENGINEERING_PURPOSES) == {"training", "development", "tuning", "selection", "benchmarking", "reference", "regression-challenge"}


# ---------------------------------------------------------------- review additions


def test_frozen_approval_cannot_be_combined_with_use_outside_the_partitions():
    for extra in ("development", "reference", "benchmarking", "regression-challenge"):
        with pytest.raises(CorpusError, match="frozen_qualification_with_untracked_purpose"):
            parse_purposes(sorted([FROZEN_QUALIFICATION, extra]), "x", "owner-captured")
    assert parse_purposes(["frozen-qualification", "selection", "training", "tuning"], "x", "commissioned")


def test_renaming_a_source_does_not_shed_its_origin_or_exposure():
    raw = build_corpus(sites=3, kind="operational", provenance=_provenance("owner-captured", exposures=[{"use": "development", "recordSha256": "f" * 64}]))
    corpus = parse_corpus(raw)
    for edit, code in ((lambda p: p.update(priorExposures=[]), "corpus_revision_exposure_dropped"),
                       (lambda p: p.update(origin="commissioned"), "corpus_revision_origin_changed")):
        revised = copy.deepcopy(raw)
        revised.update(revision=2, supersedes=corpus.sha256)
        source = revised["sources"][0]
        old, source["sourceId"] = source["sourceId"], "src-renamed"
        for track in revised["tracks"]:
            if track["sourceId"] == old:
                track["sourceId"] = "src-renamed"
        edit(source["provenance"])
        with pytest.raises(CorpusError, match=code):
            revise_corpus(corpus, revised)


def test_a_source_with_undeclared_history_can_be_declared_but_never_made_frozen_eligible():
    raw = build_corpus(sites=3, kind="operational", provenance=None)
    corpus = parse_corpus(raw)
    revised = copy.deepcopy(raw)
    revised.update(revision=2, supersedes=corpus.sha256)
    for source in revised["sources"]:
        source["provenance"] = copy.deepcopy(PROTECTED_PROVENANCE)
    with pytest.raises(CorpusError, match="corpus_revision_undeclared_source_made_frozen_eligible"):
        revise_corpus(corpus, revised)
    for source in revised["sources"]:
        source["provenance"] = _provenance("owner-captured")  # training/tuning/selection only
    assert all(frozen_blockers(s.provenance, "operational") for s in revise_corpus(corpus, revised).sources.values())


def test_a_site_with_public_and_protected_blocks_freezes_only_protected_blocks():
    raw = build_corpus(sites=4, cameras_per_site=3, days=12, tracks_per_source=1, kind="operational")
    for source in raw["sources"]:
        if source["siteId"] == "site-0" and source["recordingDate"] < "2026-03-08":  # first two 3-day blocks public
            source["provenance"] = _provenance("public")
    corpus = parse_corpus(raw)
    partition = build_partition(corpus, policy(heldOutSites=1, frozenLatestBlockFraction=0.5), [], AUDITS)
    parts = partition_of(partition)
    site0 = {c["clusterId"]: c["partition"] for c in partition["clusters"] if c["siteId"] == "site-0"}
    assert FROZEN in site0.values()  # the protected later blocks still give a temporal hold-out
    for track_id, part in parts.items():
        if part == FROZEN:
            assert not frozen_blockers(corpus.source_of(track_id).provenance, corpus.corpus_kind)
    held_out = {c["siteId"] for c in partition["clusters"] if all(x["partition"] == FROZEN for x in partition["clusters"] if x["siteId"] == c["siteId"])}
    assert "site-0" not in held_out
    verify_partition(corpus, partition, [], AUDITS)


def test_one_public_camera_makes_its_whole_site_date_cluster_ineligible():
    raw = build_corpus(sites=4, cameras_per_site=3, days=12, tracks_per_source=1, kind="operational")
    for source in raw["sources"]:
        if source["cameraId"] == "cam-1-0":
            source["provenance"] = _provenance("public")
    corpus = parse_corpus(raw)
    partition = build_partition(corpus, policy(heldOutSites=1), [], AUDITS)
    site1 = [t for t in corpus.tracks if corpus.source_of(t).site_id == "site-1"]
    assert all(partition_of(partition)[t] != FROZEN for t in site1)  # protected cameras of the same clusters too
    limit = next(x for x in partition["checks"]["limitations"] if x.startswith("frozen_ineligible_clusters:"))
    assert limit == f"frozen_ineligible_clusters:{len({c['clusterId'] for c in partition['clusters'] if c['siteId'] == 'site-1'})}"


def test_when_every_site_is_public_nothing_is_frozen_and_verification_fails_closed():
    corpus = parse_corpus(build_corpus(sites=4, kind="operational", provenance=_provenance("public")))
    partition = build_partition(corpus, policy(heldOutSites=1), [], AUDITS)
    assert FROZEN not in set(partition_of(partition).values()) and set(partition_of(partition).values()) == {"training", "tuning", "selection"}
    with pytest.raises(CorpusError, match="partition_empty:frozen-test"):
        verify_partition(corpus, partition, [], AUDITS)


def test_a_recurrence_link_to_public_training_footage_pulls_the_frozen_cluster_out():
    raw = _mixed_corpus(public_sites=(0,))
    corpus = parse_corpus(raw)
    base = build_partition(corpus, policy(heldOutSites=1), [], AUDITS)
    parts = partition_of(base)
    frozen_track = next(t for t, p in parts.items() if p == FROZEN)
    public_track = next(t for t, p in parts.items() if corpus.source_of(t).site_id == "site-0")
    link = LinkGroup("same-subject", "recurrence", frozenset({frozen_track, public_track}))
    linked = build_partition(corpus, policy(heldOutSites=1), [link], AUDITS)
    assert partition_of(linked)[frozen_track] == partition_of(linked)[public_track] == "training"
    assert any("recurrence:same-subject" in m["reasons"] for m in linked["moves"])


# Partition hashes computed with the code on main (1174ab66) for the same fixtures: eligible
# or undeclared synthetic corpora must partition byte-identically after C+.
MAIN_PARTITION_HASHES = [
    ({"sites": 4}, {}, "f901846a0a5bf83894640d0cf6f75e37177cb5ff14057b128e9640b59ad65eec"),
    ({"sites": 5, "cameras_per_site": 3, "days": 12, "tracks_per_source": 1}, {"heldOutSites": 1}, "9ef66830df5cf828b2fb72e51f4e91f013394d37809b8bb47722414570dce9ac"),
    ({"sites": 3}, {"frozenLatestBlockFraction": 0.5}, "4f3c7ec637841a762f648f76e29631905c318e3b2c875027b2a0e5173675028d"),
]


@pytest.mark.parametrize("corpus_args,policy_args,expected", MAIN_PARTITION_HASHES)
def test_pre_c_plus_partitions_are_byte_identical_to_main(corpus_args, policy_args, expected):
    corpus = parse_corpus(build_corpus(**corpus_args, provenance=None))
    assert document_sha256(build_partition(corpus, policy(**policy_args), [], {"recurrence": None, "duplicate": None})) == expected
