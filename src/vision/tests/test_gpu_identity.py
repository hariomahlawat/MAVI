"""GPU provenance must name the physical GPU that executed, or refuse.

The CUDA ordinal is never assumed to equal the nvidia-smi ordinal. These tests
pin that: the interesting cases are the ones where the two orders differ.
"""

from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest

from mavi_vision.runtime import gpu_identity


# Two physical GPUs whose nvidia-smi order is the REVERSE of their PCI-bus
# order. Under CUDA_DEVICE_ORDER=PCI_BUS_ID, cuda:0 is the 0x01 card, which is
# nvidia-smi index 1. Any implementation that queries `nvidia-smi -i 0` for
# cuda:0 attests the wrong card here.
_SMI_INDEX_0 = "0, GPU-bbbbbbbb-0000-0000-0000-000000000002, 00000000:41:00.0, 576.83, 8192, 8.6"
_SMI_INDEX_1 = "1, GPU-aaaaaaaa-0000-0000-0000-000000000001, 00000000:01:00.0, 576.83, 4096, 7.5"

_SINGLE = "0, GPU-aaaaaaaa-0000-0000-0000-000000000001, 00000000:01:00.0, 576.83, 4096, 7.5"

# A host where the nvidia-smi order and the PCI-bus order agree, so a numeric
# CUDA_VISIBLE_DEVICES entry has only one possible reading.
_AGREEING_0 = "0, GPU-aaaaaaaa-0000-0000-0000-000000000001, 00000000:01:00.0, 576.83, 4096, 7.5"
_AGREEING_1 = "1, GPU-bbbbbbbb-0000-0000-0000-000000000002, 00000000:41:00.0, 576.83, 8192, 8.6"

_UUID_LOW_PCI = "GPU-aaaaaaaa-0000-0000-0000-000000000001"
_UUID_HIGH_PCI = "GPU-bbbbbbbb-0000-0000-0000-000000000002"


class _FakeCuda:
    def __init__(self, devices: list[SimpleNamespace]) -> None:
        self._devices = devices

    def is_available(self) -> bool:
        return True

    def device_count(self) -> int:
        return len(self._devices)

    def get_device_properties(self, index: int):
        return self._devices[index]


class _FakeTorch:
    def __init__(self, devices: list[SimpleNamespace]) -> None:
        self.cuda = _FakeCuda(devices)
        self.version = SimpleNamespace(cuda="12.4")


def _properties(
    *,
    name: str = "NVIDIA GeForce GTX 1650 Ti",
    total_mib: int = 4096,
    major: int = 7,
    minor: int = 5,
    uuid: str | None = None,
) -> SimpleNamespace:
    value = SimpleNamespace(
        name=name,
        total_memory=total_mib * 1024 * 1024,
        major=major,
        minor=minor,
    )
    if uuid is not None:
        value.uuid = uuid
    return value


_GTX_1650_TI = dict(name="NVIDIA GeForce GTX 1650 Ti", total_mib=4096, major=7, minor=5)
_RTX_3070 = dict(name="NVIDIA GeForce RTX 3070", total_mib=8192, major=8, minor=6)


def _completed(stdout: str, returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


@pytest.fixture(autouse=True)
def _stable_cuda_enumeration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[str],
    devices: list[dict],
    returncode: int = 0,
) -> list[tuple[str, ...]]:
    monkeypatch.setitem(
        sys.modules,
        "torch",
        _FakeTorch([_properties(**device) for device in devices]),
    )
    observed: list[tuple[str, ...]] = []

    def _capture(args, *, env=None):
        observed.append(tuple(args))
        _capture.env = env
        return _completed("\n".join(rows) + "\n", returncode)

    monkeypatch.setattr(gpu_identity, "_run", _capture)
    return observed


def test_single_gpu_identity_is_captured(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, rows=[_SINGLE], devices=[_GTX_1650_TI])

    value = gpu_identity.capture_gpu_identity("cuda:0")

    assert value.name == "NVIDIA GeForce GTX 1650 Ti"
    assert value.index == 0
    assert value.vram_bytes == 4096 * 1024 * 1024
    assert value.driver_version == "576.83"
    assert value.cuda_runtime_version == "12.4"
    assert value.uuid == _UUID_LOW_PCI
    assert value.pci_bus_id == "00000000:01:00.0"
    assert value.compute_capability == "7.5"


