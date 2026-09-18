from __future__ import annotations

import csv
import io
import re
import subprocess
from collections.abc import Sequence

from mavi_vision.runtime.provenance import GpuIdentity


class GpuIdentityProbeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise GpuIdentityProbeError(
            "nvidia_smi_not_found"
        ) from exc


def _parse_device_index(device: str) -> int:
    match = re.fullmatch(r"cuda:(\d+)", device)
    if match is None:
        raise GpuIdentityProbeError(
            "gpu_identity_device_invalid"
        )
    return int(match.group(1))


def capture_gpu_identity(device: str) -> GpuIdentity:
    """Capture the physical GPU backing one CUDA device.

    CUDA_DEVICE_ORDER=PCI_BUS_ID must be set before Python starts so the
    CUDA index used by torch and the nvidia-smi index share the same
    PCI-bus-stable ordering.
    """
    index = _parse_device_index(device)

    # Heavy framework import remains lazy so CPU startup stays lightweight.
    try:
        import torch
    except Exception as exc:
        raise GpuIdentityProbeError(
            "gpu_identity_torch_unavailable"
        ) from exc

    if not torch.cuda.is_available():
        raise GpuIdentityProbeError(
            "gpu_identity_cuda_unavailable"
        )
    if index >= torch.cuda.device_count():
        raise GpuIdentityProbeError(
            "gpu_identity_index_unavailable"
        )

    properties = torch.cuda.get_device_properties(index)
    runtime_version = getattr(torch.version, "cuda", None)
    if not isinstance(runtime_version, str) or not runtime_version:
        raise GpuIdentityProbeError(
            "gpu_identity_cuda_runtime_missing"
        )

    query = _run(
        (
            "nvidia-smi",
            "-i",
            str(index),
            "--query-gpu=uuid,pci.bus_id,driver_version,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        )
    )
    if query.returncode != 0:
        raise GpuIdentityProbeError(
            "gpu_identity_nvidia_smi_failed"
        )

    rows = list(csv.reader(io.StringIO(query.stdout)))
    if len(rows) != 1 or len(rows[0]) != 5:
        raise GpuIdentityProbeError(
            "gpu_identity_nvidia_smi_invalid"
        )
    uuid, pci_bus_id, driver, memory_mib, compute_capability = (
        field.strip() for field in rows[0]
    )
    if not all(
        value
        for value in (
            uuid,
            pci_bus_id,
            driver,
            compute_capability,
        )
    ):
        raise GpuIdentityProbeError(
            "gpu_identity_nvidia_smi_invalid"
        )
    if re.fullmatch(r"\d+\.\d+", compute_capability) is None:
        raise GpuIdentityProbeError(
            "gpu_identity_compute_capability_invalid"
        )
    try:
        nvidia_memory_bytes = int(memory_mib) * 1024 * 1024
    except ValueError as exc:
        raise GpuIdentityProbeError(
            "gpu_identity_memory_invalid"
        ) from exc

    torch_compute = (
        f"{int(properties.major)}.{int(properties.minor)}"
    )
    if torch_compute != compute_capability:
        raise GpuIdentityProbeError(
            "gpu_identity_compute_capability_mismatch"
        )

    torch_memory = int(properties.total_memory)
    tolerance = 64 * 1024 * 1024
    if abs(torch_memory - nvidia_memory_bytes) > tolerance:
        raise GpuIdentityProbeError(
            "gpu_identity_memory_mismatch"
        )

    return GpuIdentity(
        name=str(properties.name),
        index=index,
        vram_bytes=torch_memory,
        driver_version=driver,
        cuda_runtime_version=runtime_version,
        uuid=uuid,
        pci_bus_id=pci_bus_id,
        compute_capability=torch_compute,
    )


__all__ = [
    "GpuIdentityProbeError",
    "capture_gpu_identity",
]
