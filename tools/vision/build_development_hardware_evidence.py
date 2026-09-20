#!/usr/bin/env python3
"""Assemble the Development CUDA hardware qualification evidence bundle.

ADR-009 separates Development hardware qualification from Production. The
`qualified-development-hardware` runtime state is what a real run on controlled
Development hardware produces, and `developmentEvidence` is the record that
backs it. The whole separation is worth nothing if that record can be written
from a build that never touched a GPU.

What this tool can and cannot prove is worth stating plainly, because an
overstated property is worse than an unstated one. Every producer in this set
runs offline on the operator's own machine, with no signing root, so nothing
here proves an artefact was not hand-written: the identity digest the run must
match is present in the sanitised host observation the operator holds. What the
tool does prove is that the three artefacts are one **consistent set, produced
in order, and not detachable from the record that summarises them** -- a stale,
borrowed or internally contradictory set is refused.

So it assembles the bundle only from artefacts that corroborate each other, and
refuses on anything it cannot check:

- the host observation says which physical GPU is present;
- the toolchain observation says the native build toolchain was verified;
- the runtime verification says CUDA code actually executed on that GPU.

The third is not optional. A successful wheel build proves the ops compiled,
not that they ran. Without on-device execution there is no Development hardware
qualification to claim, and this tool will not manufacture one.

Corroboration means the artefacts are required to agree with each other, not
merely to exist: the run and the host observation must name the same physical
card by its domain-salted identity digest and agree on its memory, and the
toolchain observation must name the same source revision and the same target
architecture. Anything the record asserts that another artefact also states is
checked against it, so the operator's word is never the only source for it.

The output carries `variantPatch`, the complete `qualified-development-hardware`
platform-variant entry, because ADR-009 requires a resolved-config, Python and
binary identity alongside the evidence block and hand-typing those at the last
step would reintroduce exactly the fabrication this tool exists to prevent.

It is offline and reads only the files it is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_VERSION = "mavi-windows-cuda-development-evidence-v2"

_HOST_SCHEMA = "mavi-windows-cuda-host-observation-v2"
_TOOLCHAIN_SCHEMA = "mavi-windows-cuda-toolchain-observation-v1"
_RUNTIME_SCHEMA = "mavi-windows-cuda-runtime-verification-v2"

_SOURCE_HEAD_SHA = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CANONICAL_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", re.ASCII)
_COMPUTE_CAPABILITY = re.compile(r"^\d+\.\d+$", re.ASCII)
_OPERATOR_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@/-]{0,127}$", re.ASCII)
_MEMORY_TOLERANCE_BYTES = 64 * 1024 * 1024
_SCHEMA_DIR = Path(__file__).resolve().parent
_HOST_OBSERVATION_SCHEMA_PATH = (
    _SCHEMA_DIR / "windows-cuda-host-observation.schema.json"
)
_TOOLCHAIN_SCHEMA_PATH = (
    _SCHEMA_DIR / "windows-cuda-toolchain-observation.schema.json"
)
_RUNTIME_SCHEMA_PATH = (
    _SCHEMA_DIR / "windows-cuda-runtime-verification.schema.json"
)


def _published_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class DevelopmentEvidenceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    # ensure_ascii=False so the documented recomputation recipe -- blank the
    # field, re-serialise canonically as UTF-8, hash -- is exact for a record
    # carrying a non-ASCII device name.
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _required_text(value: object, code: str) -> str:
    """Read one identity field, refusing anything that is not stated text.

    Every producer in this set always emits these fields, so an artefact
    missing one was not produced by that tool. Copying a null or a nested
    object through into the record would state an identity nobody observed.
    """
    if not isinstance(value, str) or not value.strip():
        raise DevelopmentEvidenceError(code)
    return value


def _required_digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DevelopmentEvidenceError(code)
    return value


def _required_index(value: object, expected: int, code: str) -> int:
    # bool is an int in Python, so True would compare equal to 1.
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise DevelopmentEvidenceError(code)
    return value


def _load(
    path: Path,
    schema: str,
    code: str,
    json_schema: dict | None = None,
) -> tuple[dict, str]:
    """Load one evidence artefact and return it with the SHA-256 of its bytes."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DevelopmentEvidenceError(code + "_unreadable") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DevelopmentEvidenceError(code + "_invalid") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != schema:
        raise DevelopmentEvidenceError(code + "_schema_invalid")
    if json_schema is not None:
        # The published schema closes `additionalProperties`, which is what
        # actually keeps a raw UUID -- or anything else workstation-specific --
        # out of a record this tool is about to digest and vouch for. A
        # hand-rolled key check only ever knows about the keys it was told.
        try:
            Draft202012Validator(json_schema).validate(value)
        except Exception as exc:
            raise DevelopmentEvidenceError(code + "_schema_invalid") from exc
    return value, _sha256_bytes(raw)


