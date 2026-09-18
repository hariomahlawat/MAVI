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

At C1 the final MSVC/Windows SDK native ABI identity was intentionally left unfrozen. It has since been frozen empirically by R1 (CUDA 12.4 + MSVC 14.44.35207 + Windows SDK 10.0.26100.0) — see the R1 record below.

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

These could not be frozen from repository code alone. Items 1-3 have since been
collected by R1 and are recorded below; item 4 remains outstanding.

1. ~~**R1 toolchain preflight**~~ — **COLLECTED**. CUDA 12.4 compiled with MSVC 14.44.35207 and Windows SDK 10.0.26100.0. 14.44 was retained on proof, not assumption, and 14.39 proved unnecessary.
2. ~~**Real v2 host observation**~~ — **COLLECTED**. Compute capability, PCI identity and memory availability directly observed.
3. ~~**Torch cu124 wheel inspection**~~ — **COLLECTED**. Windows wheel metadata, dependency markers and CUDA DLL inventory confirmed.
4. **MMCV reproducibility experiment:** build the CUDA MMCV wheel twice from a clean controlled build environment before C3; if byte reproducibility is not achievable, an ADR must define a controlled hash-pinned binary-input model. **Still outstanding — a C2/C3 activity.**

### Gate C1R — repository side — PASSED AND MERGED

- all five exact-head workflows green on `c80ce10`;
- Windows CPU lock, `runtime.json` and the component declaration byte-identical to `main`;
- no `windows-x86_64-cuda.lock`, Runtime Pack or CUDA component requirement introduced;
- no runtime variant promoted; `windows-x86_64-cuda` remains `pending-hardware-qualification`;
- the build contract was, at that merge, fail-closed at `pending-r1-preflight` (R1 has since verified and frozen it).

Merging this foundation is **not** a CUDA qualification of any kind.

### Gate R1 / pre-C2 — empirical — PASSED

All three items are collected, and the build contract has left
`pending-r1-preflight`:

- the exact CUDA 12.4 + MSVC 14.44.35207 + SDK 10.0.26100.0 toolchain, proven by
  compiling a trivial `.cu` file and frozen into both the build contract and the
  offline catalogue — **collected**;
- the real v2 host observation with its evidence SHA-256 retained — **collected**;
- the real `torch 2.6.0+cu124` cp312 win_amd64 wheel inspection — **collected**.

`tools/verify_repo.py` therefore no longer refuses a Windows CUDA lock on
toolchain grounds. C2 remains gated on independent review of this evidence, not
on the verifier.

### R1 — 2026-09-18 — PASSED on the controlled Windows CUDA host

R1 was executed manually on the actual Windows CUDA machine, the two hosted
attempts below having established that it could not be run from a Linux
session. All three pre-C2 evidence items are now collected.

**Toolchain — the empirical result matters.** CUDA 12.4 compiled successfully
with MSVC 14.44.35207. The standing R1 risk — that CUDA 12.4's host-compiler
allowlist would reject the 14.44 toolset this repository standardises on — is
**disproven for this controlled host/toolchain combination**. MSVC 14.39 was
therefore never required, was not tested, and is not adopted.

| CUDA Toolkit | MSVC toolset | Compiler | Windows SDK | Arch | Result |
| --- | --- | --- | --- | --- | --- |
| 12.4 (`V12.4.99`) | 14.44.35207 | 19.44.35222 | 10.0.26100.0 | `-arch=sm_75` | **passed**, exit code 0, object produced (39957 bytes) |

The probe compiled a real translation unit containing
`extern "C" __global__ void mavi_probe() {}` under
`MMCV_WITH_OPS=1`, `FORCE_CUDA=1`, `TORCH_CUDA_ARCH_LIST=7.5+PTX`, against
source head `426195ddf72ae18b31f8d0faa7bb1a50ea906720`. CUDA Toolkit home:
`C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4`. Observation
schema `mavi-windows-cuda-toolchain-observation-v1`.
`--allow-unsupported-compiler` was not used.

