"""Recorded, metadata-only Commons discovery for the S2c B0 pilot retry (Development only).

This wraps the existing helper without changing it. The helper's ``Transport`` is built
with an injected recording ``fetch`` and ``sleep``, and ``acquire.discover`` runs
unchanged, so host allow-listing, redirect re-validation, credential refusal, metadata
hashing, admission rules and store containment all remain the helper's own. The
recorder adds:

* **discovery only**: every network attempt must be a GET of the Commons Action API
  endpoint. ``upload.wikimedia.org`` (media) and every other URL are refused before a
  socket opens, so this module can never fetch footage;
* **a global stop latch**: the first refusal, non-success HTTP status (including 429/503),
  API ``error`` body, network failure, incomplete or over-limit body, exhausted attempt
  budget, deadline or interruption latches the run. Once it has latched, no further
  network attempt starts: not a remaining metadata request, not a redirect hop, not the
  helper's own back-off retry. Local finalisation continues;
* **durable capture**: an ``attempt-start`` event is fsynced before every attempt and an
  ``attempt-end`` event after it. A start without an end identifies an attempt that a
  hard stop interrupted. Bodies stream to ``bodies/attempt-NNNNNN.part`` and are renamed
  ``.body`` only when read completely, so a partial body is never presented as complete;
* **enforceable limits**: an actual-attempt budget (every fetch, including each redirect
  hop), a minimum interval between attempt starts, a soft deadline checked before every
  attempt, read chunk and sleep, a per-attempt read limit and an optional hard deadline
  that records an event and ends the process.

The User-Agent, including its contact, is written to the run configuration (controlled
run evidence). The helper's receipts and discovery records still never contain it.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tarfile
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from attributes.corpus.canonical import canonical_json, sha256_hex

from . import commons
from .acquire import StoreError, assert_controlled_store, discover
from .cli import USER_AGENT
from .transport import Transport, TransportError, _default_fetch

CONFIG_SCHEMA = "mavi-s2c-recorded-discovery-config-v1"
STATUS_SCHEMA = "mavi-s2c-recorded-discovery-status-v1"
MANIFEST_SCHEMA = "mavi-s2c-recorded-discovery-manifest-v1"

# The original predeclared scopes (B0 record section 6; 2026-10-01 run note), verbatim and in order.
PILOT_RETRY_SCOPES = (
    {"id": "P1", "kind": "search", "query": "traffic India 2026", "pool": "primary"},
    {"id": "P2", "kind": "search", "query": "street India 2026", "pool": "primary"},
    {"id": "P3", "kind": "search", "query": "pedestrians market India", "pool": "primary"},
    {"id": "P4", "kind": "category", "query": "Category:Videos of streets in India", "pool": "primary"},
    {"id": "P5", "kind": "category", "query": "Category:Videos of road traffic in India", "pool": "primary"},
    {"id": "S1", "kind": "category", "query": "Category:Videos of street scenes", "pool": "secondary"},
    {"id": "S2", "kind": "category", "query": "Category:Videos of road traffic", "pool": "secondary"},
)
CATEGORY_CAVEAT = (
    "Direct-category query: lists only files directly in the category (cmtype=file, at most the "
    "limit, in category sort order). Subcategory members are excluded. An empty or short result "
    "does not establish that the category or its subcategories contain no relevant footage."
)
PREFLIGHT_URL = commons.API + "?" + urllib.parse.urlencode(
    {"action": "query", "format": "json", "formatversion": "2", "maxlag": "5", "meta": "siteinfo", "siprop": "general"})

LIMITS = {
    "scopeLimit": 20,
    "secondaryOnlyIfPrimaryDescribedBelow": 40,
    "candidateCap": 60,
    "attemptBudget": 160,
    "minIntervalSeconds": 5,
    "scopeGapSeconds": 60,
    "softDeadlineSeconds": 40 * 60,
    "hardDeadlineSeconds": 45 * 60,
    "attemptReadSeconds": 120,
    "bodyLimitBytes": 16 * 1024 * 1024,
}
STOP_RULES = (
    "a refused URL (anything but the Commons Action API endpoint) latches the run before any socket opens",
    "a refusal raised inside the helper's Transport (redirect to a host that is not allow-listed, a non-HTTPS hop, a redirect without a location, too many redirects, an over-limit body) latches the run before any further request",
    "a local capture failure (writing or renaming a captured body) latches the run",
    "any HTTP status other than 200 or a redirect, including 429 and 503, latches the run; the helper's back-off sleep is refused, so it never retries",
    "an API body with an 'error' member latches the run",
    "a network failure, read failure, read-limit overrun or over-limit body latches the run",
    "the attempt budget counts every fetch, including each redirect hop; reaching it latches the run",
    "the soft deadline is checked before every attempt, every read chunk, every pacing wait and every sleep; passing it latches the run",
    "the hard deadline records an event and ends the process; everything already captured survives",
    "a per-file metadata error that the helper records as an item error latches the run after that scope",
    "an interruption latches the run and finalises locally",
    "after the latch, no network attempt starts; remaining scopes are recorded NOT_STARTED",
    "secondary scopes run only if primary scopes described fewer files without error than the threshold",
    "no scope starts once the candidate cap of files described without error is reached",
)
RECORDED_HEADER_NAMES = ("retry-after", "date", "content-type", "content-length", "age", "server", "x-cache", "x-cache-status",
                         "location")
RECORDED_HEADER_PREFIXES = ("x-ratelimit-", "ratelimit")
REDIRECTS = (301, 302, 303, 307, 308)
CHUNK = 64 * 1024


class RunStopped(TransportError):
    """The run has latched; the helper treats it like any other transport refusal."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _seconds(value: float) -> str:
    return f"{value:.3f}"