def _selected_gpu(host: dict, *, uuid_digest: str) -> dict:
    """Find the observed GPU the run names, by its identity digest.

    Nothing softer will do. The host observation lists GPUs in nvidia-smi order
    and the run reports a CUDA ordinal, which are not the same enumeration, so
    position may not answer which card ran the work. The device name is no
    better: `gpu_identity.py` deliberately binds on UUID, capability and memory
    and carries the name only as a label, because the name is a marketing string
    that two tools may spell differently for the same card.

    The digest is domain-salted (see host_gpu_digest), so an inventory entry and
    a run entry can only agree when both were computed from the same raw UUID on
    the same machine.
    """
    nvidia = host.get("nvidia")
    if not isinstance(nvidia, dict):
        raise DevelopmentEvidenceError("development_evidence_host_gpu_missing")
    gpus = nvidia.get("gpus")
    if not isinstance(gpus, list) or not gpus:
        raise DevelopmentEvidenceError("development_evidence_host_gpu_missing")
    if not all(isinstance(gpu, dict) for gpu in gpus):
        raise DevelopmentEvidenceError("development_evidence_host_gpu_missing")

    # The observation must have been sanitised before it could be shown to
    # anyone, and the digest it carries names a file that may never leave the
    # workstation if the raw UUID is still in it.
    if any("uuid" in gpu for gpu in gpus):
        raise DevelopmentEvidenceError(
            "development_evidence_host_observation_unsanitized"
        )

    matches = [
        gpu
        for gpu in gpus
        if gpu.get("uuidSha256") == uuid_digest
    ]
    if not matches:
        # The run and the observation do not describe the same physical device.
        raise DevelopmentEvidenceError("development_evidence_gpu_mismatch")
    if len(matches) > 1:
        # One physical card cannot appear twice in its own inventory.
        raise DevelopmentEvidenceError("development_evidence_gpu_ambiguous")
    return matches[0]


def _runtime_python_identity(runtime: dict) -> dict[str, object]:
    value = runtime.get("pythonIdentity")
    if not isinstance(value, dict):
        raise DevelopmentEvidenceError("development_evidence_python_identity_missing")
    identity: dict[str, object] = {
        key: _required_text(
            value.get(key), "development_evidence_python_identity_missing"
        )
        for key in ("version", "implementation", "compiler")
    }
    build = value.get("build")
    if (
        not isinstance(build, list)
        or len(build) != 2
        or any(not isinstance(part, str) or not part.strip() for part in build)
    ):
        raise DevelopmentEvidenceError("development_evidence_python_identity_missing")
    identity["build"] = list(build)
    return identity


def _runtime_binary_versions(runtime: dict) -> dict[str, str]:
    value = runtime.get("binaryVersions")
    if not isinstance(value, dict):
        raise DevelopmentEvidenceError("development_evidence_binary_versions_missing")
    versions = {
        key: _required_text(
            value.get(key), "development_evidence_binary_versions_missing"
        )
        for key in ("torch", "torchvision")
    }
    for version in versions.values():
        # A CUDA build identity is the local version; a bare 2.6.0 is a
        # different artefact from 2.6.0+cu124 and must not pass for one.
        if "+" not in version:
            raise DevelopmentEvidenceError(
                "development_evidence_binary_build_identity_missing"
            )
    return versions


