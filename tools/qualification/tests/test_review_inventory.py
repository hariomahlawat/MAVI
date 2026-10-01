"""B0 review inventory: verified inputs, deterministic triage, provenance and separated review status.

Local fixtures only: bundles are built with the real recorded-discovery bundler from synthetic
metadata, and the network is blocked.
"""

from __future__ import annotations

import hashlib
import io
import json
import socket
import tarfile
from datetime import date
from pathlib import Path

import pytest

from attributes.corpus.canonical import canonical_json, sha256_hex
from source_acquisition import recorded_discovery as rd
from source_acquisition import review_inventory as ri
from source_acquisition.acquire import StoreError

CODE = {"repository": {"commit": "0" * 40, "localChanges": False}, "moduleSha256": {}}
REFERENCE = date(2025, 2, 20)


def meta(title: str, page_id: int, *, uploaded="2026-05-10T08:00:00Z", capture="2026-05-02", mime="video/webm",
         mediatype="VIDEO", licence="cc-by-4.0", width=1920, height=1080, duration=30.0, uploader="Uploader A",
         revid=None, sha1=None) -> dict:
    info = {"timestamp": uploaded, "user": uploader, "size": 1000, "width": width, "height": height, "duration": duration,
            "sha1": sha1 or hashlib.sha1(f"{title}{page_id}".encode()).hexdigest(), "mime": mime, "mediatype": mediatype,
            "url": f"https://upload.wikimedia.org/wikipedia/commons/a/ab/{page_id}.webm",
            "descriptionurl": f"https://commons.wikimedia.org/wiki/{page_id}",
            "extmetadata": {"License": {"value": licence}, "Artist": {"value": uploader},
                            **({"DateTimeOriginal": {"value": capture}} if capture else {})}, "metadata": []}
    return {"query": {"pages": [{"pageid": page_id, "title": title, "imageinfo": [info],
                                 "revisions": [{"revid": revid or page_id + 1, "timestamp": "2026-05-11T00:00:00Z"}]}]}}