def test_cuda_ordinal_follows_pci_order_not_nvidia_smi_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cuda:0 is the lowest PCI bus ID, which here is nvidia-smi index 1."""
    _install(
        monkeypatch,
        rows=[_SMI_INDEX_0, _SMI_INDEX_1],
        devices=[_GTX_1650_TI, _RTX_3070],
    )

    value = gpu_identity.capture_gpu_identity("cuda:0")

    assert value.uuid == _UUID_LOW_PCI
    assert value.pci_bus_id == "00000000:01:00.0"
    assert value.compute_capability == "7.5"


def test_second_cuda_ordinal_resolves_the_higher_pci_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        rows=[_SMI_INDEX_0, _SMI_INDEX_1],
        devices=[_GTX_1650_TI, _RTX_3070],
    )

    value = gpu_identity.capture_gpu_identity("cuda:1")

    assert value.uuid == _UUID_HIGH_PCI
    assert value.pci_bus_id == "00000000:41:00.0"
    assert value.compute_capability == "8.6"


def test_inventory_query_is_not_addressed_by_ordinal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe must enumerate, never select by an assumed index."""
    observed = _install(monkeypatch, rows=[_SINGLE], devices=[_GTX_1650_TI])

    gpu_identity.capture_gpu_identity("cuda:0")

    assert "-i" not in observed[0]
    assert any("--query-gpu=" in argument for argument in observed[0])


def test_inventory_query_ignores_any_visible_device_mask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The physical inventory must be complete regardless of NVML behaviour."""
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", _UUID_HIGH_PCI)
    captured: dict[str, object] = {}

    monkeypatch.setitem(
        sys.modules,
        "torch",
        _FakeTorch([_properties(**_RTX_3070)]),
    )

    def _capture(args, *, env=None):
        captured["env"] = env
        return _completed(_SMI_INDEX_0 + "\n" + _SMI_INDEX_1 + "\n")

    monkeypatch.setattr(gpu_identity, "_run", _capture)

    value = gpu_identity.capture_gpu_identity("cuda:0")

    assert "CUDA_VISIBLE_DEVICES" not in captured["env"]
    assert value.uuid == _UUID_HIGH_PCI


def test_numeric_visible_device_mask_selects_that_physical_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mask states the CUDA order explicitly; PCI order no longer applies."""
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    _install(
        monkeypatch,
        rows=[_AGREEING_0, _AGREEING_1],
        devices=[_RTX_3070],
    )

    value = gpu_identity.capture_gpu_identity("cuda:0")

    assert value.uuid == _UUID_HIGH_PCI
    assert value.pci_bus_id == "00000000:41:00.0"


def test_numeric_visible_device_mask_preserves_mask_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1,0")
    _install(
        monkeypatch,
        rows=[_AGREEING_0, _AGREEING_1],
        devices=[_RTX_3070, _GTX_1650_TI],
    )

    assert gpu_identity.capture_gpu_identity("cuda:0").uuid == _UUID_HIGH_PCI
    assert gpu_identity.capture_gpu_identity("cuda:1").uuid == _UUID_LOW_PCI


def test_ambiguous_numeric_mask_without_a_runtime_uuid_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A numeric entry is unprovable when the two enumerations disagree.

    Entry "0" could mean the driver's device 0 or the PCI-first device; on this
    host those are different cards, and nothing here can prove which CUDA meant.
    """
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    _install(
        monkeypatch,
        rows=[_SMI_INDEX_0, _SMI_INDEX_1],
        devices=[_RTX_3070],
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_visible_devices_ambiguous",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_ambiguous_numeric_mask_is_settled_by_the_runtime_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Torch's own device UUID proves which reading CUDA actually used."""
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    _install(
        monkeypatch,
        rows=[_SMI_INDEX_0, _SMI_INDEX_1],
        devices=[
            {**_GTX_1650_TI, "uuid": "aaaaaaaa-0000-0000-0000-000000000001"}
        ],
    )

    value = gpu_identity.capture_gpu_identity("cuda:0")

    assert value.uuid == _UUID_LOW_PCI
    assert value.pci_bus_id == "00000000:01:00.0"


def test_uuid_visible_device_mask_selects_that_physical_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", _UUID_HIGH_PCI)
    _install(
        monkeypatch,
        rows=[_SMI_INDEX_0, _SMI_INDEX_1],
        devices=[_RTX_3070],
    )

    value = gpu_identity.capture_gpu_identity("cuda:0")

    assert value.uuid == _UUID_HIGH_PCI
    assert value.compute_capability == "8.6"