def is_discovery_url(url: str) -> bool:
    """Only an HTTPS GET of the Commons Action API endpoint itself, with exactly one
    ``action=query`` and no array-style or encoded parameter keys, is a discovery request."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if not (parts.scheme == "https" and parts.netloc in ("commons.wikimedia.org", "commons.wikimedia.org:443")
            and port in (None, 443) and parts.path == "/w/api.php" and not parts.fragment):
        return False
    if "%" in "".join(segment.split("=", 1)[0] for segment in parts.query.split("&")):
        return False  # an encoded key (e.g. %61ction) could smuggle a second action past the check
    try:
        pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    keys = [key for key, _ in pairs]
    if any("[" in key or "]" in key for key in keys) or len(keys) != len(set(keys)):
        return False
    return dict(pairs).get("action") == "query"


def _request_kind(url: str) -> dict:
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    if "titles" in params:
        return {"kind": "file-metadata", "title": params["titles"]}
    if params.get("list") in ("search", "categorymembers"):
        return {"kind": "list", "title": None}
    if params.get("meta") == "siteinfo":
        return {"kind": "preflight", "title": None}
    return {"kind": "other", "title": None}


def _selected_headers(headers: dict) -> dict:
    selected = {}
    for name, value in (headers or {}).items():
        key = str(name).lower()
        if key in RECORDED_HEADER_NAMES or key.startswith(RECORDED_HEADER_PREFIXES):
            selected[key] = str(value)
    return dict(sorted(selected.items()))


class EventLog:
    """Append-only JSON lines; every event is flushed and fsynced before the call returns."""

    def __init__(self, path: Path, utc: Callable[[], str]):
        self.path = path
        self._utc = utc
        self._lock = threading.Lock()
        self._handle = open(path, "xb")

    def write(self, event: str, **fields) -> None:
        record = {"event": event, "utc": self._utc(), **fields}
        line = (json.dumps(record, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
        with self._lock:
            if self._handle.closed:
                return
            self._handle.write(line)
            self._handle.flush()
            os.fsync(self._handle.fileno())

    def close(self) -> None:
        with self._lock:
            if not self._handle.closed:
                self._handle.close()


class Recorder:
    """Recording ``fetch``/``sleep`` for the helper's ``Transport``, with the global stop latch."""

    def __init__(self, capture: Path, *, attempt_budget: int, min_interval: float, soft_deadline: float,
                 attempt_read_seconds: float, body_limit: int,
                 fetch: Callable | None = None, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic, utc: Callable[[], str] = _utc_now):
        self.capture = capture
        self.bodies = capture / "bodies"
        self.bodies.mkdir(parents=True, exist_ok=False)
        self.events = EventLog(capture / "events.jsonl", utc)
        self._fetch = fetch or _default_fetch
        self._sleep = sleep
        self._monotonic = monotonic
        self.attempt_budget = attempt_budget
        self.min_interval = min_interval
        self.attempt_read_seconds = attempt_read_seconds
        self.body_limit = body_limit
        self.started = monotonic()
        self.deadline = self.started + soft_deadline
        self.attempts = 0
        self.stop_reason: str | None = None
        self.last_list_attempt: int | None = None
        self._last_start: float | None = None

    # -- latch -------------------------------------------------------------------------
    def latch(self, reason: str) -> None:
        if self.stop_reason is None:
            self.stop_reason = reason
            self.events.write("latched", reason=reason, attempts=self.attempts)

    def guard(self) -> None:
        if self.stop_reason is not None:
            raise RunStopped(f"run stopped: {self.stop_reason}")

    def _check_deadline(self, ahead: float = 0.0) -> None:
        if self._monotonic() + ahead > self.deadline:
            self.latch("soft-deadline")
            self.guard()

    # -- hooks injected into Transport ---------------------------------------------------
    def fetch(self, url: str, headers: dict):
        self.guard()
        if not is_discovery_url(url):
            self.events.write("refused-url", url=url)
            self.latch(f"refused-url:{urllib.parse.urlsplit(url).hostname}")
            self.guard()
        if self.attempts >= self.attempt_budget:
            self.latch("attempt-budget-exhausted")
            self.guard()
        if self._last_start is not None:
            wait = self._last_start + self.min_interval - self._monotonic()
            if wait > 0:
                self._check_deadline(wait)
                self._sleep(wait)
        self._check_deadline()
        self.attempts += 1
        attempt = self.attempts
        self._last_start = self._monotonic()
        kind = _request_kind(url)
        if kind["kind"] == "list":
            self.last_list_attempt = attempt
        self.events.write("attempt-start", attempt=attempt, url=url, **kind)
        part = self.bodies / f"attempt-{attempt:06d}.part"
        state = {"bytes": 0, "sha256": hashlib.sha256()}
        try:
            status, response_headers, stream = self._fetch(url, headers)
        except KeyboardInterrupt:
            self._end(attempt, outcome="interrupted", status=None, headers={}, state=state, complete=False)
            self.latch("interrupted")
            raise
        except Exception as exc:  # noqa: BLE001 - every network failure is recorded, latched and refused
            self._end(attempt, outcome=f"network-error:{type(exc).__name__}", status=None, headers={}, state=state,
                      complete=False, error=str(exc)[:500])
            self.latch(f"network-failure:{type(exc).__name__}")
            raise RunStopped(f"network failure: {type(exc).__name__}") from exc
        selected = _selected_headers(response_headers)
        try:
            body, complete, outcome = self._read(stream, part, state)
            if complete:
                os.replace(part, self.bodies / f"attempt-{attempt:06d}.body")
        except KeyboardInterrupt:
            self._end(attempt, outcome="interrupted", status=status, headers=selected, state=state, complete=False)
            self.latch("interrupted")
            raise
        except OSError as exc:  # a local capture failure: nothing more may be fetched without capture
            self._end(attempt, outcome=f"local-io-error:{type(exc).__name__}", status=status, headers=selected, state=state,
                      complete=False, error=str(exc)[:500])
            self.latch(f"local-io-error:{type(exc).__name__}")
            raise RunStopped(f"local capture failure: {type(exc).__name__}") from exc
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:  # noqa: BLE001 - closing a failed stream must not hide the outcome
                    pass
        api_error = None
        warnings = False
        if complete:
            if status == 200:
                try:
                    document = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    document = None
                if isinstance(document, dict):
                    if "error" in document:
                        error = document.get("error")
                        api_error = str(error.get("code") if isinstance(error, dict) else error)[:120]
                    warnings = "warnings" in document
        self._end(attempt, outcome=outcome, status=status, headers=selected, state=state, complete=complete,
                  apiError=api_error, apiWarnings=warnings)
        if not complete:
            self.latch(outcome)
            self.guard()
        if status in REDIRECTS:
            return status, response_headers, io.BytesIO(body)
        if status != 200:
            self.latch(f"http-{status}")
        elif api_error is not None:
            self.latch(f"api-error:{api_error}")
        return status, response_headers, io.BytesIO(body)

    def sleep(self, seconds: float) -> None:
        """The helper's back-off hook. Every back-off follows a latched 429/503, so it is refused."""
        self.guard()
        self._check_deadline(seconds)
        self.events.write("helper-sleep", seconds=_seconds(seconds))
        self._sleep(seconds)

    def pause(self, seconds: float) -> None:
        """Pacing between scopes: refused once latched or if it would pass the deadline."""
        self.guard()
        self._check_deadline(seconds)
        self.events.write("pause", seconds=_seconds(seconds))
        self._sleep(seconds)

    # -- internals -----------------------------------------------------------------------
    def _read(self, stream, part: Path, state: dict) -> tuple[bytes, bool, str]:
        chunks: list[bytes] = []
        started = self._monotonic()
        complete, outcome = False, "complete"
        with open(part, "xb") as out:
            try:
                while True:
                    now = self._monotonic()
                    if now > self.deadline:
                        outcome = "soft-deadline"
                        break
                    if now - started > self.attempt_read_seconds:
                        outcome = "read-time-limit"
                        break
                    try:
                        chunk = stream.read(min(CHUNK, self.body_limit + 1 - state["bytes"]))
                    except Exception as exc:  # noqa: BLE001 - a read failure keeps the partial body
                        outcome = f"read-error:{type(exc).__name__}"
                        break
                    if not chunk:
                        complete = True
                        break
                    out.write(chunk)
                    out.flush()
                    chunks.append(chunk)
                    state["bytes"] += len(chunk)
                    state["sha256"].update(chunk)
                    if state["bytes"] > self.body_limit:
                        outcome = "over-body-limit"
                        break
            finally:
                out.flush()
                os.fsync(out.fileno())
        return b"".join(chunks), complete, outcome

    def _end(self, attempt: int, *, outcome: str, status, headers: dict, state: dict, complete: bool, **extra) -> None:
        self.events.write("attempt-end", attempt=attempt, outcome=outcome, status=status, headers=headers,
                          bytes=state["bytes"], sha256=state["sha256"].hexdigest(), complete=complete,
                          elapsedSeconds=_seconds(self._monotonic() - self.started), **extra)


