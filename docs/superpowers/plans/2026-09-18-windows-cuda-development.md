# Windows CUDA Development Enablement Plan

**Date:** 2026-09-18  
**Base:** `main@9b0b88f5c9d20ddfa8c4e835e454d24c69921b84`  
**C1R merged to `main`:** PR #48 head `c80ce10b823443230e316fc2978116c73d703c8f`, merge commit `02257793556026a37238f06c13755c87da35f141`  
**Active branch:** `feature/windows-cuda-pre-c2` (from `main@0225779`; reconciled onto `main@bdf834a` on 2026-09-20)  
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
4. **MMCV reproducibility experiment:** build the CUDA MMCV wheel twice from a clean controlled build environment before C3. **Collected, with a finding:** four builds, not byte-reproducible. The ADR condition was answered by review rather than by an ADR — identity already binds the canonical wheel's SHA-256. See "Consequence for C3 identity — reviewed, no change required".

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
**As of R1, C2 had not started and required independent review of this evidence first.** That review is complete and the build half of C2 has since run; see "Current execution point".

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
- `MAX_JOBS=2`;
- `DISTUTILS_USE_SDK=1`;
- the exact toolchain frozen by R1.

It must also pin `setuptools==80.10.2`. Three of these were established
empirically on the host and are recorded in the runbook with the failure each
one prevents: `--no-deps` on the Torch/torchvision download (without it the
cu124 index deposits NumPy and Pillow into the wheelhouse and contaminates the
closure), the setuptools pin (MMCV 2.1.0 imports `pkg_resources`, which
setuptools 84 no longer ships), and `DISTUTILS_USE_SDK=1` (PyTorch 2.6 aborts
the extension build when a Visual Studio developer environment is already
active). The MMCV wheel build is
`pip wheel . --no-build-isolation --no-deps`.

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
       --output mmcv-reproducibility-ab.json \
       --require semantically-identical-after-native-normalization
   ```

   The verdict decides C3's identity contract:
   - `byte-identical` -- C3 may enforce exact hash identity on rebuild;
   - `semantically-identical` -- the installed members are byte-equal and only
     the container varies;
   - `semantically-identical-after-native-normalization` -- the installed
     members are **not** byte-equal, and every byte by which they differ was
     proved to lie inside a documented build-metadata field that the report
     names. **This is the observed R1 outcome** (see below);
   - `divergent-*` -- stop. Identify the variance source before proceeding;
     an ADR is required if it proves irreducible.

   Then compare the **intermediate objects**, which the linked image's own
   variance would otherwise hide:

   ```
   python tools/vision/compare_native_object_trees.py \
       --left obj-a --right obj-a2 \
       --output mmcv-objects-a-a2.json --require normalized-identical
   ```

   Note the tool reports absolute build paths embedded in **both** wheels.
   Identical embedded paths still defeat relocatable reproduction: two builds
   from the same directory will be byte-identical and still not reproducible
   elsewhere.

#### What the host measured, and the acceptance model it forces

The first host session built the wheel four times: A and B from two separately
cloned trees, then A2 and A3 from the *same* tree and the same virtual
environment after a clean rebuild. All four wheels have different SHA-256
values and sizes within ~200 bytes of each other. The MMCV CUDA wheel is
therefore **not byte-reproducible** on this toolchain, and this plan does not
claim it is.

A-versus-B additionally embeds each tree's absolute source root roughly 463
times in `_ext.cp312-win_amd64.pyd`. That is a real non-relocatability finding;
it is also why A-versus-B cannot answer whether the compiler agrees, and why
the A2-versus-A3 object comparison exists.

Across A2 and A3, all 136 intermediate objects differ by raw hash. Two were
inspected by hand: a CUDA object differing in 2 bytes that reduced to zero
after the COFF `TimeDateStamp` at offset 4:8 was zeroed, and an 18 MB `/bigobj`
CPU object differing at offsets 8, 9, 36 and 37.

**Two corrections to that reading, both now enforced by the tooling.**

*The sample is not the population.* Two of 136 inspected by hand establishes the
claim for two. `compare_native_object_trees.py` runs the same reduction over
every object and fails on any one that does not reduce, which is what the gate
needs.

*Offset 36 is not a timestamp.* In the documented `ANON_OBJECT_HEADER_BIGOBJ`
layout, 8:12 is `TimeDateStamp` and 36:40 is `MetaDataSize` (LLVM's reader calls
it `unused3`). Normalising 36:40 alongside the timestamp reached byte equality
by excusing a field whose meaning nobody had established. The pattern is
suggestive -- both differences sit in the low half of a DWORD, which is what two
timestamps minutes apart look like -- but suggestive is not established.
`native_binary_metadata.py` therefore declares `MetaDataSize` and
`MetaDataOffset` as *observed, not normalised*: their values are decoded into
the report and they **block** an equivalence verdict. One host run prints the
two DWORDs and settles it; until then this is an open question, not a closed one.

**The acceptance model, after the A2/A3 measurement.** The hope that repeated
builds would reduce to named metadata was tested and is **false**. A2 versus
A3 -- same tree, same venv, same recipe -- differ in **183,339 bytes** of
`_ext.cp312-win_amd64.pyd`, with only `pe.coff.TimeDateStamp` and
`pe.debug[0].TimeDateStamp` accounted for. Verdict `divergent-content`,
classification `unexplained-native-difference`. Roughly 0.7% of a 27 MB image
at identical file length; not a timestamp. The likely cause is `/GL` + `/LTCG`,
which moves code generation to link time where it is not deterministic between
runs, but that is **not established** and this plan does not assert it.

So C2 Development does **not** gate on reproducibility in any form. It accepts:

- one canonical MMCV CUDA wheel, chosen and named, with its exact SHA-256;
- the exact source, toolchain and dependency recipe recorded;
- a clean offline installation;
- successful runtime import and native CUDA operator validation.

Repeated-build comparison is retained as **diagnostic evidence on file**.

**Why that is defensible.** Non-reproducibility is a property of the build
*process*. Exactly one wheel is pinned, installed and executed on the device,
and that wheel is what C2.5 and C4 validate. Two builds disagreeing says
nothing about whether the pinned one works.

**The accepted cost, named so it is not rediscovered later.** The canonical
wheel cannot be reconstructed if lost -- a rebuild is a different artefact
needing a new SHA-256, a new lock, a new pack identity and a re-run of C2.5 and
C4. It cannot be verified by rebuilding and comparing. Cross-build crash
analysis is unavailable. Mitigation is operational: archive the wheel off the
build host and treat it as a controlled input.

**The analyser is not relaxed to match.** It still reports
`unexplained-native-difference` and still refuses to call these wheels
equivalent, because they are not. What changed is what C2 requires, not what
the tool is willing to say -- a green verdict elsewhere is worth something only
because it stays honest here. A native member that will not parse is a refusal,
not a pass, and no member is excused by filename.

**Production is unaffected and may demand more.** Stronger reproducibility and
provenance requirements remain open for Production qualification; Development
evidence never satisfies a Production gate.
3. **Derive the closure, then assemble the wheelhouse.** The acquisition list
   is produced by `write_requirements_projection.py` from
   `src/vision/pyproject.toml`, never typed. A hand-written subset resolved
   `Pillow==12.3.0` against a frozen `pillow==11.3.0` on the host and omitted
   `av`, `trackers`, `supervision` and eleven other pinned roots. Acquire with
   `pip download -r <projection> --only-binary=:all: --find-links <wheelhouse>`
   so the `+cu124` Torch and the canonical MMCV wheel already present are
   reused rather than replaced from PyPI. Then record what each artefact is
   and where it came from:

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

**What BUILD-VERIFIED asserts.** That the frozen toolchain produced a working
CUDA wheel, that one named wheel was selected as canonical and archived, that
its SHA-256 and full build recipe are recorded, that the closure installs
offline, and that the runtime imports and executes native CUDA operators. It
asserts **nothing** about reproducibility: repeated builds of this recipe are
not reproducible, and the reproducibility reports are attached as diagnostic
evidence rather than as a condition of the gate.

#### Deterministic-build flags — reviewed, NOT adopted in R1

The obvious response to a non-reproducible wheel is to add MSVC's `/Brepro` and
force the timestamps to agree. The review says no, for R1. The reasoning is
recorded here because "we never tried it" and "we tried it and it does not
apply" are different states, and the next reader should not have to redo the
investigation.

Each claim below is marked **[documented]** with its source, or **[unverified]**
where only a host experiment can settle it. Nothing here is asserted from
recollection.

**What is documented.**

- `IMAGE_DEBUG_TYPE_REPRO` (type 16) is a real PE convention: the entry marks an
  image whose date/time fields carry bits of a content hash rather than a build
  time, and its raw data is either empty or a length-prefixed hash.
  **[documented — Microsoft PE/COFF specification]**
- `/PDBALTPATH:%_PDB%` replaces the absolute PDB path the linker writes into the
  image with the bare filename. It does not move the PDB and does not touch the
  CodeView GUID or Age. **[documented — MSVC linker reference]**
- `CL`/`_CL_` and `LINK`/`_LINK_` prepend and append options to every cl.exe and
  link.exe invocation. These are the only supported way to inject a flag into
  this build without editing the pinned MMCV commit.
  **[documented — MSVC environment-variable reference]**
- nvcc forwards host options through `-Xcompiler`. **[documented — nvcc guide]**
- nvcc `--frandom-seed` is documented as producing deterministically identical
  PTX and object files by fixing the seed behind generated symbol names.
  **[documented — nvcc guide; presence in CUDA 12.4 specifically is unverified]**

**What is not documented.**

- `/Brepro` appears nowhere in Microsoft's compiler or linker option reference,
  for either `cl` or `link`. It is an **undocumented, unsupported switch**.
  Its only documented footprint is LLVM's reimplementation of it and the PE
  spec's REPRO debug type. **[documented as absent]**
- What MSVC 14.44 actually writes into a `.obj` `TimeDateStamp` under `/Brepro`
  — a path hash, zero, or `0xFFFFFFFF` — is **[unverified]**. So is whether
  MSVC's linker emits the type-16 entry at all.
- MSVC is **not** known to make the CodeView RSDS GUID and Age deterministic.
  The widely quoted "GUID is calculated deterministically" text describes the
  .NET/Roslyn convention, not native MSVC. The existence of third-party
  post-link canonicalisers for MSVC PE+PDB pairs is circumstantial evidence the
  other way. **[unverified, probably false]**

**Why it is not adopted now.**

1. **Two of its three usual rationales are already moot here.** setuptools links
   release extensions with `/INCREMENTAL:NO`, so the `/Brepro`-versus-
   incremental-linking conflict cannot arise; and `pip wheel` builds non-debug,
   so there is no PDB and no CodeView record in `_ext.cp312-win_amd64.pyd` for
   `/PDBALTPATH` to clean up. **[documented — setuptools `_msvccompiler`
   defaults]** This also predicts that the ~463 embedded source-root strings the
   host observed are `__FILE__`-derived, not a PDB path — which is a testable
   prediction, not a conclusion.
2. **It collides with the configuration this build actually uses.** The same
   setuptools defaults compile with `/GL` and link with `/LTCG`. Under
   link-time code generation the compiler does not write the object timestamps
   `/Brepro` targets, and `/Brepro` is reported to be ignored or unreliable
   there. **[the setuptools flags are documented; the `/Brepro`-under-LTO
   behaviour is unverified]** Adopting a flag that is probably a no-op in our
   configuration, to fix a problem we have already measured and characterised,
   is the worst kind of green.
3. **It cannot be injected cleanly.** MMCV 2.1.0 hardcodes
   `extra_compile_args['cxx'] = ['/std:c++17']` and never reads the environment
   for it; the only env hook is `MMCV_CUDA_ARGS`, which reaches nvcc only and
   arrives as a single list element that PyTorch's Windows path then quotes as
   one token. `extra_link_args` is empty and unreachable. **[documented — MMCV
   setup.py at the pinned commit, PyTorch 2.6.0 `cpp_extension`]** The remaining
   route is `set CL=/Brepro` and `set LINK=/Brepro`, which is supported but
   applies to every cl.exe in the build including the ones nvcc spawns.
4. **It cannot address device code.** Whatever `/Brepro` does to the host
   toolchain, the fatbin nvcc embeds is outside its reach; `--frandom-seed` is
   the candidate there and is separately unverified.
5. **It would invalidate the measurements already taken.** Changing compile or
   link flags changes the artefact. Builds A, B, A2 and A3, and any pack
   identity reasoned from them, would have to be redone. Doing that to make a
   gate green, before the gate's acceptance model is even correct, is the
   inversion this workstream exists to avoid.

**The decision.** R1 keeps the frozen build recipe unchanged and accepts
semantic equivalence after mechanically verified normalisation as the C2
outcome. `/Brepro`, `--frandom-seed` and `/PDBALTPATH:%_PDB%` are recorded as
**R2 candidates**, to be evaluated only by experiment on the host and only after
Gate C2 has passed on the current recipe. An R2 experiment would: build twice
with `set CL=/Brepro` and `set LINK=/Brepro`; confirm from the object and image
headers whether the timestamps actually changed; check whether a type-16 debug
entry appeared; and rerun `compare_native_object_trees.py` and
`compare_wheel_reproducibility.py` to see whether the residual set shrank. If it
did not shrink, the flag is not doing anything here and the file closes.

**What must not happen:** adding any of these flags to force a green verdict.
The checker was built so that a green verdict means something; a flag added to
produce one, without evidence that it changes the artefact in the way claimed,
empties it again.

### Consequence for C3 identity — reviewed, no change required

`runtime_pack_id` is derived from the platform variant, the Python version, the
native ABI, the third-party lock digest and the requirements-projection digest.
The lock pins each wheel as `name==version --hash=sha256:...`. Runtime Pack
identity therefore **already binds to the selected canonical MMCV wheel's
SHA-256**, not to the ability to rebuild that wheel bit for bit. The
non-reproducibility finding does not invalidate the identity model and no
identity change is required.

Two things it does change, both in what must be recorded rather than in how
identity is computed:

1. **The canonical wheel must be named as a choice.** Two wheels were built; one
   becomes the artefact the lock binds to. Which one, and why, is part of C2's
   record. The other is reproducibility evidence.
2. **The SHA-256 must travel with the reproducibility verdict.** A hash recorded
   alone implies it can be re-derived. It cannot. The C2.2a and C2.2b reports
   are what qualify it, and they belong beside it.

The rule that follows, and that nothing downstream may violate: a rebuilt MMCV
wheel is **not** substitutable into an existing pack. Semantic equivalence is
not artefact identity. If the canonical wheel is ever lost, the pack identity is
lost with it and a new pack must be minted -- which is the correct behaviour for
a hash-pinned closure, not a defect to engineer around.

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

Runtime Pack reproduction from the same inputs must produce the same content
identity: rebuild the pack and compare `runtimePackId`. This is a property of
the pack builder, not of MSVC, so it is unconditional — C2.2's verdict does not
soften it.

The wheel comparison belongs to **Gate C2**, not here, and its acceptance model
is semantic equivalence after mechanically verified normalisation. The earlier
requirement to compare the wheel byte-for-byte, and to write an ADR treating it
as a hash-pinned binary input if that failed, has been **superseded**: the
measurement was taken, the wheel is not byte-reproducible, and the lock already
pins it by SHA-256. See "Consequence for C3 identity — reviewed, no change
required". No ADR is required.

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
-- 37 cases, each naming the invariant it defends, the expected outcome, whether
retry is permitted, whether fallback is permitted, and the stable failure codes
that may legitimately report it. Print it before the
session to prepare the run sheet:

```
python tools/vision/build_failure_matrix_evidence.py --print-matrix \
    --scope hardware --source-head-sha x --captured-at-utc x \
    --operator-reference x
