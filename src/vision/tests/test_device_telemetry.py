"""The device reading is best-effort and reads the attempt, not itself.

No GPU runs in CI, so `torch` and `mmcv.ops` are stood in for through
`sys.modules`. What is exercised is the control flow: counters are read before
the probe allocates, every failure becomes a field, and a non-CUDA device yields
nothing at all.
"""

from __future__ import annotations

import sys
import types

import pytest

from mavi_vision.runtime import device_telemetry as MODULE


class _Tensor:
    def __init__(self, is_cuda: bool) -> None:
        self.is_cuda = is_cuda


class _FakeCuda:
    def __init__(self, *, available: bool = True, count: int = 1) -> None:
        self.available = available
        self.count = count
        self.calls: list[str] = []

    def is_available(self) -> bool:
        return self.available

    def device_count(self) -> int:
        return self.count

    def max_memory_allocated(self, index: int) -> int:
        self.calls.append(f"allocated:{index}")
        return 1824 * 1024 * 1024

    def max_memory_reserved(self, index: int) -> int:
        self.calls.append(f"reserved:{index}")
        return 2048 * 1024 * 1024

    def get_arch_list(self) -> list[str]:
        return ["sm_75"]

    def synchronize(self, device) -> None:
        self.calls.append("synchronize")


def _install_fakes(monkeypatch, *, cuda: _FakeCuda, nms=None, cuda_version="12.4"):
    torch = types.ModuleType("torch")
    torch.cuda = cuda
    torch.version = types.SimpleNamespace(cuda=cuda_version)
    torch.float32 = "float32"
    torch.device = lambda name: name

    def tensor(values, *, dtype, device):
        cuda.calls.append(f"tensor:{device}")
        return _Tensor(str(device).startswith("cuda"))

    torch.tensor = tensor
    monkeypatch.setitem(sys.modules, "torch", torch)

    mmcv = types.ModuleType("mmcv")
    ops = types.ModuleType("mmcv.ops")
    if nms is None:

        def nms(boxes, scores, threshold):
            cuda.calls.append("nms")
            return _Tensor(boxes.is_cuda), _Tensor(scores.is_cuda)

    ops.nms = nms
    mmcv.ops = ops
    monkeypatch.setitem(sys.modules, "mmcv", mmcv)
    monkeypatch.setitem(sys.modules, "mmcv.ops", ops)


def test_a_cpu_device_yields_nothing():
    assert MODULE.collect_cuda_device_telemetry("cpu") is None


@pytest.mark.parametrize("device", ["cuda", "gpu:0", "cuda:x", ""])
def test_a_malformed_device_yields_nothing(device):
    assert MODULE.collect_cuda_device_telemetry(device) is None


def test_a_healthy_device_reading_has_every_field(monkeypatch):
    cuda = _FakeCuda()
    _install_fakes(monkeypatch, cuda=cuda)

    reading = MODULE.collect_cuda_device_telemetry("cuda:0")

    assert reading == {
        "device": "cuda:0",
        "maxMemoryAllocatedBytes": 1824 * 1024 * 1024,
        "maxMemoryReservedBytes": 2048 * 1024 * 1024,
        "archList": ["sm_75"],
        "runtimeVersion": "12.4",
        "mmcvNmsExecutedOnCuda": True,
        "probeError": None,
    }


def test_counters_are_read_before_the_probe_allocates(monkeypatch):
    """Otherwise the peak would describe this function, not the attempt."""
    cuda = _FakeCuda()
    _install_fakes(monkeypatch, cuda=cuda)

    MODULE.collect_cuda_device_telemetry("cuda:0")

    first_tensor = cuda.calls.index("tensor:cuda:0")
    assert cuda.calls.index("allocated:0") < first_tensor
    assert cuda.calls.index("reserved:0") < first_tensor
    assert cuda.calls[-1] == "synchronize" or "nms" in cuda.calls


def test_the_ordinal_is_the_one_in_the_device_string(monkeypatch):
    cuda = _FakeCuda(count=3)
    _install_fakes(monkeypatch, cuda=cuda)

    MODULE.collect_cuda_device_telemetry("cuda:2")

    assert "allocated:2" in cuda.calls


def test_an_unavailable_device_is_a_field_not_an_exception(monkeypatch):
    _install_fakes(monkeypatch, cuda=_FakeCuda(available=False))

    reading = MODULE.collect_cuda_device_telemetry("cuda:0")

    assert reading["probeError"] == "cuda_device_unavailable"
    assert reading["mmcvNmsExecutedOnCuda"] is False
    assert reading["maxMemoryAllocatedBytes"] is None


def test_an_out_of_range_ordinal_is_a_field(monkeypatch):
    _install_fakes(monkeypatch, cuda=_FakeCuda(count=1))

    reading = MODULE.collect_cuda_device_telemetry("cuda:1")

    assert reading["probeError"] == "cuda_device_unavailable"


def test_a_failing_nms_probe_keeps_the_counters(monkeypatch):
    def failing_nms(boxes, scores, threshold):
        raise RuntimeError("no kernel image is available for execution")

    _install_fakes(monkeypatch, cuda=_FakeCuda(), nms=failing_nms)

    reading = MODULE.collect_cuda_device_telemetry("cuda:0")

    assert reading["maxMemoryAllocatedBytes"] == 1824 * 1024 * 1024
    assert reading["mmcvNmsExecutedOnCuda"] is False
    assert reading["probeError"] == "nms_probe_failed:RuntimeError"


def test_nms_that_returns_cpu_tensors_is_not_on_device_execution(monkeypatch):
    """Same rule as C4: an answer is not evidence of where it was computed."""

    def cpu_nms(boxes, scores, threshold):
        return _Tensor(False), _Tensor(False)

    _install_fakes(monkeypatch, cuda=_FakeCuda(), nms=cpu_nms)

    reading = MODULE.collect_cuda_device_telemetry("cuda:0")

    assert reading["mmcvNmsExecutedOnCuda"] is False
    assert reading["probeError"] is None


def test_a_failing_counter_read_is_a_field(monkeypatch):
    class _Broken(_FakeCuda):
        def max_memory_allocated(self, index):
            raise RuntimeError("CUDA error: device-side assert")

    _install_fakes(monkeypatch, cuda=_Broken())

    reading = MODULE.collect_cuda_device_telemetry("cuda:0")

    assert reading["probeError"] == "counter_read_failed:RuntimeError"
    assert reading["mmcvNmsExecutedOnCuda"] is False


def test_the_module_never_raises_out_of_the_probe(monkeypatch):
    _install_fakes(monkeypatch, cuda=_FakeCuda(), cuda_version=None)

    reading = MODULE.collect_cuda_device_telemetry("cuda:0")

    assert reading["runtimeVersion"] is None
