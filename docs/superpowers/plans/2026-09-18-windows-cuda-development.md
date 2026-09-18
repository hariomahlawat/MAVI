# Windows CUDA Development Enablement Plan

**Date:** 2026-09-18  
**Base:** `main@9b0b88f5c9d20ddfa8c4e835e454d24c69921b84`  
**C1R merged to `main`:** PR #48 head `c80ce10b823443230e316fc2978116c73d703c8f`, merge commit `02257793556026a37238f06c13755c87da35f141`  
**Active branch:** `feature/windows-cuda-pre-c2` (from `main@0225779`)  
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

## Phase C0 — host observation — COMPLETE

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

**PASSED.** The real laptop observation has been reviewed. Sanitized facts and the resulting C1 decision are recorded in `docs/qualification/2026-09-18-windows-cuda-c1-compatibility-decision.md`.

The host observation remains factual evidence only and does not set a qualification status.

## Phase C1 — compatibility decision — COMPLETE FOR ENGINEERING

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

**PASSED FOR ENGINEERING VALIDATION.** The C1 candidate is frozen in `docs/qualification/2026-09-18-windows-cuda-c1-compatibility-decision.md`:

- CPython 3.12.10;
- PyTorch 2.6.0+cu124 candidate;
- torchvision 0.21.0+cu124 candidate;
- CUDA 12.4 runtime family carried by PyTorch;
- MMCV 2.1.0;
- MMEngine 0.10.7;
- MMDetection 3.3.0;
- observed host driver 576.83;
- observed development GPU GTX 1650 Ti / 4096 MiB.

The final MSVC/Windows SDK native ABI identity remains intentionally unfrozen until C2 observes the actual native build/validation toolchain.

## Phase C1R — external review remediation — COMPLETE AND MERGED

Claude's independent cold review of PR #48 concluded:

`C1 ACCEPTABLE WITH REQUIRED CORRECTIONS BEFORE C2`

Two further independent cold reviews audited those corrections rather than
assuming them complete, and found residual fail-open boundaries in them. Their
findings and dispositions are recorded in
`docs/reviews/2026-09-18-pr48-claude-c1r-adjudication.md`.

Repository-side C1R is now closed and merged to `main` as the merge commit
recorded in this plan's header. C2 remains **not authorized** until the
empirical pre-C2 evidence below is collected.

### C1R implemented controls

- host observation upgraded to schema v2 with compute capability, PCI bus ID, free/used VRAM, driver/display state and sanitized stdout;
- checked-in schema is validated by tests;
- dedicated build contract added at `config/vision/windows-cuda-development-build-v1.json`;
- dedicated CUDA acquisition/offline prerequisite policy recorded;
- CPU Torch cannot be frozen into a CUDA-labelled lock/pack;
- CUDA Torch local versions are semantically compatible with the base runtime graph without weakening exact binary checks;
- CUDA Runtime Pack native ABI must include CUDA family and target architecture;
- Development CUDA may use `qualified-development-hardware`, which Production profiles explicitly reject;
- physical GPU provenance includes UUID, PCI bus ID and compute capability;
- `CUDA_DEVICE_ORDER=PCI_BUS_ID` is enforced before worker CUDA imports;
- Development `Auto` performs a non-executing installed-state preflight before probing the CUDA runtime and emits a stable selection/fallback reason;
- the device-resolution reason vocabulary is closed and authoritative in the contract layer, mirrored by JSON Schema, Pydantic and .NET, with the Production prohibition on Auto results applied by the worker where deployment context exists;
- Development `Auto` resolved inside `RuntimeSupervisor` records its reason, not only the launcher path;
- the CUDA ordinal is bound to a physical GPU through the driver's queried inventory (UUID and PCI bus ID) rather than an assumed ordinal coincidence, and fails closed when the mapping cannot be proven;
- a CUDA-labelled offline lock proves CUDA wheel identity whether or not a binary version map is supplied;
- the CUDA-lock gate is an allow-list over a verified and frozen toolchain in both the build contract and the offline catalogue, which must agree.

ADR-009 governs Development-vs-Production qualification separation.

### C1R remaining external observations

The following cannot be truthfully frozen from repository code alone and remain required before C2:

1. **R1 toolchain preflight:** CUDA Toolkit 12.4 must compile a trivial `.cu` file with the selected MSVC toolset/Windows SDK. The repository must not assume 14.39 or retain 14.44 without this proof.
2. **Real v2 host observation:** rerun the host probe so compute capability, PCI identity and memory availability are directly observed rather than inferred from the GPU model.
3. **Torch cu124 wheel inspection:** confirm Windows wheel metadata/dependency markers and enumerate/hash the CUDA DLL inventory.
4. **MMCV reproducibility experiment:** build the CUDA MMCV wheel twice from a clean controlled build environment before C3; if byte reproducibility is not achievable, an ADR must define a controlled hash-pinned binary-input model.