**Fresh v2 host observation** — schema `mavi-windows-cuda-host-observation-v2`,
raw evidence SHA-256
`cb7031911e2e71c4990b72260a2f2df974e68d44725d9702b07401a6e43132d4`.
Sanitized facts: Windows 11 x64; NVIDIA GeForce GTX 1650 Ti; PCI bus ID
`00000000:01:00.0`; VRAM 4096 MiB total, ~3935 MiB free, 0 MiB used at
observation; driver `576.83`; driver-advertised CUDA compatibility `12.9`;
driver mode WDDM; MSVC 14.44.35207 / compiler 19.44.35222 / SDK 10.0.26100.0;
Ninja 1.12.1. The record keeps `qualification.status = observation-only` and
`windowsCudaRuntimePackQualified = false`. The raw observation carries
workstation-specific GPU identity and remains local; the GPU UUID is not in Git.

**Real Windows cu124 Torch wheel** —
`torch-2.6.0+cu124-cp312-cp312-win_amd64.whl`, 2,532,302,369 bytes, SHA-256
`3313061c1fec4c7310cf47944e84513dcd27b6173b72a349bb7ca68d0ee6e9c0`, acquired
from the intended cu124 index. `inspect_windows_cuda_torch_wheel.py` returned
`passed`: version `2.6.0+cu124`; every `nvidia-*` requirement and Triton are
guarded by Linux-only markers, so none applies on Windows;
`suspiciousWindowsCudaDependencies` empty; and `torch/lib` carries the expected
CUDA runtime families (`cudart64_12`, `cublas64_12`, `cublasLt64_12`, cuDNN 9,
`cufft64_11`, `curand64_10`, `cusolver64_11`, `cusparse64_12`, NVRTC).

That last point is the one the offline design rests on, and it is now evidence
rather than assumption: the Windows cu124 wheel does carry its own CUDA runtime
libraries, so no CUDA Toolkit is required on a runtime host. The wheel is not
committed and no wheelhouse was assembled.

**Contract frozen.** `config/vision/windows-cuda-development-build-v1.json`
moves from `pending-r1-preflight` to `verified`, recording the exact observed
identities and the evidence that produced them; the offline catalogue's
placeholder values are replaced with the same identities, which `verify_repo`
requires to agree.

**Consequence to understand before C2.** The CUDA-lock gate was blocking on the
toolchain being unverified. That condition is now satisfied, so the gate no
longer refuses a Windows CUDA lock. Nothing else opened: no lock, Runtime Pack
or wheelhouse exists, `windows-x86_64-cuda` remains
`pending-hardware-qualification` and the runtime profile remains `partial`.
**C2 has not started and requires independent review of this evidence first.**

### Pre-C2 independent review — corrections to the lock gate

An independent cold review of the frozen state audited `tools/verify_repo.py`
against the negative cases the gate exists to stop, and found two fail-opens in
the freeze logic itself.

- `_frozen_toolchain_value` was a deny-list over the placeholder words
  `pending`, `tbd` and `unknown`. Values such as `TODO`, `n/a`, `FIXME`, `-` or
  `0` therefore counted as frozen identities and, with a matching catalogue,
  would have admitted a Windows CUDA lock. Identities are now validated by
  shape — `\d+\.\d+` for the CUDA Toolkit, `\d+\.\d+\.\d+` for the MSVC
  toolset, `\d+\.\d+\.\d+\.\d+` for the Windows SDK — so anything that is
  not a version of the expected form fails closed.
- the contract/catalogue agreement check was skipped when the catalogue's
  `buildToolchain` was absent entirely, so a verified contract could coexist
  with a catalogue carrying no identity at all. A verified contract now
  requires the catalogue identity whether or not a lock exists.

The contract's top-level `status` was reviewed and is **descriptive only**. The
authoritative proof is `toolchain.verificationStatus` plus the frozen
identities; a test pins that a verified-looking `status` over a pending
toolchain still refuses a lock, and the contract carries a `statusNote` saying
so. No state machine was introduced around `status`.

### R1 attempt 1 — 2026-09-18 — NOT EXECUTED (no controlled build host reachable)

R1 was attempted from the hosted engineering session at
`feature/windows-cuda-pre-c2`. None of the three evidence items could be
collected, because that session is not the controlled Windows CUDA host and
cannot reach the PyTorch CUDA index:

