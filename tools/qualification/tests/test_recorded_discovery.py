"""Recorded, metadata-only discovery wrapper: stop latch, budgets, deadlines and durable capture.

Deterministic fake transports and a fake clock only: CI never touches the network.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

from source_acquisition import commons
from source_acquisition import recorded_discovery as rd
from source_acquisition.acquire import StoreError

QUALIFICATION = Path(__file__).resolve().parents[1]
REPO = QUALIFICATION.parents[1]
CONTACT = "https://github.com/hariomahlawat/MAVI"
STAMP = "20261001T000000Z"
UTC = "2026-10-01T00:00:00.000Z"
TITLES = ["File:Crossing A 2026.webm", "File:Crossing B 2026.webm"]
SCOPES = (
    {"id": "P1", "kind": "search", "query": "traffic India 2026", "pool": "primary"},
    {"id": "P4", "kind": "category", "query": "Category:Videos of streets in India", "pool": "primary"},
    {"id": "S1", "kind": "category", "query": "Category:Videos of street scenes", "pool": "secondary"},
)


class Killed(BaseException):
    """Stands in for a hard process kill: nothing in the wrapper catches it."""


class Clock:
    def __init__(self, step_per_fetch: float = 0.0):
        self.t = 1000.0
        self.sleeps: list[float] = []
        self.step = step_per_fetch

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class Chunks:
    """A response stream that yields chunks, then optionally raises."""

    def __init__(self, chunks: list[bytes], raise_after: BaseException | None = None):
        self.chunks = list(chunks)
        self.raise_after = raise_after
        self.closed = False

    def read(self, _n: int = -1) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        if self.raise_after is not None:
            raise self.raise_after
        return b""

    def close(self) -> None:
        self.closed = True


def metadata(title: str, pageid: int) -> dict:
    sha1 = hashlib.sha1(title.encode()).hexdigest()
    info = {"timestamp": "2026-05-10T08:00:00Z", "user": "Example", "size": 1000, "width": 1280, "height": 720,
            "duration": 12.5, "sha1": sha1, "mime": "video/webm", "mediatype": "VIDEO",
            "url": f"https://upload.wikimedia.org/wikipedia/commons/a/ab/{pageid}.webm",
            "descriptionurl": f"https://commons.wikimedia.org/wiki/{pageid}",
            "extmetadata": {"License": {"value": "cc-by-4.0"}, "Artist": {"value": "Example Author"},
                            "DateTimeOriginal": {"value": "2026-05-02"}}, "metadata": []}
    return {"query": {"pages": [{"pageid": pageid, "title": title, "imageinfo": [info],
                                 "revisions": [{"revid": pageid + 1, "timestamp": "2026-05-11T00:00:00Z"}]}]}}


def ok(document: dict, headers: dict | None = None):
    return 200, headers or {}, io.BytesIO(json.dumps(document).encode())


class Net:
    """Routes by request kind; records every URL actually fetched."""

    def __init__(self, titles=TITLES, list_route=None, meta_route=None, preflight_route=None, clock: Clock | None = None,
                 before_first=None):
        self.titles = titles
        self.list_route = list_route
        self.meta_route = meta_route
        self.preflight_route = preflight_route
        self.clock = clock
        self.before_first = before_first
        self.calls: list[str] = []
        self.bodies: dict[str, bytes] = {}

    def __call__(self, url, headers):
        if not self.calls and self.before_first is not None:
            self.before_first()
        self.calls.append(url)
        if self.clock is not None:
            self.clock.t += self.clock.step
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if params.get("meta") == "siteinfo":
            return self.preflight_route(url) if self.preflight_route else ok({"query": {"general": {"sitename": "Commons"}}})
        if params.get("list"):
            if self.list_route:
                return self.list_route(url)
            key = "search" if params["list"] == "search" else "categorymembers"
            body = json.dumps({"query": {key: [{"title": t} for t in self.titles] + [{"title": "File:Still.jpg"}]}}).encode()
            self.bodies[url] = body
            return 200, {}, io.BytesIO(body)
        title = params["titles"]
        if self.meta_route:
            routed = self.meta_route(title)
            if routed is not None:
                return routed
        return ok(metadata(title, 100 + sorted(self.titles).index(title)))


def run(tmp_path: Path, net: Net, clock: Clock, scopes=SCOPES, **limits):
    root = tmp_path / "acquisition"
    root.mkdir(exist_ok=True)
    return rd.run_discovery(root, CONTACT, stamp=STAMP, scopes=scopes, limits={**rd.LIMITS, **limits}, fetch=net,
                            sleep=clock.sleep, monotonic=clock.monotonic, utc=lambda: UTC, hard_deadline=False)


def events(run_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (run_dir / "capture" / "events.jsonl").read_bytes().splitlines()]


def scope_records(run_dir: Path) -> dict:
    return {r["scope"]: r for r in (json.loads(l) for l in (run_dir / "capture" / "scopes.jsonl").read_bytes().splitlines())
            if r["event"] == "scope"}


def test_the_seven_predeclared_scopes_are_kept_verbatim_with_the_category_caveat():
    assert [(s["id"], s["kind"], s["query"], s["pool"]) for s in rd.PILOT_RETRY_SCOPES] == [
        ("P1", "search", "traffic India 2026", "primary"),
        ("P2", "search", "street India 2026", "primary"),
        ("P3", "search", "pedestrians market India", "primary"),
        ("P4", "category", "Category:Videos of streets in India", "primary"),
        ("P5", "category", "Category:Videos of road traffic in India", "primary"),
        ("S1", "category", "Category:Videos of street scenes", "secondary"),
        ("S2", "category", "Category:Videos of road traffic", "secondary"),
    ]
    assert "Subcategory members are excluded" in rd.CATEGORY_CAVEAT
    assert "does not establish" in rd.CATEGORY_CAVEAT
    config = rd.build_config(CONTACT)
    assert config["userAgent"] == f"MAVI-S2c-B0-source-acquisition/1.0 (Development qualification tooling; contact: {CONTACT})"
    assert config["limits"]["attemptBudget"] == 160 and config["limits"]["scopeLimit"] == 20
    with pytest.raises(StoreError):
        rd.build_config("ops (x)")


def test_config_and_its_hash_are_durable_before_the_first_request(tmp_path):
    clock = Clock()
    seen = {}

    def check():
        config_dir = tmp_path / "acquisition" / f"commons-discovery-retry-{STAMP}" / "config"
        data = (config_dir / "run-config.json").read_bytes()
        seen["sha"] = (config_dir / "run-config.sha256").read_text().split()[0]
        assert hashlib.sha256(data).hexdigest() == seen["sha"]
        assert json.loads(data)["userAgent"].endswith(f"contact: {CONTACT})")

    run_dir, status = run(tmp_path, Net(clock=clock, before_first=check), clock, secondaryOnlyIfPrimaryDescribedBelow=1)
    assert seen["sha"] and events(run_dir)[0] == {"event": "run-start", "utc": UTC, "configSha256": seen["sha"]}
    assert status["status"] == "COMPLETE"


def test_complete_run_retains_raw_lists_paired_attempt_records_and_reports(tmp_path):
    clock = Clock()
    net = Net(clock=clock)
    run_dir, status = run(tmp_path, net, clock, secondaryOnlyIfPrimaryDescribedBelow=1)
    assert status["status"] == "COMPLETE" and status["stopReason"] is None
    # preflight + (list + 2 metadata) for P1 and P4; S1 is not needed.
    assert len(net.calls) == 7 and status["attemptsStarted"] == 7 and status["attemptsCompleted"] == 7
    log = events(run_dir)
    starts = [e["attempt"] for e in log if e["event"] == "attempt-start"]
    ends = [e["attempt"] for e in log if e["event"] == "attempt-end"]
    assert starts == ends == list(range(1, 8))
    bodies = sorted((run_dir / "capture" / "bodies").iterdir())
    assert [p.suffix for p in bodies] == [".body"] * 7
    list_url = next(u for u in net.calls if "list=search" in u)
    list_attempt = net.calls.index(list_url) + 1
    assert (run_dir / "capture" / "bodies" / f"attempt-{list_attempt:06d}.body").read_bytes() == net.bodies[list_url]
    scopes = scope_records(run_dir)
    assert scopes["P1"]["status"] == "COMPLETE" and scopes["P1"]["categoryCaveat"] is None
    assert scopes["P1"]["listRows"] == 3 and scopes["P1"]["videoTitles"] == TITLES
    assert scopes["P4"]["categoryCaveat"] == rd.CATEGORY_CAVEAT
    assert scopes["S1"]["status"] == "NOT_NEEDED"
    store = run_dir / "store"
    assert len(list((store / "evidence").glob("*.json"))) == 2
    assert not (store / "receipts").exists() and not (store / "media").exists()
    # pacing: attempts within a scope waited the minimum interval; the scope gap already exceeds it.
    assert clock.sleeps == [5.0, 5.0, 5.0, 60, 5.0, 5.0]
    assert CONTACT not in b"".join(p.read_bytes() for p in store.rglob("*.json")).decode()


def test_attempt_budget_counts_every_fetch_and_no_request_starts_after_it(tmp_path):
    clock = Clock()
    net = Net(clock=clock)
    run_dir, status = run(tmp_path, net, clock, attemptBudget=3)
    assert len(net.calls) == 3  # preflight, list, first metadata; the second metadata request never starts
    assert status["status"] == "STOPPED" and status["stopReason"] == "attempt-budget-exhausted"
    scopes = scope_records(run_dir)
    assert scopes["P1"]["status"] == "PER_FILE_ERRORS" and scopes["P1"]["itemErrors"] == 1
    assert scopes["P4"]["status"] == "NOT_STARTED" and scopes["S1"]["status"] == "NOT_STARTED"
    report = json.loads((run_dir / "store" / "discovery" / f"{scopes['P1']['discoveryReportSha256']}.json").read_bytes())
    assert [i["error"] is None for i in report["items"]] == [True, False]


def test_redirect_hops_are_counted_and_a_redirect_off_the_api_is_refused(tmp_path):
    clock = Clock()
    hops = []

    def list_route(url):
        if "hop=1" not in url:
            hops.append(url)
            return 302, {"Location": url + "&hop=1"}, io.BytesIO(b"")
        return ok({"query": {"search": [{"title": TITLES[0]}]}})

    def meta_route(title):
        return 302, {"Location": "https://upload.wikimedia.org/wikipedia/commons/a/ab/x.webm"}, io.BytesIO(b"")

    net = Net(titles=TITLES[:1], list_route=list_route, meta_route=meta_route, clock=clock)
    run_dir, status = run(tmp_path, net, clock)
    assert len(hops) == 1 and sum(1 for u in net.calls if "list=search" in u) == 2  # both hops were real attempts
    assert not any("upload.wikimedia.org" in u for u in net.calls)  # the media hop never opened a socket
    assert status["stopReason"] == "refused-url:upload.wikimedia.org" and status["attemptsStarted"] == 4


def test_http_429_latches_at_once_and_the_helper_never_retries(tmp_path):
    clock = Clock()
    net = Net(clock=clock, list_route=lambda url: (429, {"Retry-After": "7", "Set-Cookie": "secret", "X-RateLimit-Remaining": "0"},
                                                    io.BytesIO(b"You are making too many requests")))
    run_dir, status = run(tmp_path, net, clock)
    assert len(net.calls) == 2 and status["stopReason"] == "http-429"
    assert 30 not in clock.sleeps and 60 not in clock.sleeps  # the helper's back-off was refused
    end = [e for e in events(run_dir) if e["event"] == "attempt-end"][-1]
    assert end["headers"] == {"retry-after": "7", "x-ratelimit-remaining": "0"} and end["status"] == 429
    assert scope_records(run_dir)["P1"]["status"] == "LIST_FAILED"


def test_soft_deadline_stops_before_the_next_attempt(tmp_path):
    clock = Clock(step_per_fetch=100.0)
    net = Net(clock=clock)
    run_dir, status = run(tmp_path, net, clock, softDeadlineSeconds=250, minIntervalSeconds=0)
    assert status["stopReason"] == "soft-deadline"
    assert len(net.calls) == 3 and clock.t <= 1000 + 300  # no attempt started past the deadline


def test_network_failure_latches_and_the_partial_report_survives(tmp_path):
    clock = Clock()

    def meta_route(title):
        if title == TITLES[0]:
            raise urllib.error.URLError("connection reset")
        return None

    net = Net(clock=clock, meta_route=meta_route)
    run_dir, status = run(tmp_path, net, clock)
    assert status["stopReason"] == "network-failure:URLError" and len(net.calls) == 3
    scopes = scope_records(run_dir)
    assert scopes["P1"]["status"] == "PER_FILE_ERRORS" and scopes["P1"]["itemErrors"] == 2
    assert (run_dir / "store" / "discovery" / f"{scopes['P1']['discoveryReportSha256']}.json").exists()
    end = [e for e in events(run_dir) if e["event"] == "attempt-end"][-1]
    assert end["outcome"] == "network-error:URLError" and end["complete"] is False


def test_read_failure_keeps_the_partial_body_and_never_marks_it_complete(tmp_path):
    clock = Clock()
    net = Net(clock=clock, list_route=lambda url: (200, {}, Chunks([b'{"query": {"sea'], raise_after=OSError("reset"))))
    run_dir, status = run(tmp_path, net, clock)
    part = run_dir / "capture" / "bodies" / "attempt-000002.part"
    assert part.read_bytes() == b'{"query": {"sea'
    assert not (run_dir / "capture" / "bodies" / "attempt-000002.body").exists()
    assert status["incompleteBodies"] == ["attempt-000002.part"] and status["stopReason"] == "read-error:OSError"
    end = [e for e in events(run_dir) if e["event"] == "attempt-end"][-1]
    assert end["complete"] is False and end["bytes"] == len(b'{"query": {"sea')


def test_over_limit_body_is_partial_and_latches(tmp_path):
    clock = Clock()
    net = Net(clock=clock, list_route=lambda url: (200, {}, Chunks([b"x" * 60, b"y" * 60])))
    run_dir, status = run(tmp_path, net, clock, bodyLimitBytes=100)
    assert status["stopReason"] == "over-body-limit" and status["incompleteBodies"] == ["attempt-000002.part"]


def test_interrupt_mid_read_is_recorded_and_capture_is_preserved(tmp_path):
    clock = Clock()
    net = Net(clock=clock, list_route=lambda url: (200, {}, Chunks([b'{"partial"'], raise_after=KeyboardInterrupt())))
    run_dir, status = run(tmp_path, net, clock)
    assert status["status"] == "INTERRUPTED" and status["stopReason"] == "interrupted"
    assert (run_dir / "capture" / "bodies" / "attempt-000002.part").read_bytes() == b'{"partial"'
    end = [e for e in events(run_dir) if e["event"] == "attempt-end"][-1]
    assert end["outcome"] == "interrupted" and end["complete"] is False
    assert scope_records(run_dir) == {}  # the interrupted scope never wrote a completion record


def test_finalize_identifies_an_attempt_left_without_an_end_record(tmp_path):
    clock = Clock()

    def meta_route(title):
        raise Killed()

    net = Net(clock=clock, meta_route=meta_route)
    with pytest.raises(Killed):
        run(tmp_path, net, clock)
    run_dir = tmp_path / "acquisition" / f"commons-discovery-retry-{STAMP}"
    assert not (run_dir / "run-status.json").exists()
    status = rd.finalize(run_dir)
    assert status["status"] == "INTERRUPTED" and status["attemptsWithoutEndRecord"] == [3]
    assert len(list((run_dir / "store" / "evidence").glob("*.json"))) == 0
    with pytest.raises(StoreError):
        rd.finalize(run_dir)  # never overwrites


def test_api_error_body_latches_and_no_metadata_request_follows(tmp_path):
    clock = Clock()
    net = Net(clock=clock, list_route=lambda url: ok({"error": {"code": "maxlag", "info": "Waiting for a database server"}}))
    run_dir, status = run(tmp_path, net, clock)
    assert status["stopReason"] == "api-error:maxlag" and len(net.calls) == 2
    assert scope_records(run_dir)["P1"]["status"] == "API_ERROR"
    assert not (run_dir / "store").exists()


def test_preflight_refusal_stops_before_any_scope(tmp_path):
    clock = Clock()
    net = Net(clock=clock, preflight_route=lambda url: (503, {"Retry-After": "5"}, io.BytesIO(b"busy")))
    run_dir, status = run(tmp_path, net, clock)
    assert len(net.calls) == 1 and status["stopReason"] == "http-503"
    assert {s["status"] for s in scope_records(run_dir).values()} == {"NOT_STARTED"}


def test_per_file_error_completes_the_scope_then_stops_the_run(tmp_path):
    clock = Clock()

    def meta_route(title):
        if title == TITLES[0]:
            return ok({"query": {"pages": [{"title": title, "missing": True}]}})
        return None

    net = Net(clock=clock, meta_route=meta_route)
    run_dir, status = run(tmp_path, net, clock)
    scopes = scope_records(run_dir)
    assert scopes["P1"]["status"] == "PER_FILE_ERRORS" and scopes["P1"]["describedWithoutError"] == 1
    assert scopes["P4"]["status"] == "NOT_STARTED" and status["stopReason"] == "per-file-error"
    assert len(net.calls) == 4  # both metadata requests of P1 ran; nothing after the scope


def test_discovery_only_refuses_media_and_non_api_urls_before_any_socket(tmp_path):
    for url in ("https://upload.wikimedia.org/wikipedia/commons/a/ab/x.webm",
                "https://commons.wikimedia.org/wiki/File:X.webm",
                "http://commons.wikimedia.org/w/api.php?action=query",
                "https://commons.wikimedia.org:8443/w/api.php?action=query",
                "https://commons.wikimedia.org/w/api.php?action=edit"):
        assert not rd.is_discovery_url(url), url
    assert rd.is_discovery_url(commons.search_query_url("x", 20)) and rd.is_discovery_url(rd.PREFLIGHT_URL)
    called = []
    recorder = rd.Recorder(tmp_path / "capture", attempt_budget=5, min_interval=0, soft_deadline=100, attempt_read_seconds=10,
                           body_limit=100, fetch=lambda u, h: called.append(u), sleep=lambda s: None, monotonic=lambda: 0.0,
                           utc=lambda: UTC)
    with pytest.raises(rd.RunStopped):
        recorder.fetch("https://upload.wikimedia.org/wikipedia/commons/a/ab/x.webm", {})
    with pytest.raises(rd.RunStopped):
        recorder.fetch(rd.PREFLIGHT_URL, {})  # latched: even a valid API request no longer starts
    assert called == [] and recorder.stop_reason == "refused-url:upload.wikimedia.org"


def test_run_directory_is_never_reused_and_must_be_outside_git(tmp_path):
    clock = Clock()
    run(tmp_path, Net(clock=clock), clock)
    with pytest.raises(FileExistsError):
        run(tmp_path, Net(clock=clock), clock)
    with pytest.raises(StoreError):
        rd.run_discovery(REPO / "docs", CONTACT, stamp=STAMP, fetch=Net(), hard_deadline=False)


def test_bundle_writes_a_verified_manifest_and_archive_in_a_new_directory(tmp_path):
    clock = Clock()
    net = Net(clock=clock, list_route=lambda url: (200, {}, Chunks([b'{"q'], raise_after=OSError("reset"))))
    run_dir, _status = run(tmp_path, net, clock)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    destination = rd.bundle(run_dir, evidence, "retry-test")
    manifest = json.loads((destination / "MANIFEST.json").read_bytes())
    roles = {f["path"]: f["role"] for f in manifest["files"]}
    assert roles["config/run-config.json"] == "configuration"
    assert roles["capture/bodies/attempt-000002.part"] == "incomplete-partial-response-body"
    assert roles["capture/bodies/attempt-000001.body"] == "complete-response-body"
    archive = destination / "retry-test.tar.gz"
    digest = (destination / "retry-test.tar.gz.sha256").read_text().split()[0]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest
    with tarfile.open(archive) as tar:
        names = sorted(m.name for m in tar.getmembers())
    assert "retry-test/MANIFEST.json" in names and "retry-test/run-status.json" in names
    with pytest.raises(FileExistsError):
        rd.bundle(run_dir, evidence, "retry-test")
