"""Bounded deterministic S2b job replay, not a general scheduler.

Instants are exact UTC microseconds. Fixed ordering at an instant: worker/platform
loss, sweep, Phase A, Phase C commit, acknowledgement, heartbeat, claim poll.
Thus a boundary failure cannot disappear through presentation ordering. Heartbeats
stop at Phase A; Phase C is ownership fenced independently of the live lease.
The bounded publication constraint is reported separately from lifecycle validity.
Services are whole jobs measured through E2, never per-Track p95 arithmetic.
"""
from __future__ import annotations

import heapq
import re
from datetime import datetime, timedelta, timezone

from .canonical import digest, integer, keys, require, text, tokens

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
POLICY_KEYS = {"leaseDurationUs", "heartbeatExtensionUs", "heartbeatIntervalUs", "maximumAttempts",
               "maximumAnalysisDurationUs", "claimPollUs", "sweepPollUs"}
SERVICE_KEYS = {"phaseAUs", "publicationUs", "phaseCStampOffsetUs", "acknowledgementUs",
                "explicitFailureAtUs", "failureRetryable"}


def instant(value: object, where: str) -> int:
    require(type(value) is str and UTC_RE.fullmatch(value) is not None, f"{where}:UTC_microseconds_required")
    try:
        delta = datetime.fromisoformat(value.replace("Z", "+00:00")) - EPOCH
    except ValueError as exc:
        raise ValueError(f"{where}:UTC_invalid") from exc
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def utc(value: int | None) -> str | None:
    return None if value is None else (EPOCH + timedelta(microseconds=value)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def replay(jobs: list[dict], workers: list[dict], policy: dict, services: dict,
           outages: list[dict], *, startAtUtc: str, endAtUtc: str) -> dict:
    keys(policy, POLICY_KEYS, "policy")
    for key, value in policy.items(): integer(value, key, 1)
    require(policy["heartbeatIntervalUs"] < min(policy["leaseDurationUs"], policy["heartbeatExtensionUs"]), "heartbeat:margin")
    start, end = instant(startAtUtc, "startAtUtc"), instant(endAtUtc, "endAtUtc")
    require(start < end, "replay:horizon")
    require(type(jobs) is type(workers) is type(outages) is list and bool(workers), "replay:lists")
    require(len(jobs) <= 100_000 and len(workers) <= 10_000, "replay:bounded_population")
    require((end - start) // min(policy["claimPollUs"], policy["sweepPollUs"]) * (len(workers)+1) <= 2_000_000,
            "replay:bounded_events")
    for shape, service in services.items():
        text(shape, "shape")
        keys(service, SERVICE_KEYS, "service")
        for key in SERVICE_KEYS - {"explicitFailureAtUs", "failureRetryable"}: integer(service[key], key)
        require(service["phaseCStampOffsetUs"] <= service["publicationUs"], "service:phaseC_stamp")
        if service["explicitFailureAtUs"] is not None:
            integer(service["explicitFailureAtUs"], "explicitFailureAtUs")
            require(service["explicitFailureAtUs"] < service["phaseAUs"], "service:failure_before_phaseA")
        require(type(service["failureRetryable"]) is bool, "service:retryable")
    state, processes = {}, {}
    for job in jobs:
        keys(job, {"id", "shape", "queuedAtUtc", "identitySha256", "personTracks", "vehicleTracks"}, "job")
        jid = text(job["id"], "jobId")
        require(jid not in state and job["shape"] in services, "job:duplicate_or_shape")
        digest(job["identitySha256"], "job:identity")
        queued = instant(job["queuedAtUtc"], "queuedAtUtc")
        integer(job["personTracks"], "personTracks")
        integer(job["vehicleTracks"], "vehicleTracks")
        require(job["personTracks"] + job["vehicleTracks"] <= 10_000, "job:10k_bound")
        state[jid] = {**job, "queue": queued, "status": "Queued", "attempts": 0, "first": None,
                      "lease": None, "owner": None, "phaseA": None, "commit": None, "stamp": None,
                      "ack": None, "cap": None, "failureCode": None, "boundedPublicationPassed": None}
    for worker in workers:
        keys(worker, {"workerId", "hostId", "readyAtUtc", "identitySha256"}, "worker")
        wid = text(worker["workerId"], "workerId")
        text(worker["hostId"], "hostId")
        digest(worker["identitySha256"], "worker:identity")
        require(wid not in processes, "worker:duplicate")
        processes[wid] = {**worker, "ready": instant(worker["readyAtUtc"], "readyAtUtc"), "generation": 0,
                          "busy": None}
    heap, sequence, events = [], 0, []
    priorities = {"loss": 0, "sweep": 1, "phaseA": 2, "commit": 3, "ack": 4, "heartbeat": 5, "poll": 6, "fail": 2}

    def schedule(at, kind, wid="", jid="", attempt=0, generation=0, payload=None):
        nonlocal sequence
        sequence += 1
        if at <= end:
            heapq.heappush(heap, (at, priorities[kind], wid, jid, sequence, kind, attempt, generation, payload))

    def record(at, kind, jid, **extra):
        events.append({"atUtc": utc(at), "kind": kind, "jobId": jid, **extra})

    for wid, process in sorted(processes.items()): schedule(max(start, process["ready"]), "poll", wid)
    schedule(start, "sweep")
    ranges = {wid: [] for wid in processes}
    for outage in outages:
        keys(outage, {"workerIds", "lostAtUtc", "readyAtUtc", "publicationLost"}, "outage")
        tokens(outage["workerIds"], "outage:workerIds", nonempty=True)
        lost, ready = instant(outage["lostAtUtc"], "lostAtUtc"), instant(outage["readyAtUtc"], "readyAtUtc")
        require(start <= lost < ready <= end and type(outage["publicationLost"]) is bool, "outage:range")
        for wid in outage["workerIds"]:
            require(wid in processes, "outage:worker_unknown")
            require(all(ready <= a or lost >= b for a, b in ranges[wid]), "outage:overlap")
            ranges[wid].append((lost, ready))
            schedule(lost, "loss", wid, payload=(ready, outage["publicationLost"]))
    peak_backlog = 0
    count = 0
    while heap:
        at, _, wid, jid, _, kind, attempt, generation, payload = heapq.heappop(heap)
        count += 1
        require(count <= 5_000_000, "replay:event_limit")
        process = processes.get(wid)
        unit = state.get(jid)
        peak_backlog = max(peak_backlog, sum(u["status"] == "Queued" and u["queue"] <= at for u in state.values()))
        if kind == "loss":
            process["generation"] += 1
            process["ready"] = payload[0]
            process["busy"] = None
            if payload[1]:
                # Platform-side publication loss is distinct from worker-only loss.
                for u in state.values():
                    if u["owner"] == wid and u["status"] == "Running": u["publicationLost"] = True
            record(at, "loss", "", workerId=wid)
            continue
        if kind == "sweep":
            for ident, u in sorted(state.items()):
                if u["status"] not in ("Queued", "Running") or u["first"] is None: continue
                live = u["lease"] is not None and at < u["lease"]
                deadline = u["first"] + policy["maximumAnalysisDurationUs"]
                if not live and (at >= deadline or u["attempts"] >= policy["maximumAttempts"]):
                    u["status"] = "Failed"
                    u["failureCode"] = "deadline" if at >= deadline else "attempts"
                    record(at, "terminal", ident, failureCode=u["failureCode"])
            schedule(at + policy["sweepPollUs"], "sweep")
            continue
        if kind == "poll":
            schedule(at + policy["claimPollUs"], "poll", wid)
            if at < process["ready"] or process["busy"] is not None: continue
            available = [u for u in state.values() if u["queue"] <= at and u["identitySha256"] == process["identitySha256"]
                         and u["attempts"] < policy["maximumAttempts"]
                         and (u["first"] is None or at < u["first"] + policy["maximumAnalysisDurationUs"])
                         and (u["status"] == "Queued" or (u["status"] == "Running" and at >= u["lease"]))]
            if not available: continue
            unit = min(available, key=lambda u: (u["queue"], u["id"]))
            jid = unit["id"]
            unit["first"] = at if unit["first"] is None else unit["first"]
            unit["attempts"] += 1
            attempt = unit["attempts"]
            unit.update(status="Running", owner=wid, phaseA=None, publicationLost=False,
                        lease=min(at + policy["leaseDurationUs"], unit["first"] + policy["maximumAnalysisDurationUs"]))
            process["busy"] = (jid, attempt)
            generation = process["generation"]
            service = services[unit["shape"]]
            record(at, "claim", jid, workerId=wid, attempt=attempt, leaseExpiresAtUtc=utc(unit["lease"]))
            if service["explicitFailureAtUs"] is not None:
                schedule(at + service["explicitFailureAtUs"], "fail", wid, jid, attempt, generation)
            else:
                schedule(at + service["phaseAUs"], "phaseA", wid, jid, attempt, generation)
            schedule(at + policy["heartbeatIntervalUs"], "heartbeat", wid, jid, attempt, generation)
            continue
        owned = unit["status"] == "Running" and unit["owner"] == wid and unit["attempts"] == attempt
        worker_live = generation == process["generation"] and at >= process["ready"]
        if kind == "phaseA" and worker_live and not owned and process["busy"] == (jid, attempt):
            # An expired attempt still occupies the serial inference lane until
            # its measured execution drains. Then release it for the next job.
            process["busy"] = None
        if kind == "commit":
            if owned and not unit.get("publicationLost"):
                unit.update(status="Completed", commit=at, boundedPublicationPassed=at <= unit["cap"])
                record(at, "commit", jid, attempt=attempt)
                if worker_live: schedule(at + services[unit["shape"]]["acknowledgementUs"], "ack", wid, jid, attempt, generation)
            elif worker_live and process["busy"] == (jid, attempt): process["busy"] = None
            continue
        if kind == "ack":
            if worker_live and unit["status"] == "Completed" and unit["attempts"] == attempt:
                unit["ack"] = at
                process["busy"] = None
                record(at, "ack", jid, attempt=attempt)
            continue
        if not owned or not worker_live: continue
        live = at < unit["lease"]
        if kind == "heartbeat":
            if unit["phaseA"] is not None: continue
            if not live:
                # Serial inference cannot be assumed checkpointed or reusable. A busy
                # lane drains at its measured Phase-A boundary before the next claim.
                record(at, "lease_lost", jid, attempt=attempt)
                continue
            deadline = unit["first"] + policy["maximumAnalysisDurationUs"]
            unit["lease"] = max(unit["lease"], min(at + policy["heartbeatExtensionUs"], deadline))
            record(at, "heartbeat", jid, leaseExpiresAtUtc=utc(unit["lease"]))
            schedule(at + policy["heartbeatIntervalUs"], "heartbeat", wid, jid, attempt, generation)
        elif kind == "fail":
            if live:
                retry = services[unit["shape"]]["failureRetryable"] and attempt < policy["maximumAttempts"] and at < unit["first"] + policy["maximumAnalysisDurationUs"]
                unit.update(status="Queued" if retry else "Failed", lease=None, owner=None,
                            failureCode=None if retry else "explicit-failure")
                record(at, "fail", jid, attempt=attempt, retryable=retry)
            process["busy"] = None
        elif kind == "phaseA":
            if not live:
                process["busy"] = None
                continue
            service = services[unit["shape"]]
            deadline = unit["first"] + policy["maximumAnalysisDurationUs"]
            unit.update(phaseA=at, cap=min(at + policy["leaseDurationUs"], deadline + policy["leaseDurationUs"]),
                        stamp=at + service["phaseCStampOffsetUs"])
            unit["lease"] = max(unit["lease"], unit["cap"])
            record(at, "phaseA", jid, attempt=attempt, leaseExpiresAtUtc=utc(unit["lease"]))
            schedule(at + service["publicationUs"], "commit", wid, jid, attempt, generation)
    output = {}
    for jid, unit in sorted(state.items()):
        output[jid] = {"status": unit["status"], "attempts": unit["attempts"], "queuedAtUtc": unit["queuedAtUtc"],
                       "firstClaimedAtUtc": utc(unit["first"]), "phaseAValidatedAtUtc": utc(unit["phaseA"]),
                       "publicationCommittedAtUtc": utc(unit["commit"]), "completedAtUtc": utc(unit["stamp"]) if unit["commit"] is not None else None,
                       "completionAcknowledgedAtUtc": utc(unit["ack"]), "boundedPublicationPassed": unit["boundedPublicationPassed"],
                       "failureCode": unit["failureCode"], "personTracks": unit["personTracks"], "vehicleTracks": unit["vehicleTracks"]}
    return {"jobs": output, "events": events, "peakBacklog": peak_backlog,
            "unfinishedTracks": sum(u["personTracks"]+u["vehicleTracks"] for u in state.values() if u["status"] != "Completed"),
            "waitingJobs": sum(u["status"] == "Queued" for u in state.values()),
            "oldestQueueAgeUs": max((end-u["queue"] for u in state.values() if u["status"] == "Queued" and u["queue"] <= end), default=0)}
