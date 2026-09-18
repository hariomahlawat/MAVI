from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest

from mavi_vision.runtime import gpu_identity


class _FakeCuda:
    def __init__(self) -> None:
        self._props = SimpleNamespace(
            name="NVIDIA GeForce GTX 1650 Ti",
            total_memory=4 * 1024 * 1024 * 1024,
            major=7,
            minor=5,
        )

    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def device_count() -> int:
        return 1

    def get_device_properties(self, index: int):
        assert index == 0
        return self._props


class _FakeTorch:
    cuda = _FakeCuda()
    version = SimpleNamespace(cuda="12.4")


@pytest.fixture(autouse=True)
def _stable_cuda_enumeration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every capture runs under the enumeration contract the probe requires."""
    monkeypatch.setenv("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)


def _completed(stdout: str, returncode: int = 0):
    return SimpleNamespace(
        stdout=stdout,
        stderr="",
        returncode=returncode,
    )


def test_capture_gpu_identity_binds_torch_to_nvidia_smi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())
    monkeypatch.setattr(
        gpu_identity,
        "_run",
        lambda _args: _completed(
            "GPU-test, 00000000:01:00.0, 576.83, 4096, 7.5\n"
        ),
    )

    value = gpu_identity.capture_gpu_identity("cuda:0")

    assert value.name == "NVIDIA GeForce GTX 1650 Ti"
    assert value.index == 0
    assert value.vram_bytes == 4 * 1024 * 1024 * 1024
    assert value.driver_version == "576.83"
    assert value.cuda_runtime_version == "12.4"
    assert value.uuid == "GPU-test"
    assert value.pci_bus_id == "00000000:01:00.0"
    assert value.compute_capability == "7.5"


def test_capture_gpu_identity_rejects_compute_capability_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())
    monkeypatch.setattr(
        gpu_identity,
        "_run",
        lambda _args: _completed(
            "GPU-test, 00000000:01:00.0, 576.83, 4096, 8.0\n"
        ),
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_compute_capability_mismatch",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_capture_gpu_identity_rejects_unavailable_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_index_unavailable",
    ):
        gpu_identity.capture_gpu_identity("cuda:1")


@pytest.mark.parametrize("device", ["cuda", "cpu", "cuda:-1", "CUDA:0"])
def test_capture_gpu_identity_rejects_invalid_device(
    device: str,
) -> None:
    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_device_invalid",
    ):
        gpu_identity.capture_gpu_identity(device)


def test_capture_gpu_identity_rejects_unstable_cuda_device_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-PCI-bus CUDA ordering breaks the torch/nvidia-smi index binding."""
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())
    monkeypatch.setenv("CUDA_DEVICE_ORDER", "FASTEST_FIRST")

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_device_order_unstable",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_capture_gpu_identity_rejects_absent_cuda_device_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())
    monkeypatch.delenv("CUDA_DEVICE_ORDER", raising=False)

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_device_order_unstable",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_capture_gpu_identity_resolves_masked_physical_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CUDA index 0 under a mask must query the masked physical GPU."""
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "3,1")
    observed: list[tuple[str, ...]] = []

    def _capture(args):
        observed.append(tuple(args))
        return _completed(
            "GPU-masked, 00000000:03:00.0, 576.83, 4096, 7.5\n"
        )

    monkeypatch.setattr(gpu_identity, "_run", _capture)

    value = gpu_identity.capture_gpu_identity("cuda:0")

    assert observed[0][observed[0].index("-i") + 1] == "3"
    assert value.uuid == "GPU-masked"
    assert value.pci_bus_id == "00000000:03:00.0"


def test_capture_gpu_identity_rejects_mask_shorter_than_device_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2")

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_visible_devices_index_unavailable",
    ):
        gpu_identity.capture_gpu_identity("cuda:1")


def test_capture_gpu_identity_rejects_empty_visible_device_mask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_visible_devices_empty",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_capture_gpu_identity_rejects_unsupported_visible_device_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A MIG partition cannot be bound to one physical GPU identity."""
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())
    monkeypatch.setenv(
        "CUDA_VISIBLE_DEVICES",
        "MIG-c1f2c4a0-0000-0000-0000-000000000000",
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_visible_devices_unsupported",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_capture_gpu_identity_rejects_torch_uuid_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Torch's own device UUID is authoritative over index correlation."""
    torch = _FakeTorch()
    monkeypatch.setattr(
        torch.cuda._props,
        "uuid",
        "3f2b1c4d-0000-0000-0000-000000000001",
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(
        gpu_identity,
        "_run",
        lambda _args: _completed(
            "GPU-aaaaaaaa-0000-0000-0000-000000000002,"
            " 00000000:01:00.0, 576.83, 4096, 7.5\n"
        ),
    )

    with pytest.raises(
        gpu_identity.GpuIdentityProbeError,
        match="gpu_identity_uuid_mismatch",
    ):
        gpu_identity.capture_gpu_identity("cuda:0")


def test_capture_gpu_identity_accepts_matching_torch_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    torch = _FakeTorch()
    monkeypatch.setattr(
        torch.cuda._props,
        "uuid",
        "3f2b1c4d-0000-0000-0000-000000000001",
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(
        gpu_identity,
        "_run",
        lambda _args: _completed(
            "GPU-3f2b1c4d-0000-0000-0000-000000000001,"
            " 00000000:01:00.0, 576.83, 4096, 7.5\n"
        ),
    )

    value = gpu_identity.capture_gpu_identity("cuda:0")

    assert value.uuid == "GPU-3f2b1c4d-0000-0000-0000-000000000001"
