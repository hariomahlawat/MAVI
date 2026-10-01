"""S2c B0 source-admission and acquisition pilot: rules, transport safety and integrity.

Fake transport only: CI never touches the network or downloads real media.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import re
from pathlib import Path

import pytest

from attributes.corpus.canonical import CorpusError, canonical_json
from source_acquisition import acquire as acq
from source_acquisition import admission, commons
from source_acquisition.transport import Transport, TransportError

QUALIFICATION = Path(__file__).resolve().parents[1]
REPO = QUALIFICATION.parents[1]
MEDIA = b"\x1aE\xdf\xa3 synthetic-webm-bytes " * 64  # licence-clean deterministic fixture bytes
TITLE = "File:Street crossing Pune 2026.webm"
UPLOAD_URL = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Street_crossing_Pune_2026.webm"


def api_response(**over) -> dict:
    ext = {
        "License": {"value": over.get("license", "cc-by-sa-4.0")},
        "LicenseShortName": {"value": "CC BY-SA 4.0"},
        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
        "Artist": {"value": over.get("artist", '<a href="//commons.wikimedia.org/wiki/User:Example">Example Author</a>')},
        "Attribution": {"value": "Example Author, CC BY-SA 4.0"},
        "DateTimeOriginal": {"value": over.get("dto", "2026-05-02")},
    }
    if over.get("license") is None and "license" in over:
        del ext["License"]
    info = {"timestamp": over.get("uploaded", "2026-05-10T08:00:00Z"), "user": "Example", "size": len(over.get("media", MEDIA)),
            "width": over.get("width", 1280), "height": over.get("height", 720), "duration": over.get("duration", 12.5), "sha1": hashlib.sha1(over.get("media", MEDIA)).hexdigest(),
            "mime": over.get("mime", "video/webm"), "mediatype": over.get("mediatype", "VIDEO"),
            "url": over.get("url", UPLOAD_URL), "descriptionurl": "https://commons.wikimedia.org/wiki/File:Street_crossing_Pune_2026.webm",
            "extmetadata": ext, "metadata": []}
    return {"query": {"pages": [{"pageid": 4242, "title": over.get("title", TITLE), "imageinfo": [info],
                                 "revisions": [{"revid": over.get("revid", 777), "timestamp": "2026-05-11T00:00:00Z"}]}]}}


class FakeNet:
    """Serves API JSON and media bytes; records every request's URL and headers."""

    def __init__(self, response: dict | None = None, media: bytes = MEDIA, routes: dict | None = None):
        self.response = response or api_response()
        self.media = media
        self.routes = routes or {}
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, url, headers):
        self.requests.append((url, dict(headers)))
        if url in self.routes:
            status, hdrs, body = self.routes[url]
            return status, hdrs, io.BytesIO(body)
        if url.startswith(commons.API):
            return 200, {}, io.BytesIO(json.dumps(self.response).encode())
        if url == UPLOAD_URL:
            return 200, {}, io.BytesIO(self.media)
        return 404, {}, io.BytesIO(b"")


def transport(net: FakeNet) -> Transport:
    return Transport(commons.ALLOWED_HOSTS, "MAVI-test/1.0 (contact: ops@example.org)", fetch=net, sleep=lambda s: None)


def admitted(**over) -> dict:
    decision = {
        "fileTitle": TITLE, "pageRevisionId": 777, "fileSha1": hashlib.sha1(MEDIA).hexdigest(), "state": "ADMITTED_FOR_PILOT",
        "intendedRole": "operational-candidate", "siteId": "site-pune-a", "viewpointId": "view-01", "reviewedBy": "Aarav",
        "reason": None, "freshnessReferenceDate": "2026-03-01",
        "capture": {"start": "2026-05-02", "end": "2026-05-02", "confidence": "high",
                    "evidenceKinds": ["embedded-container-metadata"], "evidence": "container creation_time 2026-05-02T06:10Z"},
        "rightsReview": {"reviewedBy": "Aarav", "determination": "PERMITTED_FOR_PILOT_ACQUISITION", "evidence": "R-5 note 2026-10-01"},
        "privacyReview": {"reviewedBy": "Aarav", "basis": "public street; no identity processing"},
    }
    decision.update(over)
    return decision