class RecordedTransport(Transport):
    """The helper's ``Transport``, unchanged, except that every refusal it raises latches the run.

    ``Transport.open`` refuses some things before or after calling ``fetch`` (a redirect to a
    host that is not allow-listed, a non-HTTPS hop, a redirect without a location, too many
    redirects), and ``get_bytes`` refuses an over-limit body. ``discover`` would otherwise
    catch those as per-item errors and continue with the next title. Here they latch first.
    ``download`` is refused outright: this transport is for discovery only.
    """

    def __init__(self, recorder: Recorder, allowed_hosts, user_agent: str):
        super().__init__(allowed_hosts, user_agent, fetch=recorder.fetch, sleep=recorder.sleep)
        self.recorder = recorder

    def _refused(self, exc: TransportError) -> RunStopped:
        if not isinstance(exc, RunStopped):
            self.recorder.events.write("transport-refused", error=str(exc)[:500])
            self.recorder.latch(f"transport-refused:{str(exc)[:160]}")
        return exc if isinstance(exc, RunStopped) else RunStopped(f"run stopped: {self.recorder.stop_reason}")

    def open(self, url: str):
        self.recorder.guard()
        try:
            return super().open(url)
        except TransportError as exc:
            raise self._refused(exc) from exc

    def get_bytes(self, url: str, limit: int = 16 * 1024 * 1024) -> bytes:
        self.recorder.guard()
        try:
            return super().get_bytes(url, limit)
        except TransportError as exc:
            raise self._refused(exc) from exc

    def download(self, url, target, expected_size, expected_sha1):  # noqa: D401 - signature of the helper
        self.recorder.latch("refused-download")
        raise RunStopped("recorded discovery never downloads media")