| Evidence item | Requirement | Observed | Result |
| --- | --- | --- | --- |
| Toolchain preflight | Windows + CUDA Toolkit 12.4 + MSVC | `platform.system()` = `Linux`; `nvcc`, `cl.exe`, `vswhere.exe` all absent | not executed |
| Fresh v2 host observation | the NVIDIA GPU machine | `nvidia-smi` absent; no `/dev/nvidia*` | not executed |
| Torch cu124 wheel inspection | `download.pytorch.org` | `403` CONNECT, recorded by the session proxy as a policy denial | not executed |

No substitute was used. In particular the wheel was **not** fetched from PyPI:
`torch==2.6.0` there is a different artefact from `2.6.0+cu124` on the cu124
index, so inspecting it would answer a different question while appearing to
satisfy this gate.

**R1 therefore remains open. No toolchain has been proven, and the build
contract stays at `pending-r1-preflight`.** Nothing in the contract or the
offline catalogue was changed.

### R1 preflight tooling — corrected before first use

Reviewing `tools/vision/verify_windows_cuda_toolchain.py` before trusting its
result found it untested and carrying four defects that would have corrupted
the R1 decision. All four are fixed with focused tests
(`src/vision/tests/test_windows_cuda_toolchain_preflight.py`):

- compile failures were a single opaque code, so an environment problem could
  have been read as a host-compiler rejection — the one failure that justifies
  changing toolset. Failures are now classified, and a missing `nvcc` is
  distinguished from a missing host compiler;
- the probe architecture was hardcoded to `sm_75` rather than derived from the
  contract, so it could have proven a target other than the one being frozen;
- the required build environment was read from the contract and then ignored in
  favour of a hardcoded copy, with the same consequence;
- the observation named neither the revision it was collected against nor when,
  so it could not be bound to a tree.

Behaviour against the current contract is unchanged, and
`--allow-unsupported-compiler` remains absent and is asserted absent by test.

### R1 attempt 2 — 2026-09-18 — NOT EXECUTED (same blocker, re-verified)

R1 was attempted again from the hosted engineering session at PR #49
(`44f2105`). The blocker was re-verified rather than assumed, and is unchanged:
`platform.system()` is `Linux`; `nvcc`, `cl.exe`, `vswhere.exe` and
`nvidia-smi` are all absent; there are no NVIDIA device nodes; and
`download.pytorch.org` still answers `403` to `CONNECT` as a policy denial.
Running the preflight here returns its fail-closed
`cuda_toolchain_windows_required`, which is correct behaviour.

No toolchain was tested, so **no statement is made about whether MSVC 14.44
works**. That question is still open and is still the gate.

The attempt was used instead to close two remaining gaps in the evidence the
gate must produce — see below. The build contract, offline catalogue, locks and
CPU artefacts are untouched.

### R1 preflight tooling — evidence completeness

Beyond the four correctness defects fixed before attempt 1, the preflight did
not record what the R1 procedure requires an operator to capture: the compile
exit code and output were absent from a passing observation, and on failure the
compiler output was truncated into an exception message.

That failure record is the load-bearing one. The rejection of MSVC 14.44 is
exactly what justifies testing 14.39, so it has to be auditable rather than
summarised. The observation now carries a `compile` block on both outcomes:

- the exact `nvcc` command and its exit code;
- full stdout and stderr;
- the probe source and its SHA-256;
- the produced object's size and SHA-256 on success.

A failed run also writes its structured evidence to `--output`, so a blocked R1
leaves an artefact behind. The default evidence filename is gitignored
alongside the host observation, because the record contains build-host paths.

### R1 execution procedure — for the controlled Windows build host

**Executed 2026-09-18; it passed at step 4 on the first toolset tried.** Retained as the reproducible procedure for any future host or toolchain revision, not as outstanding work.

Run on the Windows CUDA machine, from the repository root, recording all output:

1. Observe, before changing anything: `ver`; `wmic os get caption,version,osarchitecture`;
   `nvcc --version`; `nvidia-smi`; and
   `"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -products * -format json`
   to enumerate installed MSVC toolsets and Windows SDKs. Record exact
   `VCToolsVersion` values. Note that the CUDA level `nvidia-smi` reports is the
   driver's maximum, not the installed Toolkit version `nvcc` reports.