def meta(**over) -> dict:
    return commons.parse_file_metadata(api_response(**over))


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "controlled-store"
    root.mkdir()
    return root


# ---------------------------------------------------------------- admission rules

def test_capture_publication_and_acquisition_times_stay_distinct(store):
    net = FakeNet()
    acq.acquire(store, [admitted()], transport(net))
    receipt = _only_receipt(store)
    assert receipt["publishedAtUtc"] == "2026-05-10T08:00:00Z"
    assert receipt["capture"]["start"] == "2026-05-02"
    assert receipt["declaredCaptureDate"] == "2026-05-02"
    assert receipt["acquisition"]["acquiredAtUtc"] not in ("2026-05-10T08:00:00Z", "2026-05-02")
    assert receipt["admissionState"] == "ADMITTED_FOR_PILOT" and receipt["freshness"] == "CAPTURE_AFTER_REFERENCE"


def test_upload_time_is_never_capture_evidence():
    decision = admitted(capture={"start": "2026-05-10", "end": "2026-05-10", "confidence": "high",
                                 "evidenceKinds": ["upload-timestamp"], "evidence": "file uploaded that day"})
    state, blockers = admission.derive_state(meta(), decision)
    assert state == "PROVENANCE_PENDING" and "capture-evidence-missing-or-upload-derived" in blockers
    # Discovery never copies the upload time into the capture fields.
    receipt = admission.build_receipt(meta(dto=None), None, "0" * 64, None)
    assert receipt["capture"]["start"] is None and receipt["admissionState"] == "PROVENANCE_PENDING"


@pytest.mark.parametrize("capture", [
    {"start": None, "end": None, "confidence": "high", "evidenceKinds": ["uploader-statement"], "evidence": "x"},
    {"start": "2026-05-02", "end": "2026-05-02", "confidence": "low", "evidenceKinds": ["uploader-statement"], "evidence": "x"},
    {"start": "2026-05-02", "end": "2026-05-02", "confidence": "high", "evidenceKinds": [], "evidence": "x"},
])
def test_ambiguous_capture_provenance_cannot_be_admitted(capture):
    state, _ = admission.derive_state(meta(), admitted(capture=capture))
    assert state == "PROVENANCE_PENDING"


def test_capture_interval_straddling_the_reference_is_not_fresh():
    decision = admitted(capture={"start": "2026-02-01", "end": "2026-05-01", "confidence": "medium",
                                 "evidenceKinds": ["uploader-statement"], "evidence": "spring 2026"})
    assert admission.freshness(decision) == "UNDETERMINED"
    state, blockers = admission.derive_state(meta(), decision)
    assert state == "PROVENANCE_PENDING" and "freshness-not-established" in blockers
    # The same file can still be training-only without a freshness claim.
    assert admission.derive_state(meta(), dict(decision, intendedRole="training-only"))[0] == "ADMITTED_FOR_PILOT"


@pytest.mark.parametrize("licence", [None, "fair-use", "cc-by-nc-4.0", "cc-by-nd-4.0", "copyrighted"])
def test_unsupported_or_unknown_licence_cannot_be_admitted(licence):
    state, blockers = admission.derive_state(meta(license=licence), admitted())
    assert state == "RIGHTS_PENDING" and any(b.startswith(("file-licence", "licence-restricts")) for b in blockers)


def test_open_licence_still_needs_named_rights_and_privacy_reviews():
    assert admission.derive_state(meta(), admitted(rightsReview={}))[0] == "RIGHTS_PENDING"
    assert admission.derive_state(meta(), admitted(privacyReview={}))[0] == "RIGHTS_PENDING"


def test_rejection_and_reference_need_reasons():
    with pytest.raises(CorpusError):
        admission.derive_state(meta(), admitted(state="REJECTED", reason=None))
    assert admission.derive_state(meta(), admitted(state="REJECTED", reason="handheld tourist clip, not CCTV-like"))[0] == "REJECTED"
    with pytest.raises(CorpusError):
        admission.derive_state(meta(), admitted(state="REFERENCE_ONLY", reason="x", intendedRole="operational-candidate"))


@pytest.mark.parametrize("title", ["Category:Traffic in India", "File:*.webm", "File:Traffic*", "Commons", "File:still.jpg"])
def test_no_category_wildcard_or_still_can_stand_for_a_file(title):
    with pytest.raises(CorpusError):
        admission.require_file_title(title)


