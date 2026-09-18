# Windows CUDA Development Enablement Plan

**Date:** 2026-09-18  
**Base:** `main@9b0b88f5c9d20ddfa8c4e835e454d24c69921b84`  
**Branch:** `feature/windows-cuda-development`  
**Objective:** make the Windows laptop GPU a first-class MAVI Development execution path without weakening the qualified Windows CPU path or prematurely claiming P1 Production acceptance.

## Decision boundary

This work is **engineering enablement and hardware qualification for Development**.

It may produce reusable evidence for a later P1 Production qualification, but it does not by itself promote P1 to Production-supported.

The following remain independent:

- Development Windows CUDA engineering qualification;
- P1 single-host Windows GPU Production acceptance;
- P2 Linux CUDA Production acceptance;
- P3 Windows CPU Production acceptance.

## Existing baseline

Already implemented on `main`:

- `windows-x86_64-cuda` is a recognized runtime variant;
- Development supports `Auto`, `CUDA` and `CPU` device policies;
- CPU and CUDA Runtime Packs install side-by-side;
- the launcher chooses the runtime environment before Python starts;
- explicit CUDA fails rather than silently becoming CPU;
- provenance requires GPU identity for CUDA execution;
- profile-aware Production qualification remains fail-closed;
- Windows CPU Runtime Pack and lock remain qualified and must not be modified by CUDA work.

Still intentionally absent:

- frozen Windows CUDA third-party lock;
- frozen Windows CUDA requirements projection;
- Windows CUDA Runtime Pack identity;
- Windows CUDA component requirement in the Application Overlay;
- real Windows CUDA hardware evidence;
- CUDA-specific MMCV/native-op proof;
- Development CUDA E2E evidence;
- P1 Production acceptance.

## Phase C0 — host observation

### Deliverables

- deterministic `tools/vision/probe_windows_cuda_host.py`;
- machine-readable schema;
- tests for parsing/fail-closed behavior;
- one observation generated on the actual development laptop.

### Required facts

- Windows release/build;
- x86_64 architecture;
- NVIDIA GPU index/name/UUID;
- NVIDIA driver version;
- VRAM;
- driver-advertised CUDA compatibility level.

### Gate C0

Do not select a PyTorch CUDA build until the real laptop observation has been reviewed.

The host observation is factual evidence only. It never sets a qualification status.

## Phase C1 — compatibility decision

Using the C0 observation, freeze an **engineering candidate** for:

- CPython patch version;
- PyTorch binary build;
- torchvision binary build;
- CUDA runtime carried by PyTorch;
- MMCV build approach;
- MSVC/Windows SDK/native ABI identity.

Prefer retaining the existing semantic graph:
- torch 2.6.0;
- torchvision 0.21.0;
- mmcv 2.1.0;
- mmengine 0.10.7;
- mmdet 3.3.0;
- existing downstream Phase-1 dependencies.

A change to semantic versions requires an explicit compatibility review rather than being hidden inside CUDA enablement.

### Gate C1

Document why the selected binary graph is compatible with the observed driver/GPU. Do not infer compatibility only from test fixtures such as `+cu124`.

## Phase C2 — reproducible Windows CUDA wheelhouse and lock

Build the CUDA wheelhouse as a separate closure.

Required properties:

- no mutation of `windows-x86_64-cpu.lock`;
- no first-party `mavi-vision` wheel inside the reusable Runtime Pack;
- exact wheel SHA-256 values;
- full transitive dependency closure;
- deterministic `windows-x86_64-cuda.lock`;
- deterministic requirements projection;
- no network dependency during installation.

MMCV must be built/selected against the exact Torch/CUDA ABI and cannot silently degrade to CPU-only native ops.

### Gate C2

A clean Windows venv must install the entire closure with:
`--no-index --only-binary=:all: --require-hashes`
and `pip check` must pass.

## Phase C3 — Runtime Pack

Build a reusable third-party-only Windows CUDA Runtime Pack.

Freeze:

- Runtime Pack ID;
- lock SHA-256;
- requirements SHA-256;
- Python identity;
- native ABI;
- Torch/torchvision binary build identity.

### Gate C3

Runtime Pack reproduction from the same inputs must produce the same content identity. Existing Windows CPU Runtime Pack checks must remain green.

## Phase C4 — hardware runtime qualification

On the laptop, prove the exact C3 pack:

- starts with `cuda:0`;
- `torch.cuda.is_available()` is true;
- actual GPU identity matches C0 observation;
- exact Torch CUDA runtime is recorded;
- MMCV native/CUDA ops load and execute;
- RTMDet real inference succeeds using the frozen local model/config;
- no package/model download occurs;
- no CPU fallback occurs under explicit `CUDA`.

### Gate C4

Only after this passes may runtime metadata change `windows-x86_64-cuda` from pending to an engineering-qualified hardware state.

## Phase C5 — Application Overlay binding

Add `windows-x86_64-cuda` to
`src/vision/config/components/mmdetection-phase1-v1.json`
with the exact:

- Runtime Pack ID;
- third-party lock SHA-256;
- runtime-requirements SHA-256;
- native ABI.

Before C5, Development `Auto` must continue to choose CPU.

### Gate C5

Application checkout + Runtime Pack + Model Pack compatibility must fail closed on any changed identity.

## Phase C6 — MAVI Development E2E

Use the known `2min.mp4` test and additional controlled media.

Prove:

1. `CUDA` selects `cuda:0`;
2. `Auto` selects CUDA when the qualified pack/device is available;
3. processing reaches 100% and the video becomes Processed;
4. detection/tracking output is persisted;
5. runtime/model/device provenance records the CUDA execution;
6. CPU mode still completes independently;
7. retry/restart behavior remains correct;
8. no silent GPU-to-CPU fallback occurs.

Capture CPU vs CUDA elapsed time/FPS for engineering characterization only; do not freeze Production thresholds from this comparison.

## Phase C7 — failure and recovery

Exercise:

- missing CUDA Runtime Pack;
- incompatible/tampered Runtime Pack;
- invalid device index;
- unavailable CUDA device;
- worker restart;
- bounded CUDA OOM/recovery where safely reproducible;
- Development Auto fallback to CPU with explicit log/provenance.

Explicit `CUDA` must always fail closed.

## Phase C8 — review and merge

Before merge to `main`:

- full hosted CI green on exact head;
- hardware evidence reviewed;
- CPU regression path green;
- independent cold review;
- documentation updated;
- no Production-support claim introduced.

Merge the milestone back to `main` promptly rather than allowing another long-lived integration branch.

## First operator action

Run this on the Windows development laptop from repository root:

```powershell
python tools/vision/probe_windows_cuda_host.py --output windows-cuda-host-observation.json
```

Then inspect the JSON before selecting the CUDA/PyTorch binary graph.

The observation file is local engineering evidence and should not be committed if it contains machine-specific GPU UUID or other workstation identity.