2. Open a developer shell for the **preferred/currently available** toolset
   first — do not pre-select 14.39 because this plan mentions it:
   `vcvarsall.bat x64 -vcvars_ver=14.44 -winsdk=<observed SDK>`.
3. Set `MMCV_WITH_OPS=1`, `FORCE_CUDA=1`, `TORCH_CUDA_ARCH_LIST=7.5+PTX`.
4. `python tools/vision/verify_windows_cuda_toolchain.py --output windows-cuda-toolchain-observation.json`
   (gitignored; it records build-host paths). Keep the artefact from a failed
   attempt too — it is the evidence that justifies trying another toolset.
5. On failure, read the emitted code before acting. Only
   `cuda_toolchain_host_compiler_unsupported` justifies trying another toolset;
   `cuda_toolchain_host_compiler_not_found`, `cuda_toolchain_headers_unavailable`
   and `cuda_toolchain_nvcc_not_found` are environment problems to fix in place.
6. Only if 14.44 is genuinely rejected, and 14.39 is already installed, repeat
   from step 2 with `-vcvars_ver=14.39`. If 14.39 is not installed, report the
   exact component required and why before altering the machine.
7. Never `--allow-unsupported-compiler`. A forced compile is not a qualified
   toolchain.

Then run `python tools/vision/probe_windows_cuda_host.py --output
windows-cuda-host-observation.json` (gitignored; keep the raw UUID local, record
its SHA-256), and inspect the real wheel with
`tools/vision/inspect_windows_cuda_torch_wheel.py --wheel <wheel>`, acquiring it
only from `https://download.pytorch.org/whl/cu124` and never from PyPI.

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

### C2 tooling and execution order

The tooling below exists and is tested; the artefacts it operates on cannot be
produced from a hosted Linux session, so C2 execution belongs on the controlled
Windows build host. Run the reproducibility experiment **early** -- before
investing in the rest of the closure -- because a negative result changes C3's
identity contract rather than just delaying it.

1. **Acquire Torch and torchvision** from the dedicated cu124 index, never
   `--extra-index-url` and never a PyPI fallback: a bare `2.6.0` is a different
   artefact from `2.6.0+cu124`. Record each download's index URL.
2. **Build MMCV twice, from clean trees**, at commit
   `57c4e25e06e2d4f8a9357c84bcd24089a284dc88`, under `MMCV_WITH_OPS=1`,
   `FORCE_CUDA=1`, `TORCH_CUDA_ARCH_LIST=7.5+PTX`, `MAX_JOBS=2`, with the R1
   toolchain. Then compare them:

   ```
   python tools/vision/compare_wheel_reproducibility.py \
       --left build-a/mmcv-....whl --right build-b/mmcv-....whl \
       --output mmcv-reproducibility.json --require semantically-identical
   ```

   The verdict decides C3's identity contract:
   - `byte-identical` -- C3 may enforce exact hash identity on rebuild;
   - `semantically-identical` -- the installed members are equal and only the
     container varies; C3 enforces the documented deterministic member
     identity, and the variance source must be recorded;
   - `divergent-*` -- stop. Identify the variance source before proceeding;
     an ADR is required if it proves irreducible.

   Note the tool reports absolute build paths embedded in **both** wheels.
   Identical embedded paths still defeat relocatable reproduction: two builds
   from the same directory will be byte-identical and still not reproducible
   elsewhere.
3. **Assemble the wheelhouse** and record what each artefact is and where it
   came from:

   ```
   python tools/vision/build_wheelhouse_manifest.py \
       --wheelhouse wheelhouse --platform-variant windows-x86_64-cuda \
       --python-version 3.12.10 --origins origins.json \
       --output wheelhouse-manifest.json
   ```

   `origins.json` maps each wheel filename to `{"kind": "index", "indexUrl": ...}`
   or `{"kind": "local-build", "sourceRepository": ..., "sourceCommit": ...,
   "buildToolchain": ...}`. The manifest refuses a wheelhouse it cannot fully
   account for: an undeclared wheel, an origin naming an absent wheel, a stray
   file, a nested directory, a symlink, a duplicate distribution, or CPU Torch
   under a CUDA variant.