def _source_hashes() -> dict:
    package = Path(__file__).resolve().parent
    qualification = package.parent
    files = sorted(package.glob("*.py")) + [
        qualification / "source_discovery_recorded_cli.py",
        qualification / "source_acquisition_cli.py",
        qualification / "attributes" / "corpus" / "canonical.py",
    ]
    return {p.relative_to(qualification).as_posix(): sha256_hex(p.read_bytes()) for p in files if p.exists()}


def _source_revision() -> dict:
    """The checkout's commit and whether it had local changes; null when Git is unavailable."""
    qualification = Path(__file__).resolve().parent.parent
    try:
        commit = subprocess.run(["git", "-C", str(qualification), "rev-parse", "HEAD"], capture_output=True, text=True,
                                timeout=30, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(qualification), "status", "--porcelain"], capture_output=True, text=True,
                               timeout=30, check=True).stdout.strip() != ""
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "localChanges": None}
    return {"commit": commit or None, "localChanges": dirty}


def _validate_contact(contact: str) -> str:
    if not contact or any(c in contact for c in "\r\n()"):
        raise StoreError("--contact (an operator e-mail or URL for the User-Agent) is required")
    return contact


def _validate_limits(limits: dict) -> dict:
    if set(limits) != set(LIMITS):
        raise StoreError("limits must name exactly the documented keys")
    for key, value in limits.items():
        minimum = 0 if key in ("minIntervalSeconds", "scopeGapSeconds") else 1
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise StoreError(f"limit {key} must be an integer of at least {minimum}")
    return dict(limits)


