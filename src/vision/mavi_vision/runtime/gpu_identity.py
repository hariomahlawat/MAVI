from __future__ import annotations

import csv
import io
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from mavi_vision.runtime.provenance import GpuIdentity


class GpuIdentityProbeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_INVENTORY_FIELDS = (
    "index",
    "uuid",
    "pci.bus_id",
    "driver_version",
    "memory.total",
    "compute_cap",
)
_PCI_BUS_ID_PATTERN = re.compile(
    r"^([0-9A-Fa-f]{1,8}):([0-9A-Fa-f]{1,2}):([0-9A-Fa-f]{1,2})\.([0-9A-Fa-f]{1,2})$",
    re.ASCII,
)
_VISIBLE_DEVICE_UUID_PATTERN = re.compile(r"^GPU-[0-9A-Fa-f-]{8,}$", re.ASCII)
_COMPUTE_CAPABILITY_PATTERN = re.compile(r"^\d+\.\d+$", re.ASCII)
_MEMORY_TOLERANCE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _PhysicalGpu:
    """One physical GPU as the NVIDIA driver reports it."""

    smi_index: int
    uuid: str
    pci_bus_id: str
    driver_version: str
    memory_bytes: int
    compute_capability: str


def _run(
    args: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            env=None if env is None else dict(env),
        )
    except FileNotFoundError as exc:
        raise GpuIdentityProbeError("nvidia_smi_not_found") from exc
    except subprocess.TimeoutExpired as exc:
        raise GpuIdentityProbeError("nvidia_smi_timed_out") from exc


def _normalized_gpu_uuid(value: str) -> str:
    """Reduce a GPU UUID to its comparable lowercase hexadecimal digits."""
    return "".join(
        character
        for character in value.casefold()
        if character in "0123456789abcdef"
    )


def _pci_bus_sort_key(pci_bus_id: str) -> tuple[int, int, int, int]:
    """Order a PCI bus ID numerically, the way CUDA_DEVICE_ORDER=PCI_BUS_ID does."""
    match = _PCI_BUS_ID_PATTERN.fullmatch(pci_bus_id)
    if match is None:
        raise GpuIdentityProbeError("gpu_identity_pci_bus_id_invalid")
    return tuple(int(group, 16) for group in match.groups())  # type: ignore[return-value]


def _parse_device_index(device: str) -> int:
    match = re.fullmatch(r"cuda:(\d+)", device)
    if match is None:
        raise GpuIdentityProbeError("gpu_identity_device_invalid")
    return int(match.group(1))


def _physical_inventory() -> tuple[_PhysicalGpu, ...]:
    """Query every physical GPU the driver can see, independent of any mask.

    CUDA_VISIBLE_DEVICES is stripped from the probe environment so the inventory
    is always the complete physical set; whether NVML honours that variable
    varies by driver, and this mapping may not depend on it.
    """
    environment = {
        name: value
        for name, value in os.environ.items()
        if name != "CUDA_VISIBLE_DEVICES"
    }
    query = _run(
        (
            "nvidia-smi",
            f"--query-gpu={','.join(_INVENTORY_FIELDS)}",
            "--format=csv,noheader,nounits",
        ),
        env=environment,
    )
    if query.returncode != 0:
        raise GpuIdentityProbeError("gpu_identity_nvidia_smi_failed")

    devices: list[_PhysicalGpu] = []
    for row in csv.reader(io.StringIO(query.stdout)):
        if not row or not any(field.strip() for field in row):
            continue
        if len(row) != len(_INVENTORY_FIELDS):
            raise GpuIdentityProbeError("gpu_identity_nvidia_smi_invalid")
        index, uuid, pci_bus_id, driver, memory_mib, capability = (
            field.strip() for field in row
        )
        if not all((index, uuid, pci_bus_id, driver, capability)):
            raise GpuIdentityProbeError("gpu_identity_nvidia_smi_invalid")
        if _COMPUTE_CAPABILITY_PATTERN.fullmatch(capability) is None:
            raise GpuIdentityProbeError(
                "gpu_identity_compute_capability_invalid"
            )
        try:
            smi_index = int(index)
            memory_bytes = int(memory_mib) * 1024 * 1024
        except ValueError as exc:
            raise GpuIdentityProbeError(
                "gpu_identity_nvidia_smi_invalid"
            ) from exc
        # Reject the PCI syntax here so ordering can never fall back to a
        # coincidental string comparison.
        _pci_bus_sort_key(pci_bus_id)
        devices.append(
            _PhysicalGpu(
                smi_index=smi_index,
                uuid=uuid,
                pci_bus_id=pci_bus_id,
                driver_version=driver,
                memory_bytes=memory_bytes,
                compute_capability=capability,
            )
        )

    if not devices:
        raise GpuIdentityProbeError("gpu_identity_inventory_empty")
    if len({device.uuid for device in devices}) != len(devices):
        raise GpuIdentityProbeError("gpu_identity_nvidia_smi_invalid")
    return tuple(devices)


