"""Recorded, metadata-only discovery wrapper: stop latch, budgets, deadlines and durable capture.

Deterministic fake transports and a fake clock only: CI never touches the network.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import time
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
    root.mkdir(parents=True, exist_ok=True)
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
    # preflight + (list + 2 metadata) for P1 + list for P4, whose titles were already described; S1 is not needed.
    assert len(net.calls) == 5 and status["attemptsStarted"] == 5 and status["attemptsCompleted"] == 5
    log = events(run_dir)
    starts = [e["attempt"] for e in log if e["event"] == "attempt-start"]
    ends = [e["attempt"] for e in log if e["event"] == "attempt-end"]
    assert starts == ends == list(range(1, 6))
    bodies = sorted((run_dir / "capture" / "bodies").iterdir())
    assert [p.suffix for p in bodies] == [".body"] * 5
    list_url = next(u for u in net.calls if "list=search" in u)
    list_attempt = net.calls.index(list_url) + 1
    assert (run_dir / "capture" / "bodies" / f"attempt-{list_attempt:06d}.body").read_bytes() == net.bodies[list_url]
    scopes = scope_records(run_dir)
    assert scopes["P1"]["status"] == "COMPLETE" and scopes["P1"]["categoryCaveat"] is None
    assert scopes["P1"]["listRows"] == 3 and scopes["P1"]["videoTitles"] == TITLES
    assert scopes["P4"]["categoryCaveat"] == rd.CATEGORY_CAVEAT
    assert scopes["P4"]["alreadyDescribedTitles"] == TITLES and scopes["P4"]["requestedTitles"] == []
    assert status["describedWithoutError"] == 2  # unique titles, not a per-scope sum
    assert scopes["S1"]["status"] == "NOT_NEEDED"
    store = run_dir / "store"
    assert len(list((store / "evidence").glob("*.json"))) == 2
    assert not (store / "receipts").exists() and not (store / "media").exists()
    # pacing: attempts within a scope waited the minimum interval; the scope gap already exceeds it.
    assert clock.sleeps == [5.0, 5.0, 5.0, 60]
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


def test_soft_deadline_reached_during_a_read_stops_at_the_next_chunk(tmp_path):
    clock = Clock(step_per_fetch=100.0)
    net = Net(clock=clock)
    run_dir, status = run(tmp_path, net, clock, softDeadlineSeconds=250, minIntervalSeconds=0)
    assert status["stopReason"] == "soft-deadline"
    assert len(net.calls) == 3 and clock.t <= 1000 + 300  # attempt 3 started before the deadline; its read was cut off
    assert status["incompleteBodies"] == ["attempt-000003.part"]


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


def test_a_semantically_invalid_metadata_response_latches_before_the_next_title(tmp_path):
    clock = Clock()

    def meta_route(title):
        if title == TITLES[0]:
            return ok({"query": {"pages": [{"title": title, "missing": True}]}})
        return None

    net = Net(clock=clock, meta_route=meta_route)
    run_dir, status = run(tmp_path, net, clock)
    assert len(net.calls) == 3 and not any("Crossing+B" in u for u in net.calls)  # the second title never starts
    assert status["stopReason"] == "metadata-invalid:ValueError"
    scopes = scope_records(run_dir)
    assert scopes["P1"]["status"] == "PER_FILE_ERRORS" and scopes["P1"]["describedWithoutError"] == 0
    assert scopes["P4"]["status"] == "NOT_STARTED"
    report = json.loads((run_dir / "store" / "discovery" / f"{scopes['P1']['discoveryReportSha256']}.json").read_bytes())
    assert [bool(i["error"]) for i in report["items"]] == [True, True]  # the helper still recorded both items


def test_an_unparseable_metadata_body_latches_before_the_next_title(tmp_path):
    clock = Clock()
    net = Net(clock=clock, meta_route=lambda title: (200, {}, io.BytesIO(b"<html>not json</html>")) if title == TITLES[0] else None)
    _run_dir, status = run(tmp_path, net, clock)
    assert len(net.calls) == 3 and status["stopReason"].startswith("metadata-invalid:")


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
    with pytest.raises(StoreError):
        rd.build_config(CONTACT, limits={**rd.LIMITS, "minIntervalSeconds": 0.5})  # no floats reach canonical JSON


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


class ClosingChunks(Chunks):
    """Completes normally; closing it advances the clock (time passes after the read)."""

    def __init__(self, body: bytes, clock: Clock, advance: float):
        super().__init__([body])
        self.clock = clock
        self.advance = advance

    def close(self) -> None:
        super().close()
        self.clock.t += self.advance


class SlowChunks(Chunks):
    """Each read advances the clock, so the per-attempt read-time limit can fire."""

    def __init__(self, chunks: list[bytes], clock: Clock, per_read: float):
        super().__init__(chunks)
        self.clock = clock
        self.per_read = per_read

    def read(self, n: int = -1) -> bytes:
        self.clock.t += self.per_read
        return super().read(n)


def test_transport_refusals_inside_the_helper_latch_before_any_further_request(tmp_path):
    cases = {
        "off-allow-list redirect": (302, {"Location": "https://evil.example/x"}),
        "non-https redirect": (302, {"Location": "http://commons.wikimedia.org/w/api.php?action=query"}),
        "redirect without location": (302, {}),
    }
    for name, (code, headers) in cases.items():
        clock = Clock()
        net = Net(clock=clock, meta_route=lambda title, c=code, h=headers: (c, dict(h), io.BytesIO(b"")))
        run_dir, status = run(tmp_path / name.replace(" ", "-"), net, clock)
        assert len(net.calls) == 3, name  # preflight, list, first metadata; the second title never starts
        assert status["stopReason"].startswith("transport-refused:"), (name, status["stopReason"])
        assert not any("evil.example" in u or u.startswith("http://") for u in net.calls), name
        assert scope_records(run_dir)["P4"]["status"] == "NOT_STARTED", name
    end = [e for e in events(run_dir) if e["event"] == "attempt-end"][-1]
    assert end["status"] == 302


def test_endless_api_redirects_count_every_hop_and_stop_at_too_many(tmp_path):
    clock = Clock()

    def meta_route(title):
        return 302, {"Location": commons.metadata_query_url(title) + "&again=1"}, io.BytesIO(b"")

    net = Net(clock=clock, meta_route=meta_route)
    run_dir, status = run(tmp_path, net, clock)
    metadata_calls = [u for u in net.calls if "titles=" in u]
    assert len(metadata_calls) == 6 and all("Crossing+A" in u for u in metadata_calls)  # 1 + MAX_REDIRECTS hops, title B never
    assert status["attemptsStarted"] == 8 and status["stopReason"].startswith("transport-refused:too many redirects")
    locations = [e["headers"].get("location") for e in events(run_dir) if e["event"] == "attempt-end" and e["status"] == 302]
    assert len(locations) == 6 and all(locations)  # every redirect target is recorded


def test_discovery_url_check_refuses_duplicate_encoded_and_array_action_keys():
    base = "https://commons.wikimedia.org/w/api.php?"
    for query in ("action=query&action=edit", "action=query&%61ction=edit", "action=query&action[]=edit",
                  "action=edit", "format=json"):
        assert not rd.is_discovery_url(base + query), query
    assert not rd.is_discovery_url("https://user@commons.wikimedia.org/w/api.php?action=query")
    assert not rd.is_discovery_url("https://COMMONS.wikimedia.org/w/api.php?action=query")
    assert not rd.is_discovery_url("https://commons.wikimedia.org./w/api.php?action=query")
    assert rd.is_discovery_url(commons.category_query_url("Category:X", 20))


def test_soft_deadline_between_attempts_stops_before_the_next_attempt_starts(tmp_path):
    clock = Clock()
    net = Net(clock=clock, list_route=lambda url: (200, {}, ClosingChunks(json.dumps({"query": {"search": [{"title": TITLES[0]}]}}).encode(),
                                                                         clock, 500.0)))
    run_dir, status = run(tmp_path, net, clock, softDeadlineSeconds=300, minIntervalSeconds=1)
    assert len(net.calls) == 2 and status["stopReason"] == "soft-deadline"
    ends = [e for e in events(run_dir) if e["event"] == "attempt-end"]
    assert ends[-1]["attempt"] == 2 and ends[-1]["complete"] is True  # the list itself completed
    assert max(e["attempt"] for e in events(run_dir) if e["event"] == "attempt-start") == 2


def test_a_pacing_wait_that_would_cross_the_deadline_is_refused(tmp_path):
    clock = Clock()
    net = Net(clock=clock)
    run_dir, status = run(tmp_path, net, clock, softDeadlineSeconds=150, minIntervalSeconds=100)
    assert status["stopReason"] == "soft-deadline" and len(net.calls) == 2
    assert clock.sleeps == [100.0]  # the second wait (to t=1200 > 1150) was refused, not slept


def test_the_per_attempt_read_time_limit_keeps_a_partial_body(tmp_path):
    clock = Clock()
    net = Net(clock=clock, list_route=lambda url: (200, {}, SlowChunks([b'{"a', b'"b', b'"c'], clock, 50.0)))
    run_dir, status = run(tmp_path, net, clock, attemptReadSeconds=60)
    assert status["stopReason"] == "read-time-limit" and status["incompleteBodies"] == ["attempt-000002.part"]
    assert (run_dir / "capture" / "bodies" / "attempt-000002.part").read_bytes() == b'{"a"b'


def test_a_body_of_exactly_the_limit_is_complete_and_one_byte_more_is_not(tmp_path):
    for size, complete in ((100, True), (101, False)):
        clock = Clock()
        net = Net(clock=clock, list_route=lambda url, n=size: (200, {}, Chunks([b"x" * n])))
        run_dir, status = run(tmp_path / str(size), net, clock, bodyLimitBytes=100)
        end = [e for e in events(run_dir) if e["event"] == "attempt-end" and e["attempt"] == 2][0]
        assert end["complete"] is complete and end["bytes"] == size
        assert (run_dir / "capture" / "bodies" / f"attempt-000002.{'body' if complete else 'part'}").exists()


def test_candidate_cap_stops_further_scopes_without_latching(tmp_path):
    clock = Clock()
    net = Net(clock=clock)
    run_dir, status = run(tmp_path, net, clock, candidateCap=2)
    scopes = scope_records(run_dir)
    assert scopes["P1"]["status"] == "COMPLETE" and scopes["P4"]["status"] == "NOT_STARTED"
    assert scopes["P4"]["reason"] == "candidate-cap" and status["status"] == "COMPLETE"


def test_a_local_capture_failure_latches_the_run(tmp_path, monkeypatch):
    clock = Clock()
    net = Net(clock=clock)
    real_replace = rd.os.replace
    calls = {"n": 0}

    def failing_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(rd.os, "replace", failing_replace)
    run_dir, status = run(tmp_path, net, clock)
    assert status["stopReason"] == "local-io-error:OSError" and len(net.calls) == 2
    assert status["incompleteBodies"] == ["attempt-000002.part"]


def test_the_recorded_transport_never_downloads(tmp_path):
    recorder = rd.Recorder(tmp_path / "capture", attempt_budget=5, min_interval=0, soft_deadline=100, attempt_read_seconds=10,
                           body_limit=100, fetch=lambda u, h: pytest.fail("no fetch"), sleep=lambda s: None,
                           monotonic=lambda: 0.0, utc=lambda: UTC)
    transport = rd.RecordedTransport(recorder, commons.ALLOWED_HOSTS, "MAVI-test/1.0")
    with pytest.raises(rd.RunStopped):
        transport.download("https://upload.wikimedia.org/wikipedia/commons/a/ab/x.webm", tmp_path / "x.webm", 1, "0" * 40)
    assert recorder.stop_reason == "refused-download" and not (tmp_path / "x.webm").exists()


def test_the_hard_stop_records_an_event_then_exits_124(tmp_path):
    recorder = rd.Recorder(tmp_path / "capture", attempt_budget=5, min_interval=0, soft_deadline=100, attempt_read_seconds=10,
                           body_limit=100, fetch=None, sleep=lambda s: None, monotonic=lambda: 0.0, utc=lambda: UTC)
    codes = []
    rd.make_hard_stop(recorder, codes.append)()
    recorder.events.close()
    assert codes == [124]
    assert json.loads((tmp_path / "capture" / "events.jsonl").read_bytes().splitlines()[-1])["event"] == "hard-deadline"


def test_finalize_after_a_crash_reports_interruption_and_unreadable_lines(tmp_path):
    clock = Clock()
    net = Net(clock=clock, list_route=lambda url: (200, {}, Chunks([b"{"], raise_after=KeyboardInterrupt())))
    run_dir, _status = run(tmp_path, net, clock)
    (run_dir / "run-status.json").unlink()  # as if finalize itself had crashed before writing
    status = rd.finalize(run_dir)
    assert status["status"] == "INTERRUPTED" and status["interruptedScopes"] == ["P1"]
    assert [s["status"] for s in status["scopes"]] == ["INTERRUPTED", "NO_RECORD", "NO_RECORD"]
    (run_dir / "run-status.json").unlink()
    with open(run_dir / "capture" / "events.jsonl", "ab") as handle:
        handle.write(b'{"event": "attempt-st')
    assert rd.finalize(run_dir)["unreadableLines"] == 1


def test_a_tampered_bundle_fails_verification(tmp_path):
    clock = Clock()
    run_dir, _status = run(tmp_path, Net(clock=clock), clock)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    destination = rd.bundle(run_dir, evidence, "retry-tamper")
    rd.verify_bundle(destination, "retry-tamper")
    archive = destination / "retry-tamper.tar.gz"
    with tarfile.open(archive) as tar:
        members = [(m, tar.extractfile(m).read()) for m in tar.getmembers() if m.isfile()]
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(tampered, "w:gz") as out:
        for member, data in members:
            if member.name.endswith("run-config.json"):
                data = data.replace(b"traffic", b"TRAFFIC")
                member.size = len(data)
            out.addfile(member, io.BytesIO(data))
    archive.write_bytes(tampered.read_bytes())
    with pytest.raises(StoreError):
        rd.verify_bundle(destination, "retry-tamper", require_checksum=False)
    with pytest.raises(StoreError):
        rd.verify_bundle(destination, "retry-tamper")


def test_a_malformed_redirect_location_or_port_latches_before_the_next_title(tmp_path):
    for name, location in (("bracket", "https://[commons/x"),
                           ("port", "https://commons.wikimedia.org:99999/w/api.php?action=query")):
        clock = Clock()
        net = Net(clock=clock, meta_route=lambda title, loc=location: (302, {"Location": loc}, io.BytesIO(b"")))
        run_dir, status = run(tmp_path / name, net, clock)
        assert len(net.calls) == 3, name  # the second title never starts
        assert status["stopReason"].startswith("transport-refused:ValueError"), (name, status["stopReason"])


def _synthetic_run(tmp_path: Path, name: str, events_lines: list[str], scope_lines: list[str] = ()) -> Path:
    run_dir = tmp_path / name
    (run_dir / "capture" / "bodies").mkdir(parents=True)
    (run_dir / "capture" / "events.jsonl").write_bytes(("\n".join(events_lines) + "\n").encode())
    (run_dir / "capture" / "scopes.jsonl").write_bytes(("\n".join(scope_lines) + "\n").encode() if scope_lines else b"")
    return run_dir


START = '{"event": "run-start", "utc": "x"}'
END = '{"event": "run-end", "utc": "x"}'


def test_finalize_marks_each_interruption_signal_on_its_own(tmp_path):
    assert rd.finalize(_synthetic_run(tmp_path, "control", [START, END]))["status"] == "COMPLETE"
    cases = {
        "unfinished-attempt": ([START, '{"event": "attempt-start", "attempt": 1, "utc": "x"}', END], []),
        "interrupted-scope": ([START, END], ['{"event": "scope-start", "scope": "P1", "utc": "x"}']),
        "unreadable-line": ([START, '{"event": "attem', END], []),
        "latched-interrupt": ([START, '{"event": "latched", "reason": "interrupted", "utc": "x"}', END], []),
        "no-run-end": ([START], []),
    }
    for name, (event_lines, scope_lines) in cases.items():
        assert rd.finalize(_synthetic_run(tmp_path, name, event_lines, scope_lines))["status"] == "INTERRUPTED", name
    stopped = _synthetic_run(tmp_path, "stopped", [START, '{"event": "latched", "reason": "http-429", "utc": "x"}', END])
    assert rd.finalize(stopped)["status"] == "STOPPED"


def _rewrite_archive(destination: Path, name: str, transform) -> None:
    archive = destination / f"{name}.tar.gz"
    with tarfile.open(archive) as tar:
        members = [(m, tar.extractfile(m).read()) for m in tar.getmembers() if m.isfile()]
    rebuilt = destination.parent / f"{name}-rebuilt.tar.gz"
    with tarfile.open(rebuilt, "w:gz") as out:
        for member, data in transform(members):
            member.size = len(data)
            out.addfile(member, io.BytesIO(data))
    archive.write_bytes(rebuilt.read_bytes())


def test_verify_bundle_isolates_checksum_member_set_and_prefix_checks(tmp_path):
    clock = Clock()
    run_dir, _status = run(tmp_path, Net(clock=clock), clock)
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    def fresh(label: str) -> Path:
        return rd.bundle(run_dir, evidence, label)

    # checksum only: the archive is intact, the recorded checksum is wrong.
    one = fresh("b-checksum")
    rd.verify_bundle(one, "b-checksum")
    (one / "b-checksum.tar.gz.sha256").write_text("0" * 64 + "  b-checksum.tar.gz\n", encoding="ascii")
    with pytest.raises(StoreError, match="archive SHA-256"):
        rd.verify_bundle(one, "b-checksum")
    rd.verify_bundle(one, "b-checksum", require_checksum=False)

    # member set only: an extra file inside the prefix, every listed member intact.
    two = fresh("b-extra")
    _rewrite_archive(two, "b-extra", lambda ms: ms + [(tarfile.TarInfo("b-extra/extra.txt"), b"extra")])
    with pytest.raises(StoreError, match="member set"):
        rd.verify_bundle(two, "b-extra", require_checksum=False)

    # prefix only: a member under another top-level name of the same length, same suffix and bytes.
    three = fresh("b-prefix")

    def reprefix(ms):
        out = []
        for member, data in ms:
            if member.name.endswith("config/run-config.json"):
                member.name = "X-prefix/config/run-config.json"
            out.append((member, data))
        return out

    _rewrite_archive(three, "b-prefix", reprefix)
    with pytest.raises(StoreError, match="unexpected member"):
        rd.verify_bundle(three, "b-prefix", require_checksum=False)


def test_limits_require_the_soft_deadline_before_the_hard_deadline():
    with pytest.raises(StoreError):
        rd.build_config(CONTACT, limits={**rd.LIMITS, "softDeadlineSeconds": 45 * 60})


def test_the_candidate_cap_is_enforced_inside_a_scope(tmp_path):
    clock = Clock()
    net = Net(clock=clock)
    run_dir, status = run(tmp_path, net, clock, candidateCap=1)
    assert len(net.calls) == 3 and not any("Crossing+B" in u for u in net.calls)  # only the allowance is requested
    p1 = scope_records(run_dir)["P1"]
    assert p1["requestedTitles"] == [TITLES[0]] and p1["overCandidateCapTitles"] == [TITLES[1]]
    assert p1["uniqueDescribedSoFar"] == 1 and status["describedWithoutError"] == 1
    assert scope_records(run_dir)["P4"]["reason"] == "candidate-cap" and status["status"] == "COMPLETE"


def test_the_hard_stop_exits_even_if_logging_fails_or_blocks(tmp_path):
    import threading as _threading

    recorder = rd.Recorder(tmp_path / "capture", attempt_budget=5, min_interval=0, soft_deadline=100, attempt_read_seconds=10,
                           body_limit=100, fetch=None, sleep=lambda s: None, monotonic=lambda: 0.0, utc=lambda: UTC)

    def failing_write(*_a, **_k):
        raise OSError("disk gone")

    codes = []
    recorder.events.write = failing_write
    rd.make_hard_stop(recorder, codes.append, log_timeout=1.0)()
    assert codes == [124]

    release = _threading.Event()

    def blocking_write(*_a, **_k):
        release.wait(30)

    recorder.events.write = blocking_write
    codes.clear()
    started = time.monotonic()
    rd.make_hard_stop(recorder, codes.append, log_timeout=0.2)()
    assert codes == [124] and time.monotonic() - started < 2.0  # the exit did not wait for the blocked write
    release.set()


def test_the_hard_stop_exits_even_if_the_logging_thread_cannot_start(tmp_path, monkeypatch):
    recorder = rd.Recorder(tmp_path / "capture", attempt_budget=5, min_interval=0, soft_deadline=100, attempt_read_seconds=10,
                           body_limit=100, fetch=None, sleep=lambda s: None, monotonic=lambda: 0.0, utc=lambda: UTC)

    class NoThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(rd.threading, "Thread", NoThread)
    codes = []
    with pytest.raises(RuntimeError):
        rd.make_hard_stop(recorder, codes.append)()
    assert codes == [124]


def test_an_atomic_write_survives_a_failed_partial_cleanup(tmp_path, monkeypatch):
    real_unlink = Path.unlink

    def stubborn_unlink(self, *a, **k):
        if self.name.endswith(".partial") and self.with_name(self.name[:-len(".partial")]).exists():
            raise PermissionError("held by another process")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", stubborn_unlink)
    target = tmp_path / "record.json"
    rd._write_new(target, b"{}\n")
    assert target.read_bytes() == b"{}\n" and (tmp_path / "record.json.partial").exists()
    monkeypatch.setattr(Path, "unlink", real_unlink)
    with pytest.raises(FileExistsError):
        rd._write_new(target, b"{other}\n")  # never overwrites; the stale partial is replaced, then refused
    assert target.read_bytes() == b"{}\n"


def test_verify_bundle_rejects_duplicate_archive_members_and_manifest_paths(tmp_path):
    clock = Clock()
    run_dir, _status = run(tmp_path, Net(clock=clock), clock)
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    one = rd.bundle(run_dir, evidence, "b-dup")

    def duplicate(ms):
        out = list(ms)
        for member, data in ms:
            if member.name.endswith("config/run-config.json"):
                copy = tarfile.TarInfo(member.name)
                out.append((copy, data.replace(b"traffic", b"TRAFFIC")))  # a conflicting second copy
        return out

    _rewrite_archive(one, "b-dup", duplicate)
    with pytest.raises(StoreError, match="duplicate archive member"):
        rd.verify_bundle(one, "b-dup", require_checksum=False)

    two = rd.bundle(run_dir, evidence, "b-dup-manifest")
    manifest = json.loads((two / "MANIFEST.json").read_bytes())
    manifest["files"].append(dict(manifest["files"][0]))
    (two / "MANIFEST.json").write_bytes(json.dumps(manifest).encode())
    with pytest.raises(StoreError, match="duplicate manifest path"):
        rd.verify_bundle(two, "b-dup-manifest", require_checksum=False)


# ---------------------------------------------------------------- P2 completion pass

NEW = ["File:Lane C 2026.webm", "File:Lane D 2026.webm", "File:Lane E 2026.webm"]


def _search_route(pages: dict[int, tuple[list[tuple[str, int]], bool]], seen: list[int]):
    """Serve search pages by sroffset: {offset: ([(title, pageid)], has_continuation)}."""
    def route(url):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        offset = int(params.get("sroffset", "0"))
        seen.append(offset)
        rows, more = pages[offset]
        body = {"query": {"searchinfo": {"totalhits": 90}, "search": [{"title": t, "pageid": p} for t, p in rows]}}
        if more:
            body["continue"] = {"sroffset": offset + 20, "continue": "-||"}
        return 200, {}, io.BytesIO(json.dumps(body).encode())
    return route


def _prior_bundle(tmp_path: Path) -> tuple[Path, str]:
    clock = Clock()
    run_dir, _ = run(tmp_path / "prior", Net(clock=clock), clock, scopes=SCOPES[:1])
    evidence = tmp_path / "evidence"
    evidence.mkdir(exist_ok=True)
    return rd.bundle(run_dir, evidence, "prior-run"), "prior-run"


def _completion(tmp_path: Path, net: Net, clock: Clock, prior: dict, **limits):
    root = tmp_path / "completion-root"
    root.mkdir(parents=True, exist_ok=True)
    return rd.run_discovery(root, CONTACT, stamp=STAMP, scopes=rd.P2_COMPLETION_SCOPES,
                            limits={**rd.P2_COMPLETION_LIMITS, **limits}, fetch=net, sleep=clock.sleep,
                            monotonic=clock.monotonic, utc=lambda: UTC, hard_deadline=False,
                            pass_id=rd.P2_COMPLETION_PASS_ID, prior_runs=[prior], run_prefix="commons-discovery-completion")


def test_the_p2_completion_pass_is_predeclared_exactly():
    assert [(s["id"], s["kind"], s["query"], s["pool"], s["offset"]) for s in rd.P2_COMPLETION_SCOPES] == [
        ("P2-o0", "search", "street India 2026", "primary", 0), ("P2-o20", "search", "street India 2026", "primary", 20),
        ("P2-o40", "search", "street India 2026", "primary", 40), ("P2-o60", "search", "street India 2026", "primary", 60)]
    limits = rd.P2_COMPLETION_LIMITS
    worst_case_logical = 1 + len(rd.P2_COMPLETION_SCOPES) + limits["candidateCap"]  # preflight + pages + new metadata
    assert (worst_case_logical, limits["attemptBudget"], limits["scopeLimit"], limits["candidateCap"]) == (25, 30, 20, 20)
    assert limits["softDeadlineSeconds"] < limits["hardDeadlineSeconds"]
    assert limits == {"scopeLimit": 20, "secondaryOnlyIfPrimaryDescribedBelow": 1, "candidateCap": 20, "attemptBudget": 30,
                      "minIntervalSeconds": 5, "scopeGapSeconds": 15, "softDeadlineSeconds": 600, "hardDeadlineSeconds": 720,
                      "attemptReadSeconds": 120, "bodyLimitBytes": 16 * 1024 * 1024}
    assert rd.P2_COMPLETION_PRIOR == {
        "bundleName": "2026-10-01-source-pilot-retry-20261001T161421Z",
        "archiveSha256": "710486a2300ce1282acc447e422f423379fa354727d271c1dca84ef7d8b24ccc",
        "manifestSha256": "dd9a6e41cdc406fa4ae73d8ca977305c443ec07cb405e7c6484607a3aeb8f11f",
        "configSha256": "e6a4820bd7a09b1a19bf2b5a8370d7ca5c078b6a60eac65f5bd24400b403a7e6"}


def test_scope_validation_freezes_offsets_and_page_order():
    page = {"id": "P", "kind": "search", "query": "q", "pool": "primary"}
    for scopes in ([dict(page, offset=10)],                                              # not a page boundary
                   [dict(page, id="a", offset=20), dict(page, id="b", offset=0)],        # descending pages
                   [dict(page, kind="category", query="Category:X", offset=0)],          # no offsets on categories
                   [dict(page, offset=True)], [dict(page, extra=1)], [page, dict(page)],   # bool, unknown key, duplicate id
                   [dict(page, offset=False)],                                            # False is not offset 0
                   [dict(page, id="a", offset=20), dict(page, id="b", offset=20)],        # the same page twice
                   [dict(page, id="a"), dict(page, id="b", offset=0)]):                   # no offset is page 1
        with pytest.raises(StoreError):
            rd.build_config(CONTACT, scopes, rd.P2_COMPLETION_LIMITS)


def test_completion_pages_use_frozen_offsets_and_stop_when_the_search_is_exhausted(tmp_path):
    destination, name = _prior_bundle(tmp_path)
    prior = rd.prior_run_identities(destination, name)
    clock, seen = Clock(), []
    pages = {0: ([(TITLES[0], 100), (TITLES[1], 101), (NEW[0], 300)], True), 20: ([(NEW[1], 301)], False)}
    net = Net(titles=TITLES + NEW, clock=clock, list_route=_search_route(pages, seen))
    run_dir, status = _completion(tmp_path, net, clock, prior)
    list_urls = [u for u in net.calls if "list=search" in u]
    assert seen == [0, 20] and "sroffset" not in list_urls[0] and list_urls[1].endswith("&sroffset=20")
    scopes = scope_records(run_dir)
    assert scopes["P2-o0"]["priorRunTitles"] == TITLES and scopes["P2-o0"]["requestedTitles"] == [NEW[0]]
    assert scopes["P2-o20"]["serverContinuation"] is None and scopes["P2-o40"]["status"] == "NOT_NEEDED"
    assert scopes["P2-o60"]["status"] == "NOT_NEEDED" and status["status"] == "COMPLETE"
    assert not any(t.replace(" ", "+") in u for t in TITLES for u in net.calls if "titles=" in u)  # prior files never re-described
    assert status["describedWithoutError"] == 2
    config = json.loads((run_dir / "config" / "run-config.json").read_bytes())
    assert config["passId"] == rd.P2_COMPLETION_PASS_ID and config["priorRuns"][0]["archiveSha256"] == prior["archiveSha256"]
    assert [i["title"] for i in config["priorRuns"][0]["describedIdentities"]] == TITLES


def test_a_renamed_prior_file_is_excluded_by_page_id_and_drift_duplicates_count_once(tmp_path):
    destination, name = _prior_bundle(tmp_path)
    prior = rd.prior_run_identities(destination, name)
    clock, seen = Clock(), []
    renamed = "File:Crossing A renamed 2026.webm"  # same page id 100 as a prior file
    pages = {0: ([(renamed, 100), (NEW[0], 300)], True), 20: ([(NEW[0], 300), (NEW[1], 301)], True),
             40: ([(NEW[2], 302)], False)}
    net = Net(titles=TITLES + NEW + [renamed], clock=clock, list_route=_search_route(pages, seen))
    run_dir, status = _completion(tmp_path, net, clock, prior)
    scopes = scope_records(run_dir)
    assert scopes["P2-o0"]["priorRunTitles"] == [renamed] and scopes["P2-o0"]["requestedTitles"] == [NEW[0]]
    assert scopes["P2-o20"]["alreadyDescribedTitles"] == [NEW[0]] and scopes["P2-o20"]["requestedTitles"] == [NEW[1]]
    assert status["describedWithoutError"] == 3 and len([u for u in net.calls if "titles=" in u]) == 3


def test_the_new_candidate_cap_stops_paging(tmp_path):
    destination, name = _prior_bundle(tmp_path)
    prior = rd.prior_run_identities(destination, name)
    clock, seen = Clock(), []
    pages = {0: ([(NEW[0], 300), (NEW[1], 301), (NEW[2], 302)], True), 20: ([("File:Never 2026.webm", 400)], True)}
    net = Net(titles=NEW + ["File:Never 2026.webm"], clock=clock, list_route=_search_route(pages, seen))
    run_dir, status = _completion(tmp_path, net, clock, prior, candidateCap=2)
    scopes = scope_records(run_dir)
    assert seen == [0] and scopes["P2-o0"]["overCandidateCapTitles"] == [NEW[2]]
    assert {scopes[s]["reason"] for s in ("P2-o20", "P2-o40", "P2-o60")} == {"candidate-cap"} and status["describedWithoutError"] == 2


def test_a_tampered_prior_bundle_is_refused_before_any_request(tmp_path):
    destination, name = _prior_bundle(tmp_path)
    (destination / f"{name}.tar.gz.sha256").write_text("0" * 64 + f"  {name}.tar.gz\n", encoding="ascii")
    with pytest.raises(StoreError):
        rd.prior_run_identities(destination, name)
    root = tmp_path / "cli-root"
    root.mkdir()
    code = rd.main(["run-completion", "--run-root", str(root), "--contact", CONTACT,
                    "--prior-evidence-dir", str(destination), "--prior-name", name])
    assert code == 2 and list(root.iterdir()) == []  # refused before a run directory or any request exists


def test_a_prior_title_without_a_page_id_is_still_excluded(tmp_path):
    destination, name = _prior_bundle(tmp_path)
    prior = rd.prior_run_identities(destination, name)
    clock, seen = Clock(), []
    pages = {0: ([(TITLES[0], None), (NEW[0], 300)], False)}
    net = Net(titles=TITLES + NEW, clock=clock, list_route=_search_route(pages, seen))
    run_dir, status = _completion(tmp_path, net, clock, prior)
    assert scope_records(run_dir)["P2-o0"]["priorRunTitles"] == [TITLES[0]]
    assert len([u for u in net.calls if "titles=" in u]) == 1 and status["describedWithoutError"] == 1


def _cli_completion(tmp_path: Path, destination: Path, name: str, net: Net, clock: Clock, pinned: dict) -> tuple[int, Path]:
    root = tmp_path / "cli-run-root"
    root.mkdir(exist_ok=True)
    code = rd.main(["run-completion", "--run-root", str(root), "--contact", CONTACT,
                    "--prior-evidence-dir", str(destination), "--prior-name", name],
                   fetch=net, sleep=clock.sleep, monotonic=clock.monotonic, hard_deadline=False, pinned_prior=pinned)
    return code, root


def test_the_run_completion_command_runs_exactly_the_predeclared_pass(tmp_path):
    destination, name = _prior_bundle(tmp_path)
    prior = rd.prior_run_identities(destination, name)
    pinned = {k: prior[k] for k in ("bundleName", "archiveSha256", "manifestSha256", "configSha256")}
    clock, seen = Clock(), []
    net = Net(titles=TITLES + NEW, clock=clock, list_route=_search_route({0: ([(NEW[0], 300)], False)}, seen))
    code, root = _cli_completion(tmp_path, destination, name, net, clock, pinned)
    run_dir = next(root.iterdir())
    config = json.loads((run_dir / "config" / "run-config.json").read_bytes())
    assert code == 0 and run_dir.name.startswith("commons-discovery-completion-")
    assert config["limits"] == rd.P2_COMPLETION_LIMITS and config["scopes"] == [dict(s) for s in rd.P2_COMPLETION_SCOPES]
    assert config["passId"] == rd.P2_COMPLETION_PASS_ID and config["priorRuns"] == [prior]
    assert prior["manifestSha256"] == hashlib.sha256((destination / "MANIFEST.json").read_bytes()).hexdigest()
    assert prior["configSha256"] == hashlib.sha256((tmp_path / "prior" / "acquisition" / f"commons-discovery-retry-{STAMP}"
                                                    / "config" / "run-config.json").read_bytes()).hexdigest()


def test_run_completion_refuses_any_prior_bundle_but_the_pinned_one_before_any_request(tmp_path):
    destination, name = _prior_bundle(tmp_path)  # verifies, but is not the pinned retry bundle
    clock = Clock()
    net = Net(clock=clock)
    code, root = _cli_completion(tmp_path, destination, name, net, clock, rd.P2_COMPLETION_PRIOR)
    assert code == 2 and list(root.iterdir()) == [] and net.calls == []


def test_prior_files_never_reduce_the_new_file_allowance(tmp_path):
    destination, name = _prior_bundle(tmp_path)
    prior = rd.prior_run_identities(destination, name)
    clock, seen = Clock(), []
    pages = {0: ([(TITLES[0], 100), (TITLES[1], 101), (NEW[0], 300), (NEW[1], 301)], True), 20: ([(NEW[2], 302)], False)}
    net = Net(titles=TITLES + NEW, clock=clock, list_route=_search_route(pages, seen))
    run_dir, _status = _completion(tmp_path, net, clock, prior, candidateCap=2)
    p0 = scope_records(run_dir)["P2-o0"]
    assert p0["requestedTitles"] == [NEW[0], NEW[1]] and p0["overCandidateCapTitles"] == []
    assert p0["priorRunMatches"] == [{"title": TITLES[0], "byTitle": True, "byPageId": True},
                                     {"title": TITLES[1], "byTitle": True, "byPageId": True}]


def test_an_empty_continuation_ends_paging_and_is_recorded_consistently(tmp_path):
    destination, name = _prior_bundle(tmp_path)
    prior = rd.prior_run_identities(destination, name)
    clock = Clock()

    def route(url):
        return ok({"query": {"searchinfo": {"totalhits": 1}, "search": [{"title": NEW[0], "pageid": 300}]}, "continue": {}})

    run_dir, _status = _completion(tmp_path, Net(titles=NEW, clock=clock, list_route=route), clock, prior)
    scopes = scope_records(run_dir)
    assert scopes["P2-o0"]["listContinues"] is False and scopes["P2-o0"]["serverContinuation"] is None
    assert scopes["P2-o20"]["status"] == "NOT_NEEDED"


def test_a_prior_bundle_without_described_files_is_refused(tmp_path):
    clock = Clock()
    empty = Net(clock=clock, list_route=lambda url: ok({"query": {"search": []}}))
    run_dir, _ = run(tmp_path / "prior", empty, clock, scopes=SCOPES[:1])
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    destination = rd.bundle(run_dir, evidence, "empty-prior")
    with pytest.raises(StoreError, match="no described files"):
        rd.prior_run_identities(destination, "empty-prior")


def test_an_unknown_run_prefix_is_refused_before_any_directory_exists(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(StoreError):
        rd.run_discovery(root, CONTACT, stamp=STAMP, fetch=Net(), hard_deadline=False, run_prefix="commons-crawl")
    assert list(root.iterdir()) == []
