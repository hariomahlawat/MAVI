"""E2 observation adapter for the existing S2b AttributeRunner inference seam.

No replacement scheduler, crop loop, aggregation or completion implementation.
Client latency is measured separately from authoritative server Phase-C timing.
The latter and host/resource observations are retained by the qualification run.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .canonical import digest, integer, require, text
from .operational import pair_key

SCHEMA = "mavi-s2c-e2-runner-evidence-v1"


class _MeasuredApi:
    def __init__(self, api):
        self.api = api
        self.calls: list[dict] = []

    async def _call(self, name, *args):
        started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        tick = time.perf_counter_ns()
        outcome = "returned"
        try:
            return await getattr(self.api, name)(*args)
        except Exception:
            outcome = "raised"
            raise
        finally:
            # Do not retain tokens, crop bytes, scores or free-form error messages.
            self.calls.append({"operation": name, "startedAtUtc": started,
                "finishedAtUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "durationUs": (time.perf_counter_ns()-tick)//1000, "outcome": outcome})

    async def lease(self): return await self._call("lease")
    async def heartbeat(self, leased): return await self._call("heartbeat", leased)
    async def fail(self, leased, code, message): return await self._call("fail", leased, code, message)
    async def read_evidence(self, leased, observation): return await self._call("read_evidence", leased, observation)
    async def upload(self, leased, content): return await self._call("upload", leased, content)
    async def complete(self, leased, body): return await self._call("complete", leased, body)


async def measure_attempts(api, *, pair: dict, identity_sha256: str, worker_id: str,
                           profile, inferencer, provenance: dict, heartbeat_interval_seconds: float,
                           request_timeout_seconds: float, maximum_attempts: int, api_mode: str) -> dict:
    """Bounded observation; caller supplies the actual frozen pair inferencer.

    Synthetic clients are explicitly test-only. Real measurements require the
    production AttributeApiClient and therefore traverse the platform API.
    Caller owns the client's lifetime; the runner's inference lane always closes.
    """
    from mavi_vision.attributes.client import AttributeApiClient
    from mavi_vision.attributes.runner import AttributeRunner

    pair_key(pair)
    digest(identity_sha256, "E2:runtime_identity")
    text(worker_id, "E2:worker_id")
    integer(maximum_attempts, "E2:maximum_attempts", 1)
    require(maximum_attempts <= 100_000, "E2:bounded_attempts")
    require(api_mode in ("real-platform", "synthetic-test"), "E2:api_mode")
    require(api_mode != "real-platform" or isinstance(api, AttributeApiClient), "E2:real_platform_client_required")
    measured = _MeasuredApi(api)
    runner = AttributeRunner(measured, worker_id=worker_id, profile=profile, inferencer=inferencer,
        provenance=provenance, heartbeat_interval_seconds=heartbeat_interval_seconds,
        request_timeout_seconds=request_timeout_seconds)
    attempts = []
    try:
        for _ in range(maximum_attempts):
            outcome = await runner.run_once()
            if outcome is None: break
            attempts.append({"status": outcome.status, "failureCode": outcome.failure_code})
    finally:
        runner.close()
    return {"schema": SCHEMA, "apiMode": api_mode, "pair": pair, "identitySha256": identity_sha256,
            "workerId": worker_id, "attempts": attempts, "calls": measured.calls}
