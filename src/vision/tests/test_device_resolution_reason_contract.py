"""The device-resolution reason contract must mean the same thing everywhere.

JSON Schema, Pydantic and .NET each carry a mirror of one closed vocabulary and
one set of payload-provable relationships. These tests bind the mirrors to each
other and assert that the two Python-reachable representations accept exactly
the same payloads, so a rule added to one and forgotten in another fails here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from mavi_vision.common.control_plane import (
    AUTO_CPU_DEVICE_RESOLUTION_REASONS,
    AUTO_CUDA_DEVICE_RESOLUTION_REASONS,
    DEVICE_RESOLUTION_REASONS,
    EXPLICIT_DEVICE_RESOLUTION_REASONS,
    VisionJobComplete,
)


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-complete-v2.example.json"
SCHEMA_PATH = ROOT / "contracts/schemas/vision-job-complete-v2.schema.json"
PARSER_PATH = (
    ROOT
    / "src/platform/Mavi.Application/Modules/Intelligence"
    / "VisionRuntimeProvenanceParser.cs"
)

_GPU = {
    "name": "NVIDIA GeForce GTX 1650 Ti",
    "index": 0,
    "vramBytes": 4294967296,
    "driverVersion": "576.83",
    "cudaRuntimeVersion": "12.4",
    "uuid": "GPU-aaaa",
    "pciBusId": "00000000:01:00.0",
    "computeCapability": "7.5",
}

_OMITTED = object()


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _schema_reason_enum() -> set[str]:
    reason = _schema()["$defs"]["provenance"]["properties"][
        "deviceResolutionReason"
    ]
    for branch in reason["anyOf"]:
        if branch.get("type") == "string":
            return set(branch["enum"])
    raise AssertionError("deviceResolutionReason declares no string branch")


def _csharp_reason_set(name: str) -> set[str]:
    text = PARSER_PATH.read_text(encoding="utf-8")
    match = re.search(
        rf"HashSet<string> {name} =\s*\[(?P<body>.*?)\];",
        text,
        re.DOTALL,
    )
    assert match is not None, f"{name} not found in the .NET parser"
    return set(re.findall(r'"([a-z0-9_]+)"', match.group("body")))


def _payload(
    *,
    policy: str,
    reason: object,
    device: str = "cpu",
    gpu: bool = False,
) -> dict:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    provenance = payload["provenance"]
    provenance["configuredDevicePolicy"] = policy
    provenance["actualDevice"] = device
    if reason is _OMITTED:
        provenance.pop("deviceResolutionReason", None)
    else:
        provenance["deviceResolutionReason"] = reason
    if gpu:
        provenance["gpu"] = dict(_GPU)
    else:
        provenance.pop("gpu", None)
    return payload


def _schema_accepts(payload: dict) -> bool:
    try:
        jsonschema.validate(payload, _schema())
    except jsonschema.ValidationError:
        return False
    return True


def _pydantic_accepts(payload: dict) -> bool:
    try:
        VisionJobComplete.model_validate_json(json.dumps(payload))
    except ValidationError:
        return False
    return True


def test_published_schema_enum_matches_the_authoritative_vocabulary() -> None:
    assert _schema_reason_enum() == set(DEVICE_RESOLUTION_REASONS)


def test_dotnet_parser_vocabulary_matches_the_authoritative_vocabulary() -> None:
    explicit = set(
        re.findall(
            r'private const string Explicit\w*DeviceResolutionReason = "([a-z_]+)"',
            PARSER_PATH.read_text(encoding="utf-8"),
        )
    )

    assert explicit == set(EXPLICIT_DEVICE_RESOLUTION_REASONS)
    assert _csharp_reason_set("AutoCudaDeviceResolutionReasons") == set(
        AUTO_CUDA_DEVICE_RESOLUTION_REASONS
    )
    assert _csharp_reason_set("AutoCpuDeviceResolutionReasons") == set(
        AUTO_CPU_DEVICE_RESOLUTION_REASONS
    )
    assert explicit | _csharp_reason_set(
        "AutoCudaDeviceResolutionReasons"
    ) | _csharp_reason_set("AutoCpuDeviceResolutionReasons") == set(
        DEVICE_RESOLUTION_REASONS
    )


def test_vocabulary_partitions_cleanly() -> None:
    assert not (
        AUTO_CUDA_DEVICE_RESOLUTION_REASONS & AUTO_CPU_DEVICE_RESOLUTION_REASONS
    )
    assert not (
        EXPLICIT_DEVICE_RESOLUTION_REASONS
        & (AUTO_CUDA_DEVICE_RESOLUTION_REASONS | AUTO_CPU_DEVICE_RESOLUTION_REASONS)
    )
    assert DEVICE_RESOLUTION_REASONS == (
        EXPLICIT_DEVICE_RESOLUTION_REASONS
        | AUTO_CUDA_DEVICE_RESOLUTION_REASONS
        | AUTO_CPU_DEVICE_RESOLUTION_REASONS
    )


_REJECTED = [
    pytest.param(
        dict(policy="cpu", reason="cuda_some_new_reason"),
        id="unknown-but-syntactically-valid-reason",
    ),
    pytest.param(
        dict(policy="auto", reason="explicit_auto"),
        id="explicit-prefix-outside-the-vocabulary",
    ),
    pytest.param(
        dict(policy="cuda", reason="explicit_cpu", device="cuda:0", gpu=True),
        id="explicit-cpu-under-cuda-policy",
    ),
    pytest.param(
        dict(policy="cpu", reason="explicit_cuda"),
        id="explicit-cuda-under-cpu-policy",
    ),
    pytest.param(
        dict(policy="auto", reason="explicit_cpu"),
        id="explicit-cpu-under-auto-policy",
    ),
    pytest.param(
        dict(policy="cpu", reason="cuda_selected"),
        id="auto-cuda-reason-with-cpu-execution",
    ),
    pytest.param(
        dict(policy="cuda", reason="cuda_pack_absent", device="cuda:0", gpu=True),
        id="auto-cpu-reason-with-cuda-execution",
    ),
    pytest.param(
        dict(policy="auto", reason=_OMITTED),
        id="auto-policy-omits-reason",
    ),
    pytest.param(
        dict(policy="auto", reason=None),
        id="auto-policy-nulls-reason",
    ),
]

_ACCEPTED = [
    pytest.param(
        dict(policy="cpu", reason="explicit_cpu"),
        id="explicit-cpu",
    ),
    pytest.param(
        dict(policy="cuda", reason="explicit_cuda", device="cuda:0", gpu=True),
        id="explicit-cuda",
    ),
    pytest.param(
        dict(policy="cuda", reason="cuda_selected", device="cuda:0", gpu=True),
        id="auto-resolved-to-cuda-by-the-launcher",
    ),
    pytest.param(
        dict(policy="cpu", reason="cuda_pack_absent"),
        id="auto-resolved-to-cpu-by-the-launcher",
    ),
    pytest.param(
        dict(policy="auto", reason="cuda_device_unavailable"),
        id="auto-policy-recording-its-cpu-fallback",
    ),
    pytest.param(
        dict(policy="auto", reason="cuda_selected", device="cuda:0", gpu=True),
        id="auto-policy-recording-its-cuda-selection",
    ),
    pytest.param(
        dict(policy="cpu", reason=_OMITTED),
        id="explicit-policy-may-omit-the-reason",
    ),
]


@pytest.mark.parametrize("case", _REJECTED)
def test_schema_and_pydantic_both_reject(case: dict) -> None:
    payload = _payload(**case)

    assert not _schema_accepts(payload)
    assert not _pydantic_accepts(payload)


@pytest.mark.parametrize("case", _ACCEPTED)
def test_schema_and_pydantic_both_accept(case: dict) -> None:
    payload = _payload(**case)

    assert _schema_accepts(payload)
    assert _pydantic_accepts(payload)


@pytest.mark.parametrize(
    "reason",
    sorted(AUTO_CPU_DEVICE_RESOLUTION_REASONS),
)
def test_every_auto_cpu_reason_requires_cpu_execution(reason: str) -> None:
    cuda = _payload(policy="cuda", reason=reason, device="cuda:0", gpu=True)
    cpu = _payload(policy="cpu", reason=reason)

    assert not _schema_accepts(cuda)
    assert not _pydantic_accepts(cuda)
    assert _schema_accepts(cpu)
    assert _pydantic_accepts(cpu)


@pytest.mark.parametrize(
    "reason",
    sorted(AUTO_CUDA_DEVICE_RESOLUTION_REASONS),
)
def test_every_auto_cuda_reason_requires_cuda_execution(reason: str) -> None:
    cpu = _payload(policy="cpu", reason=reason)
    cuda = _payload(policy="cuda", reason=reason, device="cuda:0", gpu=True)

    assert not _schema_accepts(cpu)
    assert not _pydantic_accepts(cpu)
    assert _schema_accepts(cuda)
    assert _pydantic_accepts(cuda)


def test_cuda_ordinal_syntax_agrees_between_schema_and_pydantic() -> None:
    """The auto-CUDA conditional must not narrow the accepted device syntax."""
    for device in ("cuda:0", "cuda:7", "cuda:00"):
        payload = _payload(
            policy="cuda",
            reason="cuda_selected",
            device=device,
            gpu=True,
        )
        assert _schema_accepts(payload) == _pydantic_accepts(payload), device
