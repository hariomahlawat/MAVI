#!/usr/bin/env python3
"""Positive CUDA runtime/native-op verification for C4/C6 evidence."""

from __future__ import annotations

import argparse
import json
import os


class CudaRuntimeVerificationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def verify(device_index: int) -> dict[str, object]:
    if os.environ.get("CUDA_DEVICE_ORDER") != "PCI_BUS_ID":
        raise CudaRuntimeVerificationError(
            "cuda_device_order_not_pci_bus_id"
        )

    import torch
    from mmcv.ops import nms

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

    return {
        "schemaVersion": "mavi-windows-cuda-runtime-verification-v1",
        "deviceIndex": device_index,
        "deviceName": props.name,
        "computeCapability": capability,
        "torchVersion": torch.__version__,
        "torchCudaRuntimeVersion": torch.version.cuda,
        "torchCudaArchList": arch_list,
        "totalMemoryBytes": int(props.total_memory),
        "peakMemoryAllocatedBytes": int(
            torch.cuda.max_memory_allocated(device)
        ),
        "peakMemoryReservedBytes": int(
            torch.cuda.max_memory_reserved(device)
        ),
        "mmcvNmsExecutedOnCuda": True,
        "torchMatmulExecutedOnCuda": True,
        "result": "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        value = verify(args.device_index)
    except (CudaRuntimeVerificationError, Exception) as exc:
        code = (
            exc.code
            if isinstance(exc, CudaRuntimeVerificationError)
            else "cuda_runtime_verification_failed"
        )
        print(json.dumps({"ok": False, "code": code}, sort_keys=True))
        return 2
    if args.output:
        from pathlib import Path
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
