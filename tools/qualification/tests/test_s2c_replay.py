"""Bounded whole-job counterexamples against the S2b lifecycle."""
from __future__ import annotations

import importlib
import importlib.util

import pytest

T0 = "2026-09-01T00:00:00.000000Z"


@pytest.fixture
def replay():
    name = "model_selection.job_replay"
    if importlib.util.find_spec(name) is None:
        def missing(*args, **kwargs): pytest.fail("bounded job replay missing")
        return missing
    return importlib.import_module(name).replay


def policy(**changes):
    result = {"leaseDurationUs": 5_000_000, "heartbeatExtensionUs": 5_000_000,
              "heartbeatIntervalUs": 2_000_000, "maximumAttempts": 3,
              "maximumAnalysisDurationUs": 20_000_000, "claimPollUs": 1_000_000,
              "sweepPollUs": 1_000_000}
    result.update(changes)
    return result


def worker(id="w", **changes):
    result = {"workerId": id, "hostId": "h", "readyAtUtc": T0, "identitySha256": "a" * 64}
    result.update(changes)
    return result


def job(id="j", shape="small", **changes):
    result = {"id": id, "shape": shape, "queuedAtUtc": T0,
              "identitySha256": "a" * 64, "personTracks": 10, "vehicleTracks": 0}
    result.update(changes)
    return result


def service(a=3, publication=1, **changes):
    result = {"phaseAUs": a * 1_000_000, "publicationUs": publication * 1_000_000,
              "phaseCStampOffsetUs": 0, "acknowledgementUs": 2_000_000,
              "explicitFailureAtUs": None, "failureRetryable": True}
    result.update(changes)
    return result


def run(replay, jobs=None, workers=None, services=None, outages=None, **changes):
    return replay(jobs or [job()], workers or [worker()], policy(**changes),
                  services or {"small": service()}, outages or [],
                  startAtUtc=T0, endAtUtc="2026-09-01T00:01:00.000000Z")


def test_fifo_timestamp_then_id_one_unit_per_process(replay):
    result = run(replay, jobs=[job("b"), job("a")])
    claims = [e for e in result["events"] if e["kind"] == "claim"]
    assert [e["jobId"] for e in claims] == ["a", "b"]
    assert claims[1]["atUtc"] >= result["jobs"]["a"]["completionAcknowledgedAtUtc"]
    assert result["jobs"]["a"]["attempts"] == 1


def test_retry_retains_queue_position_and_consumes_attempt_at_claim(replay):
    result = run(replay, jobs=[job("a"), job("b")], services={"small": service(explicitFailureAtUs=1_000_000)})
    assert [e["jobId"] for e in result["events"] if e["kind"] == "claim"] == ["a", "a", "a", "b", "b", "b"]
    assert result["jobs"]["a"]["attempts"] == 3
    assert result["jobs"]["a"]["queuedAtUtc"] == T0


def test_identity_fence_consumes_no_attempt(replay):
    result = run(replay, workers=[worker(identitySha256="b" * 64)])
    assert result["jobs"]["j"]["attempts"] == 0
    assert result["jobs"]["j"]["firstClaimedAtUtc"] is None


def test_host_loss_near_finish_reexecutes_after_expiry(replay):
    outage = {"workerIds": ["w"], "lostAtUtc": "2026-09-01T00:00:09.000000Z",
              "readyAtUtc": "2026-09-01T00:00:10.000000Z", "publicationLost": False}
    result = run(replay, services={"small": service(10)}, outages=[outage], maximumAnalysisDurationUs=40_000_000)
    claims = [e for e in result["events"] if e["kind"] == "claim"]
    assert len(claims) == 2
    assert claims[1]["atUtc"] == "2026-09-01T00:00:13.000000Z"
    assert result["jobs"]["j"]["phaseAValidatedAtUtc"] == "2026-09-01T00:00:23.000000Z"