### Gate C1R — repository side — PASSED AND MERGED

- all five exact-head workflows green on `c80ce10`;
- Windows CPU lock, `runtime.json` and the component declaration byte-identical to `main`;
- no `windows-x86_64-cuda.lock`, Runtime Pack or CUDA component requirement introduced;
- no runtime variant promoted; `windows-x86_64-cuda` remains `pending-hardware-qualification`;
- the build contract remains fail-closed at `pending-r1-preflight`.

Merging this foundation is **not** a CUDA qualification of any kind.

### Gate R1 / pre-C2 — empirical — NEXT ACTIVE GATE

C2 may not begin until all of the following are collected on the controlled
Windows CUDA build host and reviewed:

- the exact CUDA 12.4 + MSVC toolset + Windows SDK proven by compiling a trivial
  `.cu` file, and frozen into both the build contract and the offline catalogue;
- the real v2 host observation, with its evidence SHA-256 retained;
- the real `torch 2.6.0+cu124` cp312 win_amd64 wheel inspection.

Until the build contract leaves `pending-r1-preflight`, `tools/verify_repo.py`
refuses any Windows CUDA lock. That refusal is the intended behaviour, not an
obstacle to work around.

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

The C2 build environment must set:

- `MMCV_WITH_OPS=1`;
- `FORCE_CUDA=1`;
- `TORCH_CUDA_ARCH_LIST=7.5+PTX`;
- the exact toolchain frozen by R1.

The authoritative C2 wheel build occurs on a controlled Windows build host. The Development laptop is the C4/C6 hardware-execution target, not the authoritative wheel build host.

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

Runtime Pack reproduction from the same inputs must produce the same content identity. The CUDA MMCV wheel must first be rebuilt twice from clean inputs and compared byte-for-byte. If native CUDA compilation proves irreducibly non-deterministic, stop and adopt a reviewed ADR that treats the MMCV CUDA wheel as a controlled, archived, hash-pinned binary input rather than silently weakening this gate.

Existing Windows CPU Runtime Pack checks must remain green.

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

Only after this passes may runtime metadata change `windows-x86_64-cuda` from pending to `qualified-development-hardware` with the ADR-009 Development evidence shape.

This state must remain unacceptable to P1/P2 Production qualification.

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

Also capture:

- `torch.cuda.max_memory_allocated()`;
- `torch.cuda.max_memory_reserved()`;
- `nvidia-smi` free/used memory before, during and after the run;
- `torch.cuda.get_arch_list()`;
- `torch.version.cuda`;
- host RAM peak;
- one deliberate, bounded CUDA OOM/recovery exercise.

The CUDA run must prove on-device MMCV native ops, for example CUDA-tensor NMS, before RTMDet E2E evidence is accepted.

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

## Current execution point

C0, C1 and C1R are complete. C1R is merged to `main`; the merge commit is
recorded in this plan's header.

The next active gate is **R1 — empirical CUDA 12.4 / MSVC host-toolchain
preflight**. Work continues on `feature/windows-cuda-pre-c2`, which exists only
to collect that evidence. Creating that branch does not start C2.

**Do not begin C2 wheel acquisition, build MMCV CUDA, or freeze a CUDA lock
until R1 toolchain preflight, the fresh v2 host observation and the real Torch
wheel inspection are reviewed.**

R1 must try the currently available/preferred MSVC toolset first and select an
older one only if CUDA 12.4 empirically rejects it. `--allow-unsupported-compiler`
is never acceptable: the purpose is to qualify a supportable toolchain, not to
force a build through.

Two known items remain scheduled beyond this gate and must not be pulled
forward:

- the Development `Auto` Torch-runtime smoke probe (**C3/C4**). The launcher's
  Auto check deliberately does not execute code from a candidate pack, so it
  cannot yet detect a pack whose Torch CUDA runtime installs but fails to
  initialise. That path is unreachable while no CUDA Runtime Pack exists, and
  closing it needs a real pack to validate against. See the runbook's "Known
  gap" note.
- `nativeAbi` remains a declared string. Proving the packed MMCV actually
  carries CUDA ops is the on-device `mmcv.ops.nms` check in
  `tools/vision/verify_windows_cuda_runtime.py`, and belongs to C2/C4 evidence.

Production CUDA qualification remains a separate concern throughout. No
Development evidence, on this laptop or any other Development host, may promote
a Production profile or satisfy a P1/P2 runtime gate.

The existing Windows CPU lock and Runtime Pack must remain byte-for-byte unchanged.

The raw host observation remains local engineering evidence and should not be committed because it contains workstation-specific GPU identity.