def build_config(contact: str, scopes=PILOT_RETRY_SCOPES, limits: dict | None = None) -> dict:
    limits = _validate_limits(dict(LIMITS if limits is None else limits))
    user_agent = USER_AGENT.format(contact=_validate_contact(contact))
    return {
        "schema": CONFIG_SCHEMA,
        "provider": commons.PROVIDER,
        "purpose": "metadata-only discovery retry; no admission, no acquisition, no media request",
        "scopes": [dict(s) for s in scopes],
        "categoryCaveat": CATEGORY_CAVEAT,
        "limits": limits,
        "stopRules": list(STOP_RULES),
        "preflightUrl": PREFLIGHT_URL,
        "userAgent": user_agent,
        "requestHeaders": {"Accept": "*/*", "User-Agent": user_agent},
        "recordedResponseHeaders": {"names": list(RECORDED_HEADER_NAMES), "prefixes": list(RECORDED_HEADER_PREFIXES)},
        "helperSourceSha256": _source_hashes(),
        "sourceRevision": _source_revision(),
        "python": platform.python_version(),
        "host": platform.node(),
    }


def make_hard_stop(recorder: Recorder, exit_process: Callable[[int], None] = os._exit) -> Callable[[], None]:
    """The hard-deadline action: one durable event, then the process ends with exit code 124."""
    def _hard_stop() -> None:
        recorder.events.write("hard-deadline", attempts=recorder.attempts)
        exit_process(124)
    return _hard_stop


def run_discovery(run_root: Path, contact: str, *, stamp: str | None = None, scopes=PILOT_RETRY_SCOPES,
                  limits: dict | None = None, fetch: Callable | None = None, sleep: Callable[[float], None] = time.sleep,
                  monotonic: Callable[[], float] = time.monotonic, utc: Callable[[], str] = _utc_now,
                  hard_deadline: bool = True) -> tuple[Path, dict]:
    """One recorded run in a new directory under ``run_root``; returns (run directory, status)."""
    root = assert_controlled_store(run_root)
    if not root.is_dir():
        raise StoreError("run root must be an existing directory")
    config = build_config(contact, scopes, limits)
    limits = config["limits"]
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = root / f"commons-discovery-retry-{stamp}"
    run_dir.mkdir(exist_ok=False)
    (run_dir / "config").mkdir()
    config_bytes = canonical_json(config)
    config_sha = sha256_hex(config_bytes)
    _write_new(run_dir / "config" / "run-config.json", config_bytes)
    _write_new(run_dir / "config" / "run-config.sha256", f"{config_sha}  run-config.json\n".encode("ascii"))

    capture = run_dir / "capture"
    capture.mkdir()
    recorder = Recorder(capture, attempt_budget=limits["attemptBudget"], min_interval=limits["minIntervalSeconds"],
                        soft_deadline=limits["softDeadlineSeconds"], attempt_read_seconds=limits["attemptReadSeconds"],
                        body_limit=limits["bodyLimitBytes"], fetch=fetch, sleep=sleep, monotonic=monotonic, utc=utc)
    scope_log = EventLog(capture / "scopes.jsonl", utc)
    recorder.events.write("run-start", configSha256=config_sha)
    timer = None
    if hard_deadline:
        timer = threading.Timer(limits["hardDeadlineSeconds"], make_hard_stop(recorder))
        timer.daemon = True
        timer.start()
    transport = RecordedTransport(recorder, commons.ALLOWED_HOSTS, config["userAgent"])
    store = run_dir / "store"
    interrupted = False
    try:
        _run_scopes(recorder, scope_log, transport, store, scopes, limits)
    except KeyboardInterrupt:
        interrupted = True
        recorder.latch("interrupted")
    finally:
        if timer is not None:
            timer.cancel()
        recorder.events.write("run-end", attempts=recorder.attempts, stopReason=recorder.stop_reason)
        recorder.events.close()
        scope_log.close()
    status = finalize(run_dir, interrupted=interrupted)
    return run_dir, status