def test_restart_before_lease_expiry_cannot_overlap_ownership(replay):
    outage = {"workerIds": ["w"], "lostAtUtc": "2026-09-01T00:00:01.000000Z",
              "readyAtUtc": "2026-09-01T00:00:02.000000Z", "publicationLost": False}
    result = run(replay, outages=[outage])
    claims = [e for e in result["events"] if e["kind"] == "claim"]
    assert claims[1]["atUtc"] == "2026-09-01T00:00:05.000000Z"


def test_phase_A_before_deadline_publication_after_is_valid(replay):
    result = run(replay, services={"small": service(19, 3)})
    row = result["jobs"]["j"]
    assert row["status"] == "Completed"
    assert row["publicationCommittedAtUtc"] == "2026-09-01T00:00:22.000000Z"
    assert row["boundedPublicationPassed"] is True
    assert row["completedAtUtc"] == "2026-09-01T00:00:19.000000Z"
    assert row["completionAcknowledgedAtUtc"] == "2026-09-01T00:00:24.000000Z"


def test_publication_cap_is_operational_gate_not_invented_phase_C_fence(replay):
    # Sparse sweeps/polls leave ownership unchanged after the protection window.
    result = run(replay, services={"small": service(3, 9)}, claimPollUs=30_000_000, sweepPollUs=30_000_000)
    assert result["jobs"]["j"]["status"] == "Completed"
    assert result["jobs"]["j"]["boundedPublicationPassed"] is False


def test_no_claim_or_reclaim_at_deadline_leases_capped(replay):
    result = run(replay, services={"small": service(25)})
    assert result["jobs"]["j"]["status"] == "Failed"
    assert result["jobs"]["j"]["failureCode"] == "deadline"
    claims = [e for e in result["events"] if e["kind"] == "claim"]
    assert len(claims) == 1
    renewals = [e for e in result["events"] if e["kind"] == "heartbeat"]
    assert max(e["leaseExpiresAtUtc"] for e in renewals) == "2026-09-01T00:00:20.000000Z"


def test_publication_survives_worker_loss_after_phase_A(replay):
    outage = {"workerIds": ["w"], "lostAtUtc": "2026-09-01T00:00:04.000000Z",
              "readyAtUtc": "2026-09-01T00:00:10.000000Z", "publicationLost": False}
    result = run(replay, services={"small": service(3, 3)}, outages=[outage])
    assert result["jobs"]["j"]["publicationCommittedAtUtc"] == "2026-09-01T00:00:06.000000Z"
    assert result["jobs"]["j"]["attempts"] == 1


def test_equal_track_rate_different_job_skew_changes_queue_latency(replay):
    smooth = run(replay, jobs=[job("a", personTracks=10), job("b", queuedAtUtc="2026-09-01T00:00:06.000000Z", personTracks=10)])
    skew = run(replay, jobs=[job("a", "large", personTracks=20), job("b", personTracks=0)],
               services={"small": service(1), "large": service(12)})
    assert skew["jobs"]["b"]["publicationCommittedAtUtc"] > smooth["jobs"]["b"]["publicationCommittedAtUtc"]


def test_terminal_attempt_cannot_permanently_starve_next_job(replay):
    result = run(replay, jobs=[job("a", "large"), job("b", queuedAtUtc="2026-09-01T00:00:30.000000Z")],
                 services={"large": service(25), "small": service(3)})
    assert result["jobs"]["a"]["status"] == "Failed"
    assert result["jobs"]["b"]["status"] == "Completed"


@pytest.mark.parametrize("mutation", ["offset", "naive", "unknown", "bool"])
def test_replay_strict_input_refusals(replay, mutation):
    jobs, p = [job()], policy()
    if mutation == "offset": jobs[0]["queuedAtUtc"] = "2026-09-01T00:00:00+05:30"
    if mutation == "naive": jobs[0]["queuedAtUtc"] = "2026-09-01T00:00:00"
    if mutation == "unknown": jobs[0]["queuedAt"] = jobs[0].pop("queuedAtUtc")
    if mutation == "bool": p["maximumAttempts"] = True
    with pytest.raises(ValueError): replay(jobs, [worker()], p, {"small": service()}, [], startAtUtc=T0,
                                         endAtUtc="2026-09-01T00:01:00.000000Z")