def _resolve_visible_entry(
    entry: str,
    inventory: Sequence[_PhysicalGpu],
    pci_ordered: Sequence[_PhysicalGpu],
) -> tuple[_PhysicalGpu, ...]:
    """Resolve one CUDA_VISIBLE_DEVICES entry to the GPU(s) it could name.

    A UUID entry names a physical GPU outright. A numeric entry does not: which
    enumeration its index counts against (the driver's own, or the PCI-bus order
    that CUDA_DEVICE_ORDER selects) is not something this code can prove, and
    the two disagree on hosts where the orders differ. Both readings are
    therefore returned when they disagree, for the caller to settle against an
    authoritative identity rather than a guess.
    """
    if _VISIBLE_DEVICE_UUID_PATTERN.fullmatch(entry):
        wanted = _normalized_gpu_uuid(entry)
        for device in inventory:
            if _normalized_gpu_uuid(device.uuid) == wanted:
                return (device,)
        raise GpuIdentityProbeError("gpu_identity_visible_devices_unresolved")

    if entry.isdigit():
        ordinal = int(entry)
        by_driver_index = next(
            (device for device in inventory if device.smi_index == ordinal),
            None,
        )
        by_pci_order = (
            pci_ordered[ordinal] if ordinal < len(pci_ordered) else None
        )
        candidates = tuple(
            device
            for device in (by_driver_index, by_pci_order)
            if device is not None
        )
        if not candidates:
            raise GpuIdentityProbeError(
                "gpu_identity_visible_devices_unresolved"
            )
        if len(candidates) == 2 and candidates[0].uuid == candidates[1].uuid:
            return (candidates[0],)
        return candidates

    # MIG partitions and other selector syntaxes do not name one whole physical
    # GPU, so there is no identity this function could honestly return.
    raise GpuIdentityProbeError("gpu_identity_visible_devices_unsupported")