def _run_scopes(recorder: Recorder, log: EventLog, transport: Transport, store: Path, scopes, limits: dict) -> None:
    try:
        raw = transport.get_bytes(PREFLIGHT_URL)
        json.loads(raw.decode("utf-8"))
        log.write("preflight", status="OK" if recorder.stop_reason is None else "STOPPED", reason=recorder.stop_reason)
    except (TransportError, ValueError, OSError) as exc:
        recorder.latch(f"preflight-failed:{type(exc).__name__}")
        log.write("preflight", status="STOPPED", reason=recorder.stop_reason)
    described: set[str] = set()
    primary_described = 0
    first = True
    for scope in scopes:
        sid = scope["id"]
        if recorder.stop_reason is not None:
            log.write("scope", scope=sid, status="NOT_STARTED", reason=f"latched:{recorder.stop_reason}")
            continue
        if scope["pool"] == "secondary" and primary_described >= limits["secondaryOnlyIfPrimaryDescribedBelow"]:
            log.write("scope", scope=sid, status="NOT_NEEDED", reason="primary pool reached the secondary threshold")
            continue
        if len(described) >= limits["candidateCap"]:
            log.write("scope", scope=sid, status="NOT_STARTED", reason="candidate-cap")
            continue
        if not first:
            try:
                recorder.pause(limits["scopeGapSeconds"])
            except RunStopped:
                log.write("scope", scope=sid, status="NOT_STARTED", reason=f"latched:{recorder.stop_reason}")
                continue
        first = False
        caveat = CATEGORY_CAVEAT if scope["kind"] == "category" else None
        log.write("scope-start", scope=sid, kind=scope["kind"], query=scope["query"])
        if scope["kind"] == "search":
            url = commons.search_query_url(scope["query"], limits["scopeLimit"])
        else:
            url = commons.category_query_url(scope["query"], limits["scopeLimit"])
        try:
            raw = transport.get_bytes(url)
            response = json.loads(raw.decode("utf-8"))
        except (TransportError, ValueError, OSError) as exc:
            recorder.latch(f"list-failed:{type(exc).__name__}")
            log.write("scope", scope=sid, status="LIST_FAILED", reason=recorder.stop_reason, listAttempt=recorder.last_list_attempt,
                      categoryCaveat=caveat)
            continue
        if recorder.stop_reason is not None:
            log.write("scope", scope=sid, status="API_ERROR", reason=recorder.stop_reason, listAttempt=recorder.last_list_attempt,
                      categoryCaveat=caveat)
            continue
        query = response.get("query") if isinstance(response, dict) else None
        rows = (query or {}).get("search") or (query or {}).get("categorymembers") or []
        titles = commons.discovered_titles(response if isinstance(response, dict) else {})
        try:
            result = discover(store, titles, transport)
        except Exception as exc:  # noqa: BLE001 - a crash inside the helper keeps its partial evidence
            recorder.latch(f"discover-failed:{type(exc).__name__}")
            log.write("scope", scope=sid, status="DISCOVER_FAILED", reason=recorder.stop_reason, listAttempt=recorder.last_list_attempt,
                      listRows=len(rows), videoTitles=titles, categoryCaveat=caveat)
            continue
        errors = [item for item in result["items"] if item.get("error")]
        ok = [item["fileTitle"] for item in result["items"] if not item.get("error")]
        described.update(ok)
        if scope["pool"] == "primary":
            primary_described = len(described)
        log.write("scope", scope=sid, status="PER_FILE_ERRORS" if errors else "COMPLETE", reason=recorder.stop_reason,
                  listAttempt=recorder.last_list_attempt, listRows=len(rows), listContinues=bool(isinstance(response, dict) and "continue" in response),
                  videoTitles=titles, describedWithoutError=len(ok), itemErrors=len(errors),
                  discoveryReportSha256=result["discoveryReportSha256"], decisionsTemplate=result["decisionsTemplate"],
                  categoryCaveat=caveat)
        if errors:
            recorder.latch("per-file-error")