4. **Freeze the lock** with `freeze_offline_lock.py`, which owns the transitive
   dependency closure check, then regenerate and compare to prove determinism.
5. **Prove the offline install** in a clean venv with
   `--no-index --only-binary=:all: --require-hashes`, network blackholed, then
   `pip check`, then import `torch`, `torchvision`, `mmengine`, `mmdet`, `mmcv`
   and `mmcv.ops`.
6. **Prove the native ops are real.** A successful `pip wheel` is not evidence
   that CUDA ops were compiled. `tools/vision/verify_windows_cuda_runtime.py`
   executes `mmcv.ops.nms` on device and asserts the result is on CUDA; it needs
   `--resolved-config` and records which physical card ran it. If the build host
   has no GPU, record the build/native proof as complete and the hardware
   execution as still pending -- do not conflate them.

The Runtime Pack's `--native-abi` is **not** hand-typed. It is the `nativeAbi`
field of `config/vision/windows-cuda-development-build-v1.json`, derived from
the verified toolchain by `build_runtime_pack.derive_native_abi` and pinned by
test:

`win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75`

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

### C4 tooling and execution order

The `qualified-development-hardware` state may only be written from an evidence
bundle assembled by `tools/vision/build_development_hardware_evidence.py`.

Produce the three artefacts first, on the Development machine:

```
python tools/vision/probe_windows_cuda_host.py --sanitized \
    --output host-observation.json
python tools/vision/verify_windows_cuda_toolchain.py \
    --contract config/vision/windows-cuda-development-build-v1.json \
    --output toolchain-observation.json
python tools/vision/verify_windows_cuda_runtime.py --device-index 0 \
    --resolved-config src/vision/runtime/mmdetection-phase1-v1/rtmdet_m_resolved.py \
    --host-observation host-observation.json \
    --output runtime-verification.json
```

`--sanitized` is not optional. Without it the host observation contains the raw
GPU UUID, which may never be committed or shown, so the SHA-256 the bundle
records would name a file nobody can ever recompute. The evidence builder
refuses an observation that still carries a raw `uuid`.

Then assemble the bundle:

```
python tools/vision/build_development_hardware_evidence.py \
    --host-observation host-observation.json \
    --toolchain-observation toolchain-observation.json \
    --runtime-verification runtime-verification.json \
    --source-head-sha <40-hex head of the source tree under test> \
    --captured-at-utc <YYYY-MM-DDTHH:MM:SSZ> \
    --operator-reference <workstation or operator label> \
    --device-index 0 \
    --output development-evidence.json
```

`--device-index` must be the CUDA ordinal the run used; it defaults to 0 and
must match `deviceIndex` in the runtime verification. Refusal prints
`{"ok": false, "code": ...}` and exits 2, and an existing `--output` path is
never overwritten (`development_evidence_output_exists`).

A failed runtime verification also writes its record to `--output`, with
`result: "failed"`, the failure code and its detail, and both execution flags
`false`. C7's entire output is failures, so the tool that proves on-device
execution has to be able to record one; the evidence builder refuses any record
that is not `passed`, so a failure artefact can never be mistaken for a
qualification. All of these filenames are gitignored.

What the builder requires, and why:

- **on-device execution.** `mmcvNmsExecutedOnCuda` and
  `torchMatmulExecutedOnCuda` must both be `true`. A wheel that compiled is not
  a run, and no Development qualification exists without one.
- **one physical card, named by identity.** The run and the host observation
  must carry the same `gpuUuidSha256`, the same driver version, and agree on
  total memory to within 64 MiB. Identity is never inferred from the CUDA
  ordinal's position in nvidia-smi order, and never from the device's marketing
  name: the two producers may spell one card's name differently, and
  `gpu_identity.py` binds on UUID for the same reason.
- **one set, produced in order.** The run records the SHA-256 of the host
  observation it was produced against, and the builder requires it to be the
  observation it was handed, so a stale or borrowed inventory is detectable.