def test_provider_or_category_membership_alone_never_admits():
    # Discovery with a perfect open licence yields DISCOVERED, never ADMITTED_FOR_PILOT.
    state, _ = admission.derive_state(meta(), None)
    assert state == "DISCOVERED"
    with pytest.raises((CorpusError, acq.StoreError)):
        acq.load_decisions(_write_decisions(Path("/nonexistent-never-used"), None))


def test_still_image_is_rejected_as_not_continuous_video():
    state, blockers = admission.derive_state(meta(mediatype="BITMAP", mime="image/jpeg"), admitted())
    assert state == "REJECTED" and "not-continuous-video" in blockers


OGV_TITLE = "File:Street crossing Pune 2026.ogv"


@pytest.mark.parametrize("mime", ["video/webm", "video/ogg", "video/mpeg", "video/mp4"])
def test_existing_video_mime_types_are_still_continuous_video(mime):
    assert admission.is_continuous_video(meta(mime=mime))
    assert admission.derive_state(meta(mime=mime), None)[0] == "DISCOVERED"
    assert admission.derive_state(meta(mime=mime), admitted())[0] == "ADMITTED_FOR_PILOT"


def test_commons_ogv_reported_as_application_ogg_is_continuous_video():
    # Commons reports every Ogg container as application/ogg; mediatype VIDEO is its content classification.
    ogv = meta(title=OGV_TITLE, mime="application/ogg", mediatype="VIDEO")
    assert admission.is_continuous_video(ogv)
    assert admission.derive_state(ogv, None) == ("DISCOVERED", [])
    assert admission.derive_state(ogv, admitted(fileTitle=OGV_TITLE)) == ("ADMITTED_FOR_PILOT", [])
    # An .ogg extension holding Theora video is the same case.
    assert admission.is_continuous_video(meta(title="File:Street crossing Pune 2026.ogg", mime="application/ogg"))


def test_admitted_commons_ogv_is_acquired_and_verified(store):
    net = FakeNet(api_response(title=OGV_TITLE, mime="application/ogg"))
    summary = acq.acquire(store, [admitted(fileTitle=OGV_TITLE)], transport(net))
    receipt = _only_receipt(store)
    assert summary["failed"] == 0 and receipt["admissionState"] == "ADMITTED_FOR_PILOT"
    assert receipt["declaredMedia"]["mime"] == "application/ogg" and receipt["acquisition"]["status"] == "ACQUIRED"
    assert acq.verify(store) == []


@pytest.mark.parametrize("over", [
    {"title": "File:Street ambience Pune 2026.ogg", "mediatype": "AUDIO", "width": 0, "height": 0},  # Vorbis/Opus audio only
    {"title": "File:Street ambience Pune 2026.oga", "mediatype": "AUDIO", "width": 0, "height": 0},
    {"title": OGV_TITLE, "mediatype": "AUDIO", "width": 0, "height": 0},                              # wrong-extension audio
    {"title": OGV_TITLE, "mediatype": "VIDEO", "width": 0, "height": 0},                              # no frame size
    {"title": OGV_TITLE, "mediatype": "VIDEO", "width": 1280, "height": None},
    {"title": OGV_TITLE, "mediatype": "VIDEO", "width": True, "height": True},                        # bool is not a size
    {"title": TITLE, "mediatype": "VIDEO"},                                                           # application/ogg on .webm
    {"title": OGV_TITLE, "mediatype": "BITMAP"},
])
def test_non_video_ogg_is_not_admitted_as_continuous_video(over):
    if over["title"].endswith(".oga"):
        with pytest.raises(CorpusError):  # .oga is not even an admissible file title
            meta(mime="application/ogg", **over)
        return
    candidate = meta(mime="application/ogg", **over)
    assert not admission.is_continuous_video(candidate)
    state, blockers = admission.derive_state(candidate, admitted(fileTitle=over["title"]))
    assert state == "REJECTED" and "not-continuous-video" in blockers


@pytest.mark.parametrize("mime", ["application/octet-stream", "application/x-matroska", "application/mp4", "video/quicktime", None])
def test_no_other_mime_is_accepted_even_with_mediatype_video(mime):
    candidate = meta(title=OGV_TITLE, mime=mime, mediatype="VIDEO")
    assert not admission.is_continuous_video(candidate)
    assert admission.derive_state(candidate, None)[0] == "REJECTED"


