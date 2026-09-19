"""What the device did during this process's lifetime, read after an attempt.

C6 accepts a CUDA run only with evidence that the GPU was touched: peak device
memory, the kernels the build carries, the CUDA runtime, and the MMCV native
operator executing on the device. None of that is visible from outside the
worker process -- peak allocation is per process and dies with it, and the API
attestation never carried it -- so the worker reads it itself, once, after the
attempt completes and before the next one starts.

The native-operator field is an in-process probe, not a per-frame trace: one
tiny `mmcv.ops.nms` on device tensors, the same standard C4 applies. It proves
the runtime this process loaded executes MMCV's CUDA kernels on this device,
alongside an actual device of `cuda:N` and a non-zero peak allocation from the
run itself. It does not instrument the detector.

Best-effort throughout. This is diagnostic evidence for a Development record;
it must never change what an attempt returns, so every failure here becomes a
field in the reading rather than an exception out of it.
"""

from __future__ import annotations

import re

_CUDA_DEVICE = re.compile(r"^cuda:(\d+)$")


def collect_cuda_device_telemetry(device: str) -> dict[str, object] | None:
    """Read the device counters for one CUDA device; None off CUDA.

    Runs on the vision lane, because it touches the CUDA context. Peak memory
    counters are read *before* the probe allocates anything, so the values
    describe the attempt and not this function.
    """
    match = _CUDA_DEVICE.fullmatch(device)
    if match is None:
        return None
    index = int(match.group(1))

    reading: dict[str, object] = {
        "device": device,
        "maxMemoryAllocatedBytes": None,
        "maxMemoryReservedBytes": None,
        "archList": None,
        "runtimeVersion": None,
        "mmcvNmsExecutedOnCuda": False,
        "probeError": None,
    }

    try:
        import torch
    except Exception as exc:  # pragma: no cover - torch is a pack dependency
        reading["probeError"] = f"torch_import_failed:{type(exc).__name__}"
        return reading

    try:
        if not torch.cuda.is_available() or index >= torch.cuda.device_count():
            reading["probeError"] = "cuda_device_unavailable"
            return reading
        reading["maxMemoryAllocatedBytes"] = int(
            torch.cuda.max_memory_allocated(index)
        )
        reading["maxMemoryReservedBytes"] = int(
            torch.cuda.max_memory_reserved(index)
        )
        reading["archList"] = [str(item) for item in torch.cuda.get_arch_list()]
        runtime_version = getattr(torch.version, "cuda", None)
        reading["runtimeVersion"] = (
            str(runtime_version) if runtime_version else None
        )
    except Exception as exc:
        reading["probeError"] = f"counter_read_failed:{type(exc).__name__}"
        return reading

    try:
        from mmcv.ops import nms

        target = torch.device(device)
        boxes = torch.tensor(
            [[0.0, 0.0, 10.0, 10.0], [1.0, 1.0, 11.0, 11.0]],
            dtype=torch.float32,
            device=target,
        )
        scores = torch.tensor([0.9, 0.8], dtype=torch.float32, device=target)
        dets, keep = nms(boxes, scores, 0.5)
        torch.cuda.synchronize(target)
        reading["mmcvNmsExecutedOnCuda"] = bool(dets.is_cuda and keep.is_cuda)
    except Exception as exc:
        reading["probeError"] = f"nms_probe_failed:{type(exc).__name__}"

    return reading


__all__ = ["collect_cuda_device_telemetry"]