def build_evidence(
    *,
    host_observation: Path,
    toolchain_observation: Path,
    runtime_verification: Path,
    source_head_sha: str,
    captured_at_utc: str,
    operator_reference: str,
    device_index: int = 0,
) -> dict[str, object]:
    if _SOURCE_HEAD_SHA.fullmatch(source_head_sha) is None:
        raise DevelopmentEvidenceError("development_evidence_source_head_sha_invalid")
    if _CANONICAL_UTC.fullmatch(captured_at_utc) is None:
        raise DevelopmentEvidenceError("development_evidence_captured_at_invalid")
    if _OPERATOR_REFERENCE.fullmatch(operator_reference) is None:
        raise DevelopmentEvidenceError("development_evidence_operator_invalid")

    host, host_sha = _load(
        host_observation,
        _HOST_SCHEMA,
        "development_evidence_host_observation",
        _published_schema(_HOST_OBSERVATION_SCHEMA_PATH),
    )
    toolchain, toolchain_sha = _load(
        toolchain_observation,
        _TOOLCHAIN_SCHEMA,
        "development_evidence_toolchain",
        _published_schema(_TOOLCHAIN_SCHEMA_PATH),
    )
    runtime, runtime_sha = _load(
        runtime_verification,
        _RUNTIME_SCHEMA,
        "development_evidence_runtime",
        _published_schema(_RUNTIME_SCHEMA_PATH),
    )

    if toolchain.get("status") != "passed":
        raise DevelopmentEvidenceError("development_evidence_toolchain_not_passed")
    if runtime.get("result") != "passed":
        raise DevelopmentEvidenceError("development_evidence_runtime_not_passed")

    # On-device execution is the claim. A build that compiled is not a run.
    if runtime.get("mmcvNmsExecutedOnCuda") is not True:
        raise DevelopmentEvidenceError("development_evidence_native_ops_not_executed")
    if runtime.get("torchMatmulExecutedOnCuda") is not True:
        raise DevelopmentEvidenceError("development_evidence_torch_not_executed")

    _required_index(
        runtime.get("deviceIndex"),
        device_index,
        "development_evidence_device_index_mismatch",
    )

    runtime_capability = _required_text(
        runtime.get("computeCapability"),
        "development_evidence_runtime_capability_invalid",
    )
    if _COMPUTE_CAPABILITY.fullmatch(runtime_capability) is None:
        raise DevelopmentEvidenceError("development_evidence_runtime_capability_invalid")
    runtime_name = _required_text(
        runtime.get("deviceName"),
        "development_evidence_runtime_device_unnamed",
    ).strip()
    uuid_digest = _required_digest(
        runtime.get("gpuUuidSha256"),
        "development_evidence_gpu_identity_missing",
    )

    gpu = _selected_gpu(host, uuid_digest=uuid_digest)
    if _required_digest(
        gpu.get("uuidSha256"), "development_evidence_gpu_identity_missing"
    ) != uuid_digest:
        raise DevelopmentEvidenceError("development_evidence_gpu_mismatch")
    host_capability = _required_text(
        gpu.get("computeCapability"),
        "development_evidence_host_capability_invalid",
    )
    if _COMPUTE_CAPABILITY.fullmatch(host_capability) is None:
        raise DevelopmentEvidenceError("development_evidence_host_capability_invalid")
    if host_capability != runtime_capability:
        raise DevelopmentEvidenceError("development_evidence_gpu_mismatch")

    # A second, independent reading of the same card, on the tolerance
    # gpu_identity.py already uses for the reserved-memory difference.
    host_memory = gpu.get("memoryMiB")
    if not isinstance(host_memory, dict) or not isinstance(
        host_memory.get("total"), int
    ):
        raise DevelopmentEvidenceError("development_evidence_host_memory_missing")
    runtime_memory = runtime.get("totalMemoryBytes")
    if not isinstance(runtime_memory, int) or isinstance(runtime_memory, bool):
        raise DevelopmentEvidenceError("development_evidence_runtime_memory_missing")
    if (
        abs(runtime_memory - host_memory["total"] * 1024 * 1024)
        > _MEMORY_TOLERANCE_BYTES
    ):
        raise DevelopmentEvidenceError("development_evidence_gpu_memory_mismatch")

    # The run must name the observation it was produced against, so a record
    # cannot be paired with a different or later inventory of the same host.
    if _required_digest(
        runtime.get("hostObservationSha256"),
        "development_evidence_host_observation_unchained",
    ) != host_sha:
        raise DevelopmentEvidenceError(
            "development_evidence_host_observation_mismatch"
        )

    # Both readings of the driver come from nvidia-smi on the one host.
    if _required_text(
        gpu.get("driverVersion"), "development_evidence_host_driver_missing"
    ) != _required_text(
        runtime.get("driverVersion"),
        "development_evidence_runtime_identity_missing",
    ):
        raise DevelopmentEvidenceError("development_evidence_driver_mismatch")

    declared_count = host["nvidia"].get("gpuCount")
    if declared_count != len(host["nvidia"]["gpus"]):
        raise DevelopmentEvidenceError("development_evidence_gpu_count_mismatch")

    # Work was done on the device, so the allocator must have seen it. Zero
    # peak allocation alongside a claim of on-device execution is a
    # contradiction, not a rounding artefact.
    allocated = runtime.get("peakMemoryAllocatedBytes")
    reserved = runtime.get("peakMemoryReservedBytes")
    if (
        not isinstance(allocated, int)
        or isinstance(allocated, bool)
        or allocated <= 0
    ):
        raise DevelopmentEvidenceError(
            "development_evidence_no_device_allocation"
        )
    if (
        not isinstance(reserved, int)
        or isinstance(reserved, bool)
        or reserved < allocated
    ):
        raise DevelopmentEvidenceError(
            "development_evidence_device_allocation_invalid"
        )

    architecture = f"sm_{host_capability.replace('.', '')}"
    arch_list = runtime.get("torchCudaArchList")
    if not isinstance(arch_list, list) or architecture not in arch_list:
        # Without kernels for this architecture the run relied on PTX JIT, which
        # is not the artefact being qualified.
        raise DevelopmentEvidenceError(
            "development_evidence_architecture_not_in_torch_build"
        )

    # The toolchain artefact states the revision and the architecture it built
    # for. Both are asserted elsewhere in this record, so leaving them
    # uncompared would make the operator's word the only source for either.
    toolchain_head = _required_text(
        toolchain.get("sourceHeadSha"),
        "development_evidence_toolchain_source_head_missing",
    )
    if toolchain_head != source_head_sha:
        raise DevelopmentEvidenceError(
            "development_evidence_source_revision_mismatch"
        )
    toolchain_architecture = _required_text(
        toolchain.get("targetArchitecture"),
        "development_evidence_toolchain_architecture_missing",
    )
    if toolchain_architecture.replace("_", "") != architecture.replace("_", ""):
        raise DevelopmentEvidenceError(
            "development_evidence_toolchain_architecture_mismatch"
        )

    corroboration = {
        "toolchainObservationSha256": toolchain_sha,
        "runtimeVerificationSha256": runtime_sha,
        "gpuUuidSha256": uuid_digest,
        "gpuName": runtime_name,
        "hostGpuName": _required_text(
            gpu.get("name"), "development_evidence_host_gpu_unnamed"
        ).strip(),
        "computeCapability": host_capability,
        "targetArchitecture": architecture,
        "deviceIndex": device_index,
        "hostGpuCount": len(host["nvidia"]["gpus"]),
        "driverVersion": _required_text(
            runtime.get("driverVersion"),
            "development_evidence_runtime_identity_missing",
        ),
        "torchCudaRuntimeVersion": _required_text(
            runtime.get("torchCudaRuntimeVersion"),
            "development_evidence_runtime_identity_missing",
        ),
        "msvcToolset": _required_text(
            toolchain.get("vcToolsVersion"),
            "development_evidence_toolchain_identity_missing",
        ),
        "windowsSdkVersion": _required_text(
            toolchain.get("windowsSdkVersion"),
            "development_evidence_toolchain_identity_missing",
        ),
        "cudaToolkitVersion": _required_text(
            toolchain.get("cudaToolkitVersion"),
            "development_evidence_toolchain_identity_missing",
        ),
    }

    # The complete platform-variant entry, machine-generated. ADR-009 requires
    # the resolved-config, Python and binary identities alongside the evidence
    # block; typing those in by hand at the last step would reintroduce exactly
    # the fabrication this tool exists to prevent.
    binary_versions = _runtime_binary_versions(runtime)
    if _required_text(
        runtime.get("torchVersion"),
        "development_evidence_runtime_identity_missing",
    ) != binary_versions["torch"]:
        raise DevelopmentEvidenceError("development_evidence_torch_version_mismatch")

    variant_patch = {
        "status": "qualified-development-hardware",
        "resolvedConfigSha256": _required_digest(
            runtime.get("resolvedConfigSha256"),
            "development_evidence_resolved_config_missing",
        ),
        "pythonIdentity": _runtime_python_identity(runtime),
        "binaryVersions": binary_versions,
    }

    evidence: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "developmentEvidence": {
            "hostObservationSha256": host_sha,
            "evidenceBundleSha256": "",
            "sourceHeadSha": source_head_sha,
            "capturedAtUtc": captured_at_utc,
            "operatorReference": operator_reference,
        },
        "variantPatch": variant_patch,
        "corroboration": corroboration,
        "note": (
            "Development hardware evidence for ADR-009. This supports the "
            "qualified-development-hardware runtime state only. It is not, and "
            "may not be promoted to, Production qualification: Production "
            "requires qualified-hardware with its own independent evidence."
        ),
    }

    # The digest covers this whole record with the digest field itself blank,
    # so an auditor holding only the file can recompute it: blank the field,
    # re-serialise canonically, hash. It therefore binds the source artefacts,
    # the revision, the capture time and the operator together, and the record
    # cannot be detached from the evidence it summarises.
    evidence["developmentEvidence"]["evidenceBundleSha256"] = _sha256_bytes(  # type: ignore[index]
        _canonical(evidence)
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host-observation", type=Path, required=True)
    parser.add_argument("--toolchain-observation", type=Path, required=True)
    parser.add_argument("--runtime-verification", type=Path, required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--captured-at-utc", required=True)
    parser.add_argument("--operator-reference", required=True)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        evidence = build_evidence(
            host_observation=args.host_observation,
            toolchain_observation=args.toolchain_observation,
            runtime_verification=args.runtime_verification,
            source_head_sha=args.source_head_sha,
            captured_at_utc=args.captured_at_utc,
            operator_reference=args.operator_reference,
            device_index=args.device_index,
        )
    except DevelopmentEvidenceError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2

    if args.output is not None:
        if args.output.exists():
            print(
                json.dumps(
                    {"ok": False, "code": "development_evidence_output_exists"},
                    sort_keys=True,
                )
            )
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps({"ok": True, "evidence": evidence}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