def test_review_bound_to_a_different_revision_is_not_admitted():
    state, blockers = admission.derive_state(meta(revid=778), admitted())
    assert state == "PROVENANCE_PENDING" and "reviewed-revision-differs-from-current" in blockers


def test_transcoded_or_thumbnail_urls_are_refused():
    for url in ("https://upload.wikimedia.org/wikipedia/commons/transcoded/a/ab/X.webm/X.webm.480p.vp9.webm",
                "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.webm/320px--X.webm.jpg"):
        with pytest.raises(ValueError):
            meta(url=url)


def test_receipts_refuse_local_paths():
    with pytest.raises(CorpusError):
        admission.build_receipt(meta(), admitted(reason="see C:\\Users\\ops\\notes.txt", state="REJECTED"), "0" * 64, None)


# ---------------------------------------------------------------- transport safety

def test_https_only_and_host_allow_list():
    t = transport(FakeNet())
    for url in ("http://upload.wikimedia.org/x", "https://evil.example.com/x", "https://user:pw@upload.wikimedia.org/x",
                "https://upload.wikimedia.org:8443/x", "file:///etc/passwd", "ftp://upload.wikimedia.org/x"):
        with pytest.raises(TransportError):
            t.check_url(url)


def test_redirect_to_unapproved_host_is_refused():
    net = FakeNet(routes={UPLOAD_URL: (302, {"Location": "https://evil.example.com/stolen.webm"}, b"")})
    with pytest.raises(TransportError, match="not allow-listed"):
        transport(net).open(UPLOAD_URL)
    net = FakeNet(routes={UPLOAD_URL: (302, {"Location": "http://upload.wikimedia.org/x.webm"}, b"")})
    with pytest.raises(TransportError, match="non-HTTPS"):
        transport(net).open(UPLOAD_URL)


def test_redirects_are_bounded():
    loop = "https://upload.wikimedia.org/wikipedia/commons/a/ab/loop.webm"
    net = FakeNet(routes={loop: (302, {"Location": loop}, b"")})
    with pytest.raises(TransportError, match="too many redirects"):
        transport(net).open(loop)
    assert len(net.requests) == 6


def test_no_credentials_are_sent_or_serialized(store):
    net = FakeNet()
    acq.acquire(store, [admitted()], transport(net))
    for _url, headers in net.requests:
        assert set(headers) == {"User-Agent", "Accept"}
    everything = b"".join(p.read_bytes() for p in store.rglob("*.json"))
    assert b"Authorization" not in everything and b"Cookie" not in everything and b"ops@example.org" not in everything


def test_failed_transfer_does_not_promote_a_target(store):
    net = FakeNet(media=MEDIA[:-5])
    summary = acq.acquire(store, [admitted()], transport(net))
    assert summary["failed"] == 1 and ("SHA-1" in summary["items"][0]["error"] or "size" in summary["items"][0]["error"])
    assert not list((store / "media").rglob("*.webm")) and not list(store.rglob("*.partial"))


def test_same_size_different_bytes_fail_the_provider_sha1(store):
    tampered = bytes(b ^ 0xFF for b in MEDIA)
    summary = acq.acquire(store, [admitted()], transport(FakeNet(media=tampered)))
    assert summary["failed"] == 1 and "SHA-1" in summary["items"][0]["error"]
    assert not list((store / "media").rglob("*.webm")) and not list(store.rglob("*.partial"))


def test_rerun_is_idempotent_and_differing_target_is_refused(store):
    net = FakeNet()
    acq.acquire(store, [admitted()], transport(net))
    first = _only_receipt(store)
    second = acq.acquire(store, [admitted()], transport(FakeNet()))
    assert second["failed"] == 0
    statuses = {json.loads(p.read_bytes())["acquisition"]["status"] for p in (store / "receipts").glob("*.json")}
    assert statuses == {"ACQUIRED", "ALREADY_PRESENT_VERIFIED"}
    media = store / first["acquisition"]["storeRelativePath"]
    media.write_bytes(b"tampered")
    third = acq.acquire(store, [admitted()], transport(FakeNet()))
    assert third["failed"] == 1 and "differs" in third["items"][0]["error"]
    assert media.read_bytes() == b"tampered"