def _resolve_cuda_ordinal(
    index: int,
    inventory: Sequence[_PhysicalGpu],
    *,
    device_count: int,
    torch_uuid: str | None,
) -> _PhysicalGpu:
    """Bind one CUDA ordinal to the physical GPU behind it, or fail closed.

    CUDA ordinals are never assumed to equal driver ordinals. Without a mask the
    order is the PCI-bus ordering that CUDA_DEVICE_ORDER=PCI_BUS_ID requires,
    which this function can prove from the queried inventory. With a mask the
    mask states the order, and any entry it cannot pin to a single physical GPU
    must be settled by the runtime's own device UUID.
    """
    if os.environ.get("CUDA_DEVICE_ORDER") != "PCI_BUS_ID":
        raise GpuIdentityProbeError("gpu_identity_device_order_unstable")

    pci_ordered = tuple(
        sorted(inventory, key=lambda item: _pci_bus_sort_key(item.pci_bus_id))
    )

    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is None:
        if len(pci_ordered) != device_count:
            # Our reconstruction of the CUDA ordinal space disagrees with the
            # runtime's, so no ordinal in it can be trusted to name a GPU.
            raise GpuIdentityProbeError("gpu_identity_device_count_mismatch")
        return pci_ordered[index]

    entries = [entry.strip() for entry in visible.split(",") if entry.strip()]
    if not entries:
        # An empty mask hides every GPU; no CUDA device can have executed.
        raise GpuIdentityProbeError("gpu_identity_visible_devices_empty")
    if len(entries) != device_count:
        raise GpuIdentityProbeError("gpu_identity_device_count_mismatch")

    resolved = [
        _resolve_visible_entry(entry, inventory, pci_ordered)
        for entry in entries
    ]

    identities = [
        candidates[0].uuid for candidates in resolved if len(candidates) == 1
    ]
    if len(set(identities)) != len(identities):
        # The same physical GPU twice makes the ordinal mapping ambiguous.
        raise GpuIdentityProbeError("gpu_identity_visible_devices_duplicate")

    candidates = resolved[index]
    if len(candidates) == 1:
        return candidates[0]

    if torch_uuid is None:
        raise GpuIdentityProbeError("gpu_identity_visible_devices_ambiguous")
    wanted = _normalized_gpu_uuid(torch_uuid)
    for candidate in candidates:
        if _normalized_gpu_uuid(candidate.uuid) == wanted:
            return candidate
    raise GpuIdentityProbeError("gpu_identity_visible_devices_ambiguous")


def capture_gpu_identity(device: str) -> GpuIdentity:
    """Capture the physical GPU backing one CUDA device.

    The CUDA ordinal is bound to a physical GPU through the driver's own
    inventory of UUIDs and PCI bus IDs, never through an assumed ordinal
    coincidence between the CUDA runtime and nvidia-smi. Every step that cannot
    be proven fails closed, because the purpose of this record is to state
    which physical GPU produced a result.
    """
    index = _parse_device_index(device)

    # Heavy framework import remains lazy so CPU startup stays lightweight.
    try:
        import torch
    except Exception as exc:
        raise GpuIdentityProbeError("gpu_identity_torch_unavailable") from exc

    if not torch.cuda.is_available():
        raise GpuIdentityProbeError("gpu_identity_cuda_unavailable")
    device_count = int(torch.cuda.device_count())
    if index >= device_count:
        raise GpuIdentityProbeError("gpu_identity_index_unavailable")

    runtime_version = getattr(torch.version, "cuda", None)
    if not isinstance(runtime_version, str) or not runtime_version:
        raise GpuIdentityProbeError("gpu_identity_cuda_runtime_missing")

    properties = torch.cuda.get_device_properties(index)
    torch_uuid = getattr(properties, "uuid", None)
    torch_uuid = None if torch_uuid is None else str(torch_uuid)

    physical = _resolve_cuda_ordinal(
        index,
        _physical_inventory(),
        device_count=device_count,
        torch_uuid=torch_uuid,
    )

    torch_compute = f"{int(properties.major)}.{int(properties.minor)}"
    if torch_compute != physical.compute_capability:
        raise GpuIdentityProbeError(
            "gpu_identity_compute_capability_mismatch"
        )

    if torch_uuid is not None and _normalized_gpu_uuid(
        torch_uuid
    ) != _normalized_gpu_uuid(physical.uuid):
        raise GpuIdentityProbeError("gpu_identity_uuid_mismatch")

    torch_memory = int(properties.total_memory)
    if abs(torch_memory - physical.memory_bytes) > _MEMORY_TOLERANCE_BYTES:
        raise GpuIdentityProbeError("gpu_identity_memory_mismatch")

    return GpuIdentity(
        name=str(properties.name),
        index=index,
        vram_bytes=torch_memory,
        driver_version=physical.driver_version,
        cuda_runtime_version=runtime_version,
        uuid=physical.uuid,
        pci_bus_id=physical.pci_bus_id,
        compute_capability=torch_compute,
    )


__all__ = [
    "GpuIdentityProbeError",
    "capture_gpu_identity",
]