```

Record each case as a `mavi-windows-cuda-failure-case-v1` document -- its shape
is published at `tools/vision/windows-cuda-failure-case.schema.json` and
validated on load -- then assemble:

```
python tools/vision/build_failure_matrix_evidence.py --scope hardware \
    --case auto-pack-absent=case-auto-pack-absent.json \
    ... one --case per declared case ... \
    --source-head-sha <40-hex head of the source tree under test> \
    --captured-at-utc <YYYY-MM-DDTHH:MM:SSZ> \
    --operator-reference <workstation or operator label> \
    --output failure-matrix-evidence.json
```

**Scope is explicit and never implied, on two axes.** A case can need the
Windows launcher without needing a GPU: most permitted Auto fallbacks are
resolved by `Test-CudaRuntimeUsable` before Python starts, and PowerShell does
not run in hosted CI at all. So:

- `--scope linux-observable` -- the 7 cases the worker itself produces, needing
  neither a GPU nor the launcher;
- `--scope windows-host` -- the 27 cases observable without a GPU (the 7 above plus 20 needing the Windows launcher), but no
  GPU;
- `--scope hardware` -- all 37, and it additionally requires
  `--development-evidence`: every hardware case must carry the salted GPU
  identity digest and driver version, and all of them must match the card the
  C4 bundle qualified. Without that a full hardware bundle would assemble on a
  machine with no device and be indistinguishable from one that ran.

None of the three is hardware qualification. The bundle says so in its own note,
and a bundle may never carry a case its scope says it cannot have observed.

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

Where Auto is permitted to answer CPU, explicit CUDA has its own refusal case --
all eight, not only the obvious four. Those are the highest-risk places for a
silent fallback precisely because a legitimate CPU answer exists next door.

Ten cases require a real GPU; twenty more require the Windows launcher; the
remaining seven are exercisable on any machine and should be recorded before the
host session, so the session spends its time on what only it can do.

Operator diagnostics are redacted on the way in: the natural NVML or driver
message for a wrong-GPU refusal *is* the card's UUID, and the operator is being
asked to paste that message into the record.

## Phase C8 — review and merge

Before merge to `main`:

- full hosted CI green on exact head;
- hardware evidence reviewed;
- CPU regression path green;
- independent cold review;
- documentation updated;
- no Production-support claim introduced.

Merge the milestone back to `main` promptly rather than allowing another long-lived integration branch.

## Guard coverage

The evidence assemblers are almost entirely fail-closed guards, and a guard no
test can distinguish is not a guard. Adversarial review found ten at once in the
C6 and C7 assemblers: every weakening applied to them left the suites green.

`tools/vision/check_guard_coverage.py` makes that check mechanical. It names
each guard by the exact source line that implements it, neutralises that line,
and requires the suites to fail; a survivor means the guard is untested or
redundant, and both are worth knowing. The quality gate runs it. The ordinary
suite runs the cheap half -- that every named guard still exists exactly once --
because a harness that cannot find its targets looks identical to one whose
targets are all well tested.

## Operator procedure for the host session

Everything in this plan that a hosted session cannot do is consolidated, in
execution order and with exact commands, in
`docs/runbooks/windows-cuda-host-session.md`. This plan remains authoritative
for the reasoning, the gates and the dated history; the runbook is the
procedure, so the host session executes a reviewed sequence rather than
improvising one. A test checks that every flag the runbook names still exists
on the tool it names.

## Current execution point

C0, C1 and C1R are complete. C1R is merged to `main`; the merge commit is
recorded in this plan's header.

**R1 has passed** and the pre-C2 empirical gate is complete. The verified
toolchain is CUDA 12.4 + MSVC 14.44.35207 + Windows SDK 10.0.26100.0; MSVC 14.39
is not required. The evidence is recorded above and frozen in the build
contract.

**C2 has started.** The first Windows host session ran the build half of C2:
four successful MMCV CUDA wheel builds, three empirical corrections to the
procedure (`--no-deps` on the wheel download, `setuptools==80.10.2`,
`DISTUTILS_USE_SDK=1`), and the reproducibility measurement. Its outcome is
that the wheel is **not byte-reproducible**, and the acceptance model in Phase
C2 above was rewritten to match what was measured rather than what was hoped.

C2 is **not** complete and the branch is **not** BUILD-VERIFIED. C2.2 has now
been run and recorded; what remains is the closure and the functional proof --
C2.3 through C2.5, the wheelhouse manifest, the frozen lock, the offline
install and the runtime validation. Until Gate C2 passes in full, no
BUILD-VERIFIED claim may be made anywhere.

### Phase state, in the precise vocabulary

These states are not interchangeable and this plan does not collapse them.
*Implemented* means the code exists; *tested* means it is covered by automated
tests; *build-verified* means a real build produced the artefact;
*Runtime-Pack-verified* means a pack was assembled and checked;
*hardware-qualified* means a real GPU executed the work and the evidence was
accepted; *Production-qualified* is a separate later gate that none of this
reaches.

| Phase | State |
| --- | --- |
| C0, C1, C1R | complete; C1R merged to `main` |
| R1 toolchain preflight | **executed and passed** on the controlled Windows host |
| C2 wheelhouse/lock | **BUILD-VERIFIED**: canonical MMCV CUDA wheel chosen and archived off-host; 21-root projection derived; `windows-x86_64-cuda.lock` and `.requirements.txt` frozen and committed (`3d73330`); clean `--no-index --require-hashes` install and `mmcv.ops` import proven on the host |
| C2 reproducibility | **MEASURED and CLOSED**: not reproducible in any form. A2/A3 differ in 183,339 bytes of the `.pyd` with two timestamps accounted for. Retained as diagnostic evidence; explicitly **not** a Development gate. Object-level comparison not applicable -- the objects are `/GL` IL |
| C3 Runtime Pack | **RUNTIME-PACK-VERIFIED** on the host: `mavi-runtime-v2-89fd8bf…`, native ABI `win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75`, identity reproduced from a second build; the pack is external to the repository |
| C4 hardware qualification | **HARDWARE-QUALIFIED for Development** on a GTX 1650 Ti: `runtime.json` `windows-x86_64-cuda` is `qualified-development-hardware` with `developmentEvidence` bound to source head `3d73330` (`6889bf4`, `4e88c36`); the release lock entry stays `pending-hardware-qualification` |
| C5 Overlay binding | **BOUND** (`4b54f4d`, `20babb0`): component overlay declares the CUDA pack with real identities; boundary-gate `windows-x86_64-cuda` row passes in CI; host-side C5.4 device-resolution checks (explicit CUDA fail-closed, Auto fallback) **not yet recorded** |
| C6 Development E2E | evidence tooling IMPLEMENTED and TESTED; **no run executed** |
| C7 failure matrix | tooling IMPLEMENTED and TESTED; 37 declared cases, 7 exercisable without a Windows host, **none yet recorded** |
| Production | **not entered**, and not reachable from anything above |

The committed C2 artefacts are the frozen lock and requirements projection;
the wheels, the wheelhouse manifest and the Runtime Pack remain external. Every
promotion recorded above was made by a host session executing the reviewed
procedure and checked by the tooling, not typed by hand; the table's history
(the earlier "not started" states) is preserved in this file's git log.

**Tooling is not execution.** An implemented evidence assembler proves only
that a bundle will be checked when one exists; it is not a build, not a pack,
not a run and not a qualification.

**The pre-C2 evidence review is complete**, as are several further rounds of
adversarial review over the C2-C7 tooling, the launcher refactor and the branch
as a whole. Their findings are fixed and pinned by test.

**Reconciled onto `main@bdf834a` on 2026-09-20** (PR #50 merged first; merge
commit, no conflicts, no history rewrite). The cold review of the reconciled
tree and the two P2 fixes it produced are recorded in
`docs/superpowers/plans/c8-pr49-readiness.md` §8. **The next step requires the physical Windows CUDA host**: what remains is C6 (five E2E runs) and C7 (37 failure-matrix
cases), plus the C5.4 device-resolution checks; the procedure is
`docs/runbooks/windows-cuda-host-session.md`. Nothing on the host may promote
the CUDA release lock without an owner decision (readiness §5).

### Owner decisions recorded

Two questions raised by review are resolved and no longer block work.

**Production bundle-identity coupling does not block C3.** C3 remains
Development-only. Development artefacts bind strongly to the frozen lock, the
Runtime Pack manifest, the Python, Torch, torchvision and MMCV/native ABI
identities, the build toolchain identity, and the model, config and checkpoint
identities where relevant. Production qualification stays a separate later
fail-closed gate, and Development evidence never satisfies it. The consequence
recorded in ADR-009 -- that freezing the CUDA lock changes Production bundle
identity -- is accepted rather than designed around, and is handled when
Production qualification is undertaken.

**The consistency-only evidence model is accepted for Development.** Stated
precisely, Development evidence proves internal consistency, cross-file
identity agreement, the expected execution relationship, reproducible evidence
binding, and integrity against accidental mismatch. It does **not** prove
authenticity, non-repudiation, operator non-fabrication, or tamper-resistance
against a privileged local operator. That limit is acceptable for Development
because ADR-009 keeps the state separate; Production will require stronger
provenance, attestation, signing and CI-produced evidence as a later
requirement.

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