def test_rate_limit_backs_off_boundedly_then_fails_closed():
    sleeps = []
    net = FakeNet(routes={UPLOAD_URL: (429, {}, b"slow down")})
    t = Transport(commons.ALLOWED_HOSTS, "MAVI-test/1.0", fetch=net, sleep=sleeps.append)
    with pytest.raises(TransportError, match="HTTP 429"):
        t.open(UPLOAD_URL)
    assert sleeps == [30, 60] and len(net.requests) == 3


# ---------------------------------------------------------------- integrity

def test_exact_original_sha256_is_retained_and_verify_detects_byte_changes(store):
    acq.acquire(store, [admitted()], transport(FakeNet()))
    receipt = _only_receipt(store)
    assert receipt["acquisition"]["sha256"] == hashlib.sha256(MEDIA).hexdigest()
    assert receipt["acquisition"]["sha1"] == hashlib.sha1(MEDIA).hexdigest() == receipt["declaredMedia"]["sha1"]
    assert acq.verify(store) == []
    (store / receipt["acquisition"]["storeRelativePath"]).write_bytes(MEDIA[::-1])
    assert any("differ" in p for p in acq.verify(store))


def test_receipts_are_canonical_content_addressed_utf8_lf(store):
    acq.acquire(store, [admitted()], transport(FakeNet()))
    for path in list((store / "receipts").glob("*.json")) + list((store / "evidence").glob("*.json")):
        blob = path.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == path.stem
        assert blob == canonical_json(json.loads(blob)) and not blob.startswith(b"\xef\xbb\xbf") and b"\r" not in blob
    summary = (store / "source-acquisition-summary.json").read_bytes()
    assert summary == canonical_json(json.loads(summary))


def test_editing_a_receipt_changes_its_identity(store):
    acq.acquire(store, [admitted()], transport(FakeNet()))
    path = next((store / "receipts").glob("*.json"))
    doc = json.loads(path.read_bytes())
    doc["acquisition"]["sha256"] = "0" * 64
    path.write_bytes(canonical_json(doc))
    assert any("identity" in p for p in acq.verify(store))


# ---------------------------------------------------------------- separation

def test_store_inside_git_is_refused(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(acq.StoreError):
        acq.acquire(tmp_path / "store", [admitted()], transport(FakeNet()))
    with pytest.raises(acq.StoreError):
        acq.assert_controlled_store(REPO / "tmp-source-store")


def test_only_admitted_items_are_downloaded(store):
    net = FakeNet()
    acq.acquire(store, [admitted(rightsReview={})], transport(net))
    assert not any(u == UPLOAD_URL for u, _ in net.requests)
    assert _only_receipt(store)["admissionState"] == "RIGHTS_PENDING" and _only_receipt(store)["acquisition"] is None


def test_acquisition_code_stays_outside_the_corpus_package_and_away_from_candidates():
    corpus = QUALIFICATION / "attributes" / "corpus"
    for path in corpus.rglob("*.py"):
        assert not re.search(r"^\s*(?:import|from)\s+(?:urllib|http|socket|ssl|requests)\b", path.read_text(encoding="utf-8"), re.M), path
    package = QUALIFICATION / "source_acquisition"
    source = "\n".join(p.read_text(encoding="utf-8") for p in package.rglob("*.py"))
    for forbidden in ("model_selection", "predictions", "f1", "partition", "annotation", "frozen", "manifest import", "build_corpus"):
        assert not re.search(rf"^\s*(?:import|from)\s+[\w.]*{forbidden}", source, re.M), forbidden
    assert "mavi-s2c-f1-evidence-record" not in source and "mavi-attribute-corpus-manifest" not in source


def _only_receipt(store: Path) -> dict:
    receipts = sorted((store / "receipts").glob("*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(receipts[-1].read_bytes())


def _write_decisions(path: Path, decisions) -> Path:
    import tempfile
    target = Path(tempfile.mkdtemp()) / "decisions.json"
    target.write_text(json.dumps({"schemaVersion": "mavi-s2c-source-admission-decisions-v1",
                                  "decisions": decisions or [{"fileTitle": "Category:Traffic in India"}]}), encoding="utf-8")
    return target