def _write_new(path: Path, data: bytes) -> None:
    """Create ``path`` atomically and never overwrite it: write a partial, fsync, then hard-link."""
    partial = path.with_name(path.name + ".partial")
    if partial.exists():
        partial.unlink()  # our own incomplete write from an earlier crash; the target was never created
    with open(partial, "xb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    try:
        os.link(partial, path)
    finally:
        partial.unlink()


def _read_jsonl(path: Path) -> tuple[list[dict], int]:
    if not path.exists():
        return [], 0
    records, unreadable = [], 0
    for line in path.read_bytes().splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            unreadable += 1
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            unreadable += 1
    return records, unreadable


def finalize(run_dir: Path, *, interrupted: bool = False) -> dict:
    """Local only: derive run-status.json from the durable records. Never overwrites."""
    run_dir = Path(run_dir)
    target = run_dir / "run-status.json"
    if target.exists():
        raise StoreError("run-status.json already exists; refusing to overwrite")
    events, bad_events = _read_jsonl(run_dir / "capture" / "events.jsonl")
    scope_events, bad_scopes = _read_jsonl(run_dir / "capture" / "scopes.jsonl")
    try:
        declared = [s["id"] for s in json.loads((run_dir / "config" / "run-config.json").read_bytes())["scopes"]]
    except (OSError, ValueError, KeyError, TypeError):
        declared = []
    starts = {e["attempt"] for e in events if e.get("event") == "attempt-start"}
    ends = {e["attempt"]: e for e in events if e.get("event") == "attempt-end"}
    latched = [e.get("reason") for e in events if e.get("event") == "latched"]
    hard = any(e.get("event") == "hard-deadline" for e in events)
    run_ended = any(e.get("event") == "run-end" for e in events)
    unfinished = sorted(starts - set(ends))
    bodies = run_dir / "capture" / "bodies"
    incomplete = sorted(p.name for p in bodies.glob("*.part")) if bodies.exists() else []
    finished_scopes = {s["scope"]: s for s in scope_events if s.get("event") == "scope"}
    started_scopes = [s["scope"] for s in scope_events if s.get("event") == "scope-start"]
    interrupted_scopes = [sid for sid in started_scopes if sid not in finished_scopes]
    scope_status = [finished_scopes.get(sid) or {"scope": sid, "status": "INTERRUPTED" if sid in interrupted_scopes else "NO_RECORD"}
                    for sid in declared]
    if (interrupted or hard or not run_ended or unfinished or interrupted_scopes or bad_events or bad_scopes
            or (latched and latched[0] == "interrupted")):
        state = "INTERRUPTED"
    elif latched:
        state = "STOPPED"
    else:
        state = "COMPLETE"
    status = {
        "schema": STATUS_SCHEMA,
        "status": state,
        "stopReason": latched[0] if latched else ("hard-deadline" if hard else None),
        "hardDeadline": hard,
        "attemptsStarted": len(starts),
        "attemptsCompleted": sum(1 for e in ends.values() if e.get("complete")),
        "attemptsWithoutEndRecord": unfinished,
        "incompleteBodies": incomplete,
        "unreadableLines": bad_events + bad_scopes,
        "preflight": next((s for s in scope_events if s.get("event") == "preflight"), None),
        "scopes": scope_status,
        "interruptedScopes": interrupted_scopes,
        "describedWithoutError": sum(int(s.get("describedWithoutError") or 0) for s in finished_scopes.values()),
        "categoryCaveat": CATEGORY_CAVEAT,
        "finalizedUtc": _utc_now(),
    }
    _write_new(target, canonical_json(status))
    return status


def _role(relative: str) -> str:
    if relative.startswith("config/"):
        return "configuration"
    if relative.startswith("capture/bodies/"):
        return "incomplete-partial-response-body" if relative.endswith(".part") else "complete-response-body"
    if relative.startswith("capture/"):
        return "capture-log"
    if relative.startswith("store/"):
        return "helper-store-record"
    if relative == "run-status.json":
        return "run-status"
    return "other"


def bundle(run_dir: Path, evidence_root: Path, name: str) -> Path:
    """MANIFEST.json + .tar.gz of a finalised run in a new evidence directory, re-verified."""
    run_dir = assert_controlled_store(run_dir)
    if not (run_dir / "run-status.json").exists():
        raise StoreError("run is not finalised (run-status.json missing)")
    destination = assert_controlled_store(evidence_root) / name
    destination.mkdir(exist_ok=False)
    files = []
    for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        relative = path.relative_to(run_dir).as_posix()
        data = path.read_bytes()
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        files.append({"path": relative, "bytes": len(data), "sha256": sha256_hex(data), "role": _role(relative),
                      "modifiedUtc": modified})
    manifest = {"schema": MANIFEST_SCHEMA, "run": run_dir.name, "files": files,
                "runStatus": json.loads((run_dir / "run-status.json").read_bytes()),
                "createdUtc": _utc_now()}
    _write_new(destination / "MANIFEST.json", canonical_json(manifest))
    archive = destination / f"{name}.tar.gz"
    with tarfile.open(archive, "x:gz") as tar:
        for entry in files:
            tar.add(run_dir / entry["path"], arcname=f"{name}/{entry['path']}", recursive=False)
        tar.add(destination / "MANIFEST.json", arcname=f"{name}/MANIFEST.json", recursive=False)
    verify_bundle(destination, name, require_checksum=False)
    _write_new(destination / f"{name}.tar.gz.sha256", f"{sha256_hex(archive.read_bytes())}  {archive.name}\n".encode("ascii"))
    return destination


def verify_bundle(destination: Path, name: str, *, require_checksum: bool = True) -> None:
    """Every archive member matches MANIFEST.json, nothing is missing or extra, and the archive hash matches."""
    destination = Path(destination)
    manifest_bytes = (destination / "MANIFEST.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    archive = destination / f"{name}.tar.gz"
    if require_checksum:
        recorded = (destination / f"{name}.tar.gz.sha256").read_text(encoding="ascii").split()[0]
        if sha256_hex(archive.read_bytes()) != recorded:
            raise StoreError("bundle verification failed: archive SHA-256 differs")
    expected = {e["path"]: e["sha256"] for e in manifest["files"]}
    expected["MANIFEST.json"] = sha256_hex(manifest_bytes)
    with tarfile.open(archive, "r:gz") as tar:
        members = {}
        for member in tar.getmembers():
            if not member.isfile() or not member.name.startswith(f"{name}/"):
                raise StoreError(f"bundle verification failed: unexpected member {member.name}")
            members[member.name[len(name) + 1:]] = member
        if set(members) != set(expected):
            raise StoreError("bundle verification failed: member set differs")
        for relative, digest in expected.items():
            handle = tar.extractfile(members[relative])
            if handle is None or sha256_hex(handle.read()) != digest:
                raise StoreError(f"bundle verification failed: {relative}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recorded_discovery", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="one recorded metadata-only run of the predeclared scopes")
    r.add_argument("--run-root", required=True, type=Path)
    r.add_argument("--contact", required=True)
    f = sub.add_parser("finalize", help="local only: derive run-status.json after a hard stop")
    f.add_argument("--run-dir", required=True, type=Path)
    b = sub.add_parser("bundle", help="local only: MANIFEST.json and .tar.gz in a new evidence directory")
    b.add_argument("--run-dir", required=True, type=Path)
    b.add_argument("--evidence-root", required=True, type=Path)
    b.add_argument("--name", required=True)
    v = sub.add_parser("verify-bundle", help="local only: re-verify a bundle against its manifest and checksum")
    v.add_argument("--evidence-dir", required=True, type=Path)
    v.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            run_dir, status = run_discovery(args.run_root, args.contact)
            print(json.dumps({"runDir": run_dir.name, "status": status["status"], "stopReason": status["stopReason"],
                              "attemptsStarted": status["attemptsStarted"], "describedWithoutError": status["describedWithoutError"]}, indent=2))
            return {"COMPLETE": 0, "STOPPED": 1}.get(status["status"], 130)
        if args.command == "finalize":
            status = finalize(args.run_dir)
            print(json.dumps({"status": status["status"], "stopReason": status["stopReason"]}, indent=2))
            return 0
        if args.command == "verify-bundle":
            verify_bundle(args.evidence_dir, args.name)
            print(json.dumps({"verified": True}, indent=2))
            return 0
        destination = bundle(args.run_dir, args.evidence_root, args.name)
        print(json.dumps({"evidenceDir": destination.name}, indent=2))
        return 0
    except (StoreError, OSError, ValueError, KeyError, tarfile.TarError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