def test_unknown_visible_device_selector_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "7")
    _install(monkeypatch, rows=[_SINGLE], devices=[_GTX_1650_TI])

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_visible_devices_unresolved",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_duplicate_visible_device_selector_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same physical GPU twice makes the ordinal mapping ambiguous."""
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", f"{_UUID_LOW_PCI},{_UUID_LOW_PCI}")
    _install(
        monkeypatch,
        rows=[_SMI_INDEX_0, _SMI_INDEX_1],
        devices=[_GTX_1650_TI, _GTX_1650_TI],
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_visible_devices_duplicate",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_mig_visible_device_selector_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CUDA_VISIBLE_DEVICES",
        "MIG-c1f2c4a0-0000-0000-0000-000000000000",
    )
    _install(monkeypatch, rows=[_SINGLE], devices=[_GTX_1650_TI])

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_visible_devices_unsupported",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_empty_visible_device_mask_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    _install(monkeypatch, rows=[_SINGLE], devices=[_GTX_1650_TI])

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_visible_devices_empty",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_mask_shorter_than_the_runtime_device_count_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Our reconstruction must agree with the runtime, or nothing is trusted."""
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", _UUID_LOW_PCI)
    _install(
        monkeypatch,
        rows=[_SMI_INDEX_0, _SMI_INDEX_1],
        devices=[_GTX_1650_TI, _RTX_3070],
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_device_count_mismatch",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_inventory_smaller_than_the_runtime_device_count_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        rows=[_SINGLE],
        devices=[_GTX_1650_TI, _RTX_3070],
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_device_count_mismatch",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


@pytest.mark.parametrize("order", ["FASTEST_FIRST", ""])
def test_unstable_cuda_device_order_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    order: str,
) -> None:
    monkeypatch.setenv("CUDA_DEVICE_ORDER", order)
    _install(monkeypatch, rows=[_SINGLE], devices=[_GTX_1650_TI])

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_device_order_unstable",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_absent_cuda_device_order_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CUDA_DEVICE_ORDER", raising=False)
    _install(monkeypatch, rows=[_SINGLE], devices=[_GTX_1650_TI])

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_device_order_unstable",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_torch_uuid_mismatch_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Torch's own device UUID outranks any ordering reconstruction."""
    _install(
        monkeypatch,
        rows=[_SINGLE],
        devices=[{**_GTX_1650_TI, "uuid": "bbbbbbbb-0000-0000-0000-000000000002"}],
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_uuid_mismatch",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_matching_torch_uuid_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        rows=[_SINGLE],
        devices=[{**_GTX_1650_TI, "uuid": "aaaaaaaa-0000-0000-0000-000000000001"}],
    )

    assert gpu_identity.capture_gpu_identity("cuda:0").uuid == _UUID_LOW_PCI


def test_compute_capability_mismatch_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, rows=[_SINGLE], devices=[_RTX_3070])

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_compute_capability_mismatch",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_memory_mismatch_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        rows=[_SINGLE],
        devices=[{**_GTX_1650_TI, "total_mib": 6144}],
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_memory_mismatch",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_malformed_pci_bus_id_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ordering may never fall back to a coincidental string comparison."""
    _install(
        monkeypatch,
        rows=["0, GPU-aaaa-1, not-a-pci-id, 576.83, 4096, 7.5"],
        devices=[_GTX_1650_TI],
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_pci_bus_id_invalid",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_duplicate_physical_uuid_inventory_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        rows=[_SMI_INDEX_0, _SMI_INDEX_0.replace("0,", "1,", 1)],
        devices=[_RTX_3070, _RTX_3070],
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_nvidia_smi_invalid",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_failed_inventory_query_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        rows=[_SINGLE],
        devices=[_GTX_1650_TI],
        returncode=9,
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_nvidia_smi_failed",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_unavailable_device_index_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "torch",
        _FakeTorch([_properties(**_GTX_1650_TI)]),
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_index_unavailable",
    ):
        gpu_identity.capture_gpu_identity("cuda:1")


@pytest.mark.parametrize("device", ["cuda", "cpu", "cuda:-1", "CUDA:0"])
def test_invalid_device_string_is_rejected(device: str) -> None:
    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_device_invalid",
    ):
        gpu_identity.capture_gpu_identity(device)