def make_bundle(root: Path, name: str, run: str, files: list[dict], *, scope="P1", historical=None, extra=None) -> dict:
    """A finalised run directory, bundled with the real bundler. ``historical`` maps title -> (state, blockers)."""
    run_dir = root / "runs" / run
    for sub in ("config", "capture", "store/evidence", "store/discovery"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    (run_dir / "config" / "run-config.json").write_bytes(canonical_json({"run": run}))
    titles = []
    for document in files:
        blob = canonical_json(document)
        (run_dir / "store" / "evidence" / f"{sha256_hex(blob)}.json").write_bytes(blob)
        titles.append(document["query"]["pages"][0]["title"])
    for path, blob in (extra or {}).items():
        (run_dir / path).write_bytes(blob)
    report = {"items": [{"fileTitle": t, "admissionState": s, "blockers": b} for t, (s, b) in (historical or {}).items()]}
    blob = canonical_json(report)
    (run_dir / "store" / "discovery" / f"{sha256_hex(blob)}.json").write_bytes(blob)
    (run_dir / "capture" / "scopes.jsonl").write_bytes(
        (json.dumps({"event": "scope", "scope": scope, "describedTitles": titles}) + "\n").encode())
    (run_dir / "run-status.json").write_bytes(canonical_json({"status": "COMPLETE"}))
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    destination = rd.bundle(run_dir, evidence, name)
    digest = (destination / f"{name}.tar.gz.sha256").read_text().split()[0]
    return {"dir": destination, "name": name, "sha": digest}


def inventory(tmp_path: Path, bundles: list[dict], judgements=(), judgements_sha=None) -> dict:
    read = [ri.read_bundle(b["dir"], b["name"], b["sha"]) for b in bundles]
    return ri.build_inventory(read, REFERENCE, list(judgements), judgements_sha, CODE)


def by_title(inv: dict) -> dict:
    return {c["title"]: c for c in inv["candidates"]}


def test_a_bundle_is_used_only_after_its_checksum_pin_and_members_verify(tmp_path):
    b = make_bundle(tmp_path, "b1", "run-1", [meta("File:Street A 2026.webm", 10)])
    ri.read_bundle(b["dir"], b["name"], b["sha"])
    with pytest.raises(StoreError, match="supplied pin"):
        ri.read_bundle(b["dir"], b["name"], "f" * 64)
    with pytest.raises(StoreError, match="64 lower-case hex"):
        ri.read_bundle(b["dir"], b["name"], "not-a-hash")
    archive = b["dir"] / "b1.tar.gz"
    with tarfile.open(archive) as tar:
        members = [(m, tar.extractfile(m).read()) for m in tar.getmembers() if m.isfile()]
    rebuilt = io.BytesIO()
    with tarfile.open(fileobj=rebuilt, mode="w:gz") as out:
        for member, data in members:
            out.addfile(member, io.BytesIO(data))
        extra = tarfile.TarInfo("b1/store/evidence/" + "e" * 64 + ".json")
        extra.size = 2
        out.addfile(extra, io.BytesIO(b"{}"))
    archive.write_bytes(rebuilt.getvalue())
    new_sha = hashlib.sha256(rebuilt.getvalue()).hexdigest()
    (b["dir"] / "b1.tar.gz.sha256").write_text(f"{new_sha}  b1.tar.gz\n")
    with pytest.raises(StoreError, match="member set"):  # checksum and pin agree, but the member is not in the manifest
        ri.read_bundle(b["dir"], b["name"], new_sha)
    with pytest.raises(StoreError, match="checksum file"):
        (b["dir"] / "b1.tar.gz.sha256").write_text("0" * 64 + "  b1.tar.gz\n")
        ri.read_bundle(b["dir"], b["name"], new_sha)


def test_output_is_deterministic_and_never_overwrites(tmp_path):
    b = make_bundle(tmp_path, "b1", "run-1", [meta("File:Street A 2026.webm", 10), meta("File:Bus B 2026.webm", 11)])
    inv = inventory(tmp_path, [b])
    one = ri.write_outputs(tmp_path / "out-1", inv)
    two = ri.write_outputs(tmp_path / "out-2", inventory(tmp_path, [b]))
    assert one == two
    for name in one:
        assert (tmp_path / "out-1" / name).read_bytes() == (tmp_path / "out-2" / name).read_bytes()
    with pytest.raises(FileExistsError):
        ri.write_outputs(tmp_path / "out-1", inv)
    fake_repo = tmp_path / "fake-repo"
    (fake_repo / ".git").mkdir(parents=True)
    with pytest.raises(StoreError):
        ri.write_outputs(fake_repo / "inventory", inv)  # inside a Git worktree (a stand-in, so nothing can leak into this repository)
    assert not (fake_repo / "inventory").exists()


def test_a_page_described_twice_is_one_candidate_with_every_provenance(tmp_path):
    b1 = make_bundle(tmp_path, "b1", "run-1", [meta("File:Street A 2026.webm", 10)], scope="P2")
    b2 = make_bundle(tmp_path, "b2", "run-2", [meta("File:Street A 2026.webm", 10, revid=99, sha1="a" * 40)], scope="P2-o0")
    inv = inventory(tmp_path, [b1, b2])
    (c,) = inv["candidates"]
    assert [p["bundle"] for p in c["provenance"]] == ["b1", "b2"] and [p["scope"] for p in c["provenance"]] == ["P2", "P2-o0"]
    assert {"DESCRIBED_IN_MULTIPLE_BUNDLES", "REVISION_DIFFERS_BETWEEN_BUNDLES"} <= set(c["triage"]["flags"])
    assert c["pageRevisionId"] == 11  # identity from the first supplied bundle; the second revision stays in provenance


def test_title_page_id_and_byte_collisions_are_flagged(tmp_path):
    files = [meta("File:Street A 2026.webm", 10, sha1="b" * 40), meta("File:Street A 2026.webm", 20),
             meta("File:Copy 2026.webm", 30, sha1="b" * 40), meta("File:Cityscape 2026.webm", 40),
             meta("File:Cityscape 2026-320x180.webm", 41)]
    inv = inventory(tmp_path, [make_bundle(tmp_path, "b1", "run-1", files)])
    flags = {c["pageId"]: set(c["triage"]["flags"]) for c in inv["candidates"]}
    assert "TITLE_SHARED_BY_PAGE_IDS" in flags[10] and "TITLE_SHARED_BY_PAGE_IDS" in flags[20]
    assert "IDENTICAL_FILE_BYTES" in flags[10] and "IDENTICAL_FILE_BYTES" in flags[30]
    assert "NEAR_DUPLICATE_TITLE" in flags[40] and "NEAR_DUPLICATE_TITLE" in flags[41]
    assert inv["summary"]["nearDuplicateTitleClusters"]["cityscape"] == [40, 41]  # trailing numbers and sizes are stripped


def test_historical_ogv_states_stay_historical_beside_the_current_state(tmp_path):
    ogv = "File:Freeway view 2026.ogv"
    b = make_bundle(tmp_path, "b1", "run-1", [meta(ogv, 10, mime="application/ogg")],
                    historical={ogv: ("REJECTED", ["not-continuous-video"])})
    (c,) = inventory(tmp_path, [b])["candidates"]
    assert c["provenance"][0]["historicalAutomaticState"]["state"] == "REJECTED"
    assert c["provenance"][0]["historicalAutomaticState"]["blockers"] == ["not-continuous-video"]
    assert c["currentAutomaticState"] == {"state": "DISCOVERED", "blockers": []}


def test_malformed_and_incomplete_metadata_are_recorded_not_guessed(tmp_path):
    broken = canonical_json({"query": {"pages": [{"title": "File:Broken 2026.webm", "missing": True}]}})
    b = make_bundle(tmp_path, "b1", "run-1",
                    [meta("File:Street undated 2026.webm", 10, capture=None, duration=None, uploaded=None)],
                    extra={f"store/evidence/{sha256_hex(broken)}.json": broken})
    inv = inventory(tmp_path, [b])
    assert inv["summary"]["unparseableEvidence"] == 1 and inv["unparseableEvidence"][0]["memberSha256"] == sha256_hex(broken)
    (c,) = inv["candidates"]
    assert {"CAPTURE_DATE_UNDECLARED", "DURATION_MISSING", "UPLOAD_TIME_MISSING"} <= set(c["triage"]["flags"])
    assert "NOT_FRESH_UNDER_PROVISIONAL_REFERENCE" not in c["triage"]["flags"]  # a missing upload time never excludes


def test_title_rules_describe_and_never_decide_alone(tmp_path):
    judgements = [{"code": "TITLE_EVENT_SERIES", "titlePattern": "Skill Programme", "reason": "title names a programme event"}]
    files = [meta("File:Skill Programme 2026 Video 01.webm", 10),                                  # fresh + judgement
             meta("File:A Native Street (1906).webm", 11, uploaded="2019-07-09T00:00:00Z"),        # old + archival
             meta("File:Freeway view.ogv", 12, mime="application/ogg", uploaded="2012-06-02T00:00:00Z"),  # old, no title code
             meta("File:Times Square traffic 2026.webm", 13),                                      # fresh street, no India hint
             meta("File:Garden 2026.webm", 14),                                                    # fresh, no street hint
             meta("File:Harbour time-lapse 2026.webm", 15)]                                        # fresh timelapse
    inv = by_title(inventory(tmp_path, [make_bundle(tmp_path, "b1", "run-1", files)], judgements, "x" * 64))
    assert inv["File:Skill Programme 2026 Video 01.webm"]["triage"]["primary"] == "LIKELY_UNSUITABLE_TITLE_NEEDS_VISUAL_CONFIRMATION"
    assert inv["File:A Native Street (1906).webm"]["triage"]["primary"] == "CLEARLY_UNSUITABLE"
    assert inv["File:Freeway view.ogv"]["triage"]["primary"] == "NON_OPERATIONAL_REFERENCE_ONLY"
    street = inv["File:Times Square traffic 2026.webm"]
    assert street["triage"]["primary"] == "PLAUSIBLE_NEEDS_VISUAL_REVIEW" and "NO_INDIA_HINT_IN_TITLE" in street["triage"]["flags"]
    assert inv["File:Garden 2026.webm"]["triage"]["primary"] == "LIKELY_UNSUITABLE_TITLE_NEEDS_VISUAL_CONFIRMATION"
    assert inv["File:Harbour time-lapse 2026.webm"]["triage"]["primary"] == "LIKELY_UNSUITABLE_TITLE_NEEDS_VISUAL_CONFIRMATION"
    for c in inv.values():
        assert c["triage"]["basis"] == "retained Commons metadata and title only; no frame viewed"


def test_the_freshness_bound_is_derived_from_the_latest_excluded_upload(tmp_path):
    files = [meta("File:Old street.webm", 10, uploaded="2019-01-01T00:00:00Z"),
             meta("File:Later street.webm", 11, uploaded="2024-11-18T10:00:00Z"),
             meta("File:New street 2026.webm", 12, duration=40.5)]
    summary = inventory(tmp_path, [make_bundle(tmp_path, "b1", "run-1", files)])["summary"]
    assert summary["freshnessBoundValidForReferenceOnOrAfter"] == "2024-11-18"
    assert summary["freshPossibleCandidates"] == 1 and summary["upperBoundSeconds"]["freshPossibleAllSubjects"] == "40.5"


def test_review_admission_and_frozen_status_stay_separate_and_unset(tmp_path):
    b = make_bundle(tmp_path, "b1", "run-1", [meta("File:Old street (1906).webm", 10, uploaded="2019-01-01T00:00:00Z"),
                                               meta("File:Old freeway.webm", 11, uploaded="2012-01-01T00:00:00Z", licence="cc-by-sa-3.0"),
                                               meta("File:Street 2026.webm", 12)])
    inv = inventory(tmp_path, [b])
    for c in inv["candidates"]:
        assert c["status"] == {"DESCRIBED": True, "REVIEWED": False, "ADMISSIBLE": None, "FROZEN_QUALIFICATION": False}
    hashes = ri.write_outputs(tmp_path / "out", inv)
    template = json.loads((tmp_path / "out" / "decisions-template.json").read_bytes())
    assert all(d["state"] is None and d["reviewedBy"] is None and d["rightsReview"]["determination"] is None for d in template["decisions"])
    proposals = json.loads((tmp_path / "out" / "proposed-metadata-decisions.json").read_bytes())["decisions"]
    states = {p["fileTitle"]: (p["state"], p["reviewedBy"], p["confirmation"]) for p in proposals}
    assert states == {"File:Old street (1906).webm": ("REJECTED", None, "PROPOSED_UNCONFIRMED"),
                      "File:Old freeway.webm": ("REFERENCE_ONLY", None, "PROPOSED_UNCONFIRMED")}
    assert "R-5" in next(p for p in proposals if p["state"] == "REFERENCE_ONLY")["reason"]
    worksheet = (tmp_path / "out" / "visual-review-worksheet.csv").read_text().splitlines()
    assert len(worksheet) == 2 and worksheet[1].startswith("12,File:Street 2026.webm,PLAUSIBLE_NEEDS_VISUAL_REVIEW")
    sums = (tmp_path / "out" / "SHA256SUMS").read_text()
    assert all(f"{h}  {n}" in sums for n, h in hashes.items())


def test_ordering_is_stable_by_bundle_then_title(tmp_path):
    b1 = make_bundle(tmp_path, "b1", "run-1", [meta("File:Zebra street 2026.webm", 2), meta("File:Alpha street 2026.webm", 1)])
    b2 = make_bundle(tmp_path, "b2", "run-2", [meta("File:Aardvark street 2026.webm", 3)])
    titles = [c["title"] for c in inventory(tmp_path, [b1, b2])["candidates"]]
    assert titles == ["File:Alpha street 2026.webm", "File:Zebra street 2026.webm", "File:Aardvark street 2026.webm"]


def test_title_judgements_are_validated_and_unused_patterns_reported(tmp_path):
    def write(doc) -> Path:
        path = tmp_path / f"j{len(list(tmp_path.glob('j*.json')))}.json"
        path.write_text(json.dumps(doc))
        return path

    good = write({"schema": ri.JUDGEMENTS_SCHEMA, "rules": [{"code": "TITLE_BILLBOARD", "titlePattern": "billboard", "reason": "a billboard"}]})
    rules, digest = ri.load_judgements(good)
    assert digest == hashlib.sha256(good.read_bytes()).hexdigest()
    for bad in ({"schema": "other", "rules": []},
                {"schema": ri.JUDGEMENTS_SCHEMA, "rules": [{"code": "TITLE_MADE_UP", "titlePattern": "x", "reason": "r"}]},
                {"schema": ri.JUDGEMENTS_SCHEMA, "rules": [{"code": "TITLE_BILLBOARD", "titlePattern": "(", "reason": "r"}]},
                {"schema": ri.JUDGEMENTS_SCHEMA, "rules": [{"code": "TITLE_BILLBOARD", "titlePattern": "x", "reason": " "}]},
                {"schema": ri.JUDGEMENTS_SCHEMA, "rules": [{"code": "TITLE_BILLBOARD", "titlePattern": "x", "reason": "r", "extra": 1}]}):
        with pytest.raises(StoreError):
            ri.load_judgements(write(bad))
    inv = inventory(tmp_path, [make_bundle(tmp_path, "b1", "run-1", [meta("File:Street 2026.webm", 1)])], rules, digest)
    assert inv["summary"]["unmatchedJudgementPatterns"] == ["billboard"] and inv["titleJudgementsSha256"] == digest


def test_the_command_makes_no_network_attempt_and_never_mutates_a_bundle(tmp_path, monkeypatch):
    b = make_bundle(tmp_path, "b1", "run-1", [meta("File:Street 2026.webm", 1)])
    before = {p.name: p.read_bytes() for p in b["dir"].iterdir()}

    def blocked(*_a, **_k):
        raise AssertionError("network attempted")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    code = ri.main(["--bundle", str(b["dir"]), b["name"], b["sha"], "--provisional-reference", "2025-02-20",
                    "--out", str(tmp_path / "cli-out")])
    assert code == 0 and (tmp_path / "cli-out" / "inventory.json").exists()
    assert {p.name: p.read_bytes() for p in b["dir"].iterdir()} == before
    assert ri.main(["--bundle", str(b["dir"]), b["name"], "f" * 64, "--provisional-reference", "2025-02-20",
                    "--out", str(tmp_path / "cli-out-2")]) == 2
    assert not (tmp_path / "cli-out-2").exists()