- **allocation consistent with execution.** Peak device allocation must be
  above zero and reserved memory at least allocated: work done on the device
  means the allocator saw it.
- **a schema-valid observation.** The host observation is validated against
  `tools/vision/windows-cuda-host-observation.schema.json`, whose
  `additionalProperties: false` is what actually keeps workstation-specific
  fields out of a record this tooling digests and vouches for.
- **the same revision and the same target.** The toolchain observation's
  `sourceHeadSha` must equal `--source-head-sha` and its `targetArchitecture`
  must match the card's, so neither is the operator's unchecked word.
- **kernels for this card.** `sm_XY` must appear in `torchCudaArchList`; a run
  that fell back to PTX JIT does not qualify the built artefact.
- **stated identities.** Every toolchain and runtime identity field must be
  present, non-empty text. Torch and torchvision must carry a local build tag
  (`+cu124`); a bare `2.6.0` is a different artefact.

`gpuUuidSha256` is a **domain-salted** digest, not a plain SHA-256 of the UUID.
The single definition lives in `tools/vision/host_gpu_digest.py`; a verifier
computing a plain SHA-256 would wrongly conclude the evidence was forged.

**What this tooling does and does not prove.** It proves the three artefacts
are one consistent set, produced in order, and not detachable from the record
that summarises them: a stale, borrowed or internally contradictory set is
refused, and the bundle digest binds the artefacts to the revision, capture
time and operator. It does **not** prove an artefact was not fabricated. Every
producer runs offline on the operator's own machine with no signing root, and
the identity digest the run must match is present in the sanitised observation
the operator holds, so a determined operator can still hand-write a consistent
set. Development hardware qualification therefore rests on the operator's
integrity plus these consistency checks -- which is precisely why ADR-009 keeps
it a separate state that can never satisfy Production, where the evidence is
CI-produced and the operator is not in the loop.

The output's `variantPatch` is the complete `qualified-development-hardware`
entry for `platformVariants["windows-x86_64-cuda"]` in
`src/vision/runtime/mmdetection-phase1-v1/runtime.json` — status,
`resolvedConfigSha256`, `pythonIdentity`, `binaryVersions` — to which
`developmentEvidence` from the same file is added. It is machine-generated on
purpose: ADR-009 requires those identities alongside the evidence block, and
hand-typing them at the last step would reintroduce exactly the fabrication the
rest of this tooling prevents. A test validates both against the real consumer
schema in `mavi_vision.runtime.qualification`.

`evidenceBundleSha256` is recomputable from the delivered file alone: blank that
field, re-serialise the whole record canonically (`sort_keys`, `,`/`:`
separators, UTF-8) and hash. It therefore binds the three artefact digests, the
source revision, the capture time and the operator together.

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

### C6 tooling and execution order

C6's output is an evidence bundle, not a report that it went well. Record each
run as a `mavi-windows-cuda-development-e2e-run-v1` document and assemble them
with `tools/vision/build_development_e2e_evidence.py`:

```
python tools/vision/build_development_e2e_evidence.py \
    --development-evidence development-evidence.json \
    --run explicit-cuda=run-explicit-cuda.json \
    --run auto-cuda=run-auto-cuda.json \
    --run explicit-cpu=run-explicit-cpu.json \
    --run restart-recovery=run-restart-recovery.json \
    --run cuda-oom-recovery=run-cuda-oom-recovery.json \
    --source-head-sha <40-hex head of the source tree under test> \
    --captured-at-utc <YYYY-MM-DDTHH:MM:SSZ> \
    --operator-reference <workstation or operator label> \
    --output development-e2e-evidence.json
```

The five case IDs are exactly the required set: one per thing the list above
asks to be proven, and the bundle is refused if any is missing or if a case
nobody asked for is supplied. Each run must reach `Processed` at 100% with
detections persisted, carry provenance agreeing with the run, and name the
media by SHA-256.

The rules that matter most:

- **no silent GPU-to-CPU fallback.** Policy, resolved device and reason code go
  through `validate_device_resolution_wire_relationship` -- the same function
  the wire contract uses, not a restatement that could drift -- and a case that
  exists to prove CUDA is refused if it reports `cpu`. A legitimate Auto
  fallback is a real result but does not satisfy the `auto-cuda` case;
