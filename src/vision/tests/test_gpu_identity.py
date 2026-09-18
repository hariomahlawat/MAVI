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
