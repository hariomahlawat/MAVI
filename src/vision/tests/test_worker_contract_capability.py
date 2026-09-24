"""W family: the worker emits completion 3.0 only against a platform that lists it.

Plan §23–24: the capability is probed before any lease; an incompatible or
malformed answer keeps the worker not-ready (no lease, no v2 fallback); a later
``400 worker_contract_version_unsupported`` at completion is a terminal attempt
failure that is not retried.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mavi_vision.common.control_plane import VisionJobLease
from mavi_vision.storage.local_media_store import LocalMediaStore
from mavi_vision.worker.client import CompletionPayloadInvalid, PlatformContractUnsupported, WorkerApiError
from mavi_vision.worker.runner import WorkerRunner

from test_worker_runner import (
    PROVENANCE_SENTINEL,
    FakeWorkerApiClient,
    RecordingProcessor,
    make_lease,
    make_result,
)


class ProbingApi(FakeWorkerApiClient):
    """Answers the capability probe from a scripted sequence of outcomes."""

    def __init__(self, leased_job: VisionJobLease | None, probes: list[object]) -> None:
        super().__init__(leased_job)
        self.probes = list(probes)
        self.complete_error: Exception | None = None

    async def get_contract_capabilities(self) -> None:
        self.events.append("probe")
        outcome = self.probes.pop(0) if self.probes else None
        if isinstance(outcome, Exception):
            raise outcome
        return None

    async def complete(self, lease, result, processing_duration_ms, provenance, *, authorize_publish=None):
        if self.complete_error is None:
            return await super().complete(
                lease, result, processing_duration_ms, provenance, authorize_publish=authorize_publish
            )
        self.events.append("complete")
        raise self.complete_error


def _media(tmp_path: Path) -> None:
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"video")


def _runner(client: ProbingApi, tmp_path: Path, lease: VisionJobLease) -> WorkerRunner:
    return WorkerRunner(
        client,
        LocalMediaStore(tmp_path),
        2.0,
        RecordingProcessor(make_result(lease)),
        runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
    )


def test_incompatible_platform_is_never_leased_and_is_reprobed(tmp_path: Path) -> None:
    lease = make_lease()
    unsupported = PlatformContractUnsupported("platform does not accept completion 3.0")
    client = ProbingApi(lease, [unsupported, unsupported])
    runner = _runner(client, tmp_path, lease)

    async def scenario() -> list[bool]:
        return [await runner.run_once(), await runner.run_once()]

    assert asyncio.run(scenario()) == [False, False]
    assert client.events == ["probe", "probe"]
    assert runner.platform_contract_confirmed is False
    assert client.completions == [] and client.failures == []


def test_capability_is_probed_before_every_lease(tmp_path: Path) -> None:
    lease = make_lease()
    _media(tmp_path)
    client = ProbingApi(lease, [None])
    runner = _runner(client, tmp_path, lease)

    async def scenario() -> list[bool]:
        return [await runner.run_once(), await runner.run_once()]

    assert asyncio.run(scenario()) == [True, True]
    assert client.events == [
        "probe", "lease", "heartbeat", "complete", "probe", "lease", "heartbeat", "complete"
    ]
    assert runner.platform_contract_confirmed is True


def test_a_platform_downgrade_between_leases_is_caught_before_leasing(tmp_path: Path) -> None:
    lease = make_lease()
    _media(tmp_path)
    client = ProbingApi(lease, [None, PlatformContractUnsupported("downgraded")])
    runner = _runner(client, tmp_path, lease)

    async def scenario() -> list[bool]:
        return [await runner.run_once(), await runner.run_once()]

    assert asyncio.run(scenario()) == [True, False]
    # The second job is never leased, so it is not burned by a 3.0 rejection.
    assert client.events == ["probe", "lease", "heartbeat", "complete", "probe"]
    assert runner.platform_contract_confirmed is False


def test_an_invalid_local_completion_fails_the_attempt_instead_of_crashing(tmp_path: Path) -> None:
    lease = make_lease()
    _media(tmp_path)
    client = ProbingApi(lease, [None])
    client.complete_error = CompletionPayloadInvalid("vision result is not a valid completion 3.0 body")
    runner = _runner(client, tmp_path, lease)

    assert asyncio.run(runner.run_once()) is True
    assert client.events == ["probe", "lease", "heartbeat", "complete", "fail:vision_result_invalid"]


def test_platform_upgrade_is_picked_up_on_a_later_poll(tmp_path: Path) -> None:
    lease = make_lease()
    _media(tmp_path)
    client = ProbingApi(lease, [PlatformContractUnsupported("malformed"), None])
    runner = _runner(client, tmp_path, lease)

    async def scenario() -> list[bool]:
        return [await runner.run_once(), await runner.run_once()]

    assert asyncio.run(scenario()) == [False, True]
    assert client.events == ["probe", "probe", "lease", "heartbeat", "complete"]


def test_probe_transport_failure_propagates_without_lease(tmp_path: Path) -> None:
    lease = make_lease()
    client = ProbingApi(lease, [WorkerApiError("worker API request failed")])
    runner = _runner(client, tmp_path, lease)

    with pytest.raises(WorkerApiError):
        asyncio.run(runner.run_once())
    assert client.events == ["probe"]
    assert runner.platform_contract_confirmed is False


def test_control_plane_error_forces_reprobe_before_next_lease(tmp_path: Path) -> None:
    lease = make_lease()
    _media(tmp_path)
    client = ProbingApi(lease, [None, None])
    client.complete_error = WorkerApiError("worker API request failed")
    runner = _runner(client, tmp_path, lease)

    with pytest.raises(WorkerApiError):
        asyncio.run(runner.run_once())
    assert runner.platform_contract_confirmed is False
    client.complete_error = None
    assert asyncio.run(runner.run_once()) is True
    assert client.events == [
        "probe", "lease", "heartbeat", "complete", "probe", "lease", "heartbeat", "complete"
    ]


def test_completion_contract_rejection_is_terminal_and_not_retried(tmp_path: Path) -> None:
    lease = make_lease()
    _media(tmp_path)
    client = ProbingApi(lease, [None, PlatformContractUnsupported("downgraded")])
    client.complete_error = PlatformContractUnsupported(
        "platform rejected completion 3.0",
        status_code=400,
        code="worker_contract_version_unsupported",
    )
    runner = _runner(client, tmp_path, lease)

    async def scenario() -> list[bool]:
        return [await runner.run_once(), await runner.run_once()]

    assert asyncio.run(scenario()) == [True, False]
    # One completion, one terminal failure, then re-probing keeps it not-ready:
    # no second completion, no v2 completion, no further lease.
    assert client.events == [
        "probe",
        "lease",
        "heartbeat",
        "complete",
        "fail:vision_worker_contract_unsupported",
        "probe",
    ]
    assert client.completions == []
    assert runner.platform_contract_confirmed is False
