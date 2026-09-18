#!/usr/bin/env python3
"""Positive CUDA runtime/native-op verification for C4/C6 evidence.

This runs on the controlled Windows host and is the only artefact in the C4 set
that can attest a GPU actually executed anything. That makes it the artefact
worth forging, so it states which physical card it ran on rather than only that
some card did: the record carries the same domain-salted GPU identity digest the
host observation carries, so the two can be required to agree.

It also carries the runtime identity ADR-009 requires of a Development
qualification -- exact Python identity, exact Torch and torchvision build
identities, exact resolved-config SHA-256 -- because those fields describe the
run and should not be typed in afterwards by hand.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

for _candidate in (
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[2] / "src" / "vision",
):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from host_gpu_digest import gpu_uuid_digest  # noqa: E402

SCHEMA_VERSION = "mavi-windows-cuda-runtime-verification-v2"


class CudaRuntimeVerificationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compose_record(
    *,
    device_index: int,
    device_name: str,
    compute_capability: str,
    gpu_uuid: str,
    driver_version: str,
    torch_version: str,
    torchvision_version: str,
    torch_cuda_runtime_version: str,
    torch_cuda_arch_list: list[str],
    total_memory_bytes: int,
    peak_memory_allocated_bytes: int,
    peak_memory_reserved_bytes: int,
    resolved_config_sha256: str,
) -> dict[str, object]:
    """Assemble the verification record from values the run observed.

    Kept separate from the run itself so the record's shape can be exercised
    without a GPU; the booleans below are set by the caller only after the
    operators have executed on the device.
    """
    return {
        "schemaVersion": SCHEMA_VERSION,
        "deviceIndex": device_index,
        "deviceName": device_name,
        "computeCapability": compute_capability,
        # The raw UUID never enters the record; the digest is what correlates
        # this run with the host observation of the same card.
        "gpuUuidSha256": gpu_uuid_digest(gpu_uuid),
        "driverVersion": driver_version,
        "pythonIdentity": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "build": list(platform.python_build()),
            "compiler": platform.python_compiler(),
        },
        "binaryVersions": {
            "torch": torch_version,
            "torchvision": torchvision_version,
        },
        "resolvedConfigSha256": resolved_config_sha256,
        "torchVersion": torch_version,
        "torchCudaRuntimeVersion": torch_cuda_runtime_version,
        "torchCudaArchList": torch_cuda_arch_list,
        "totalMemoryBytes": total_memory_bytes,
        "peakMemoryAllocatedBytes": peak_memory_allocated_bytes,
        "peakMemoryReservedBytes": peak_memory_reserved_bytes,
        "mmcvNmsExecutedOnCuda": True,
        "torchMatmulExecutedOnCuda": True,
        "result": "passed",
    }


def verify(device_index: int, resolved_config: Path) -> dict[str, object]:
    if os.environ.get("CUDA_DEVICE_ORDER") != "PCI_BUS_ID":
        raise CudaRuntimeVerificationError(
            "cuda_device_order_not_pci_bus_id"
        )
    if not resolved_config.is_file():
        raise CudaRuntimeVerificationError(
            "cuda_runtime_resolved_config_missing"
        )

    import torch
    import torchvision
    from mmcv.ops import nms

    from mavi_vision.runtime.gpu_identity import (
        GpuIdentityProbeError,
        capture_gpu_identity,
    )

    if not torch.cuda.is_available():
        raise CudaRuntimeVerificationError("cuda_unavailable")
    if device_index < 0 or device_index >= torch.cuda.device_count():
        raise CudaRuntimeVerificationError("cuda_device_index_invalid")

    device = torch.device(f"cuda:{device_index}")
    props = torch.cuda.get_device_properties(device_index)
    capability = f"{props.major}.{props.minor}"
    arch = f"sm_{props.major}{props.minor}"
    arch_list = list(torch.cuda.get_arch_list())
    if arch not in arch_list:
        raise CudaRuntimeVerificationError(
            "torch_cuda_architecture_missing"
        )

    # Which physical card this ordinal names is resolved by the runtime's own
    # audited binding, never by assuming the CUDA and nvidia-smi orders agree.
    try:
        identity = capture_gpu_identity(f"cuda:{device_index}")
    except GpuIdentityProbeError as exc:
        raise CudaRuntimeVerificationError(exc.code) from exc

    torch.cuda.reset_peak_memory_stats(device)
    boxes = torch.tensor(
        [[0.0, 0.0, 10.0, 10.0], [1.0, 1.0, 11.0, 11.0]],
        dtype=torch.float32,
        device=device,
    )
    scores = torch.tensor(
        [0.9, 0.8],
        dtype=torch.float32,
        device=device,
    )
    dets, keep = nms(boxes, scores, 0.5)
    if not dets.is_cuda or not keep.is_cuda:
        raise CudaRuntimeVerificationError(
            "mmcv_cuda_op_executed_off_device"
        )

    matmul = torch.ones((64, 64), device=device) @ torch.ones(
        (64, 64),
        device=device,
    )
    if not matmul.is_cuda:
        raise CudaRuntimeVerificationError(
            "torch_cuda_matmul_executed_off_device"
        )
    torch.cuda.synchronize(device)

    return compose_record(
        device_index=device_index,
        device_name=str(props.name),
        compute_capability=capability,
        gpu_uuid=identity.uuid,
        driver_version=identity.driver_version,
        torch_version=torch.__version__,
        torchvision_version=torchvision.__version__,
        torch_cuda_runtime_version=torch.version.cuda,
        torch_cuda_arch_list=arch_list,
        total_memory_bytes=int(props.total_memory),
        peak_memory_allocated_bytes=int(
            torch.cuda.max_memory_allocated(device)
        ),
        peak_memory_reserved_bytes=int(
            torch.cuda.max_memory_reserved(device)
        ),
        resolved_config_sha256=_sha256_file(resolved_config),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--resolved-config", type=Path, required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        value = verify(args.device_index, args.resolved_config)
    except Exception as exc:
        code = (
            exc.code
            if isinstance(exc, CudaRuntimeVerificationError)
            else "cuda_runtime_verification_failed"
        )
        print(json.dumps({"ok": False, "code": code}, sort_keys=True))
        return 2
    if args.output:
        path = Path(args.output)
        if path.exists():
            print(
                json.dumps(
                    {"ok": False, "code": "cuda_runtime_verification_output_exists"},
                    sort_keys=True,
                )
            )
            return 2
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps({"ok": True, "verification": value}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