- **a CUDA run must have touched the GPU.** On-device MMCV native ops, a peak
  device allocation above zero, and nvidia-smi showing more device memory in use
  during the run than before it;
- **provenance stays `unverified`.** Development never inherits the release's
  verified label, so a run record claiming `verified` did not come from this
  runtime;
- **the OOM and restart cases must have exercised what they are named for.**

Timing is carried for engineering characterisation only. The bundle says so in
the record itself, and this tool never compares an elapsed time against a
threshold, because no Production bound may be derived from Development hardware.

The bundle is bound to the C4 hardware evidence by digest and must name the same
source revision, so a C6 run cannot be attached to a qualification of something
else. `evidenceBundleSha256` is recomputable the same way as C4's: blank the
field, re-serialise the record canonically as UTF-8, hash.

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

### C7 tooling and execution order

The matrix is declared as data in `tools/vision/build_failure_matrix_evidence.py`
-- 33 cases, each naming the invariant it defends, the expected outcome, whether
retry is permitted and whether fallback is permitted. Print it before the
session to prepare the run sheet:

```
python tools/vision/build_failure_matrix_evidence.py --print-matrix \
    --scope hardware --source-head-sha x --captured-at-utc x \
    --operator-reference x
```

Record each case as a `mavi-windows-cuda-failure-case-v1` document, then
assemble:

```
python tools/vision/build_failure_matrix_evidence.py --scope hardware \
    --case auto-pack-absent=case-auto-pack-absent.json \
    ... one --case per declared case ... \
    --source-head-sha <40-hex head of the source tree under test> \
    --captured-at-utc <YYYY-MM-DDTHH:MM:SSZ> \
    --operator-reference <workstation or operator label> \
    --output failure-matrix-evidence.json
```

**Scope is explicit and never implied.** `--scope linux-observable` covers the
23 cases that need no GPU and may not carry a hardware case; `--scope hardware`
requires all 33. Neither is hardware qualification: the bundle says so in its
own note, and a linux-observable bundle asserts nothing about any GPU.

The distinction the matrix exists to protect is between a **permitted** fallback
and a **silent** one:

- the eight `auto-*` cases are exactly the closed vocabulary's Auto-CPU reasons,
  one case each, so no reason the runtime can emit goes unexercised. Each must
  land on `cpu`, carry its declared reason, and be both logged and persisted in
  provenance -- an unlogged fallback is a silent one whatever its reason;
- every `explicit-cuda-*` case is fail-closed. An observation reporting any
  device, any resolution reason, or completed processing is the defect the case
  exists to detect, not the evidence;
- the two `*-recovered` cases must show more than one attempt and a real
  recovery, and no fail-closed case may claim recovery.

The reason vocabulary is imported from `mavi_vision.common.control_plane`, never
restated, so the matrix cannot certify against codes the runtime no longer
emits. A test asserts the eight fallback cases are exactly
`AUTO_CPU_DEVICE_RESOLUTION_REASONS`.

Ten cases require the real host: the four that need a present or absent physical
device, the driver and architecture refusals, the physical-GPU identity refusal,
`mmcv.ops` failing on device, and the two recovery cases. The other 23 are
exercisable on any machine and should be recorded before the host session, so
the session spends its time on what only it can do.

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

**R1 has passed** and the pre-C2 empirical gate is complete. The verified
toolchain is CUDA 12.4 + MSVC 14.44.35207 + Windows SDK 10.0.26100.0; MSVC 14.39
is not required. The evidence is recorded above and frozen in the build
contract.

**C2, C3 and C4 repository tooling is landed and tested**, and its execution
order is documented in the phase sections above. No C2 artefact has been
produced: nothing in this branch acquires wheels, builds MMCV CUDA, freezes a
lock or promotes any qualification state, and none of that can happen from a
hosted Linux session. The tooling is what a controlled Windows host will run;
it exists first so the host session executes a reviewed procedure rather than
improvising one, and so the artefacts it produces are checked by code rather
than read by eye.

The next step remains **independent review of the R1/pre-C2 evidence**, on
Draft PR #49, before C2 execution begins on the Windows host.

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
