# C8 — PR #49 pre-merge readiness

Status of the Windows CUDA Development workstream on `feature/windows-cuda-pre-c2`.

**Nothing below is marked complete without evidence that exists today.** Where a
row says pending, the evidence does not exist and cannot be produced from a
hosted Linux session.

The vocabulary is not interchangeable:

| State | Means |
| --- | --- |
| IMPLEMENTED | the code exists |
| TESTED | covered by automated tests that run in CI |
| BUILD-VERIFIED | a real build produced the artefact (C2) |
| RUNTIME-PACK-VERIFIED | a pack was assembled and checked (C3) |
| HARDWARE-QUALIFIED | a real GPU executed the work and the evidence was accepted (C4) |
| PRODUCTION-QUALIFIED | a separate later gate this branch does not approach |

## 1. Repository and tooling — COMPLETE

| Item | State | Evidence |
| --- | --- | --- |
| R1 toolchain preflight | **executed and passed** on the controlled Windows host | frozen in `config/vision/windows-cuda-development-build-v1.json`, `verificationStatus: verified` |
| C2 tooling (wheel inspection, reproducibility comparison, native metadata analysis, object-tree comparison, wheelhouse manifest, lock freeze) | IMPLEMENTED, TESTED | `tools/vision/`, vision suite; counts are read from the suite rather than restated here |
| C3 tooling (Runtime Pack build, native-ABI derivation) | IMPLEMENTED, TESTED | `build_runtime_pack.derive_native_abi`, pinned against the committed contract |
| C4 tooling (host probe, toolchain verify, runtime verify, evidence assembler) | IMPLEMENTED, TESTED | 88 tests on the assembler, 16 on the verifier |
| C5 tooling (requirements projection writer, Auto-decision function) | IMPLEMENTED, TESTED | reproduces both tracked CPU projections byte for byte; 9 Auto branches on Windows CI |
| C6 tooling (E2E evidence assembler) | IMPLEMENTED, TESTED | vision suite |
| C7 tooling (failure matrix, 37 declared cases: 7 linux-observable, +20 windows-host, +10 hardware) | IMPLEMENTED, TESTED | vision suite |
| Published schemas for all five record types | COMPLETE | `tools/vision/*.schema.json`, validated on load |
| Launcher failure-code vocabulary | COMPLETE | 38 codes, mirror-checked, exercised on Windows CI |
| Guard-coverage harness | COMPLETE | `check_guard_coverage.py`, runs in the quality gate |
| Operator procedure | COMPLETE | `docs/runbooks/windows-cuda-host-session.md`, flag-drift tested |
| Hosted CI on exact head | GREEN | all five workflows |
| CPU baseline protected | VERIFIED | `windows-x86_64-cpu.lock` byte-identical to `main`; `runtime.json` and `mmdetection-phase1-v1.json` changed **additively only** (new `windows-x86_64-cuda` variant, lock and pack entries; both CPU entries byte-for-byte unchanged); the qualification record's `runtimeProfileSha256` was re-derived because it binds the whole runtime profile (the tripwire, §4) |

## 2. Build verification (C2) — PARTIALLY EXECUTED, GATE PENDING

The first Windows host session ran the build half. The closure half has not
run, and the reproducibility proof has not been run over the full object
population with the tooling that now exists.

Done on the host, recorded in the plan:

- [x] MMCV built four times against CUDA 12.4 / MSVC 14.44.35207 / SDK 10.0.26100.0 — A and B from separate clean trees, A2 and A3 from the same tree and venv
- [x] three procedural corrections established and written into the runbook: `--no-deps` on the wheel download, `setuptools==80.10.2`, `DISTUTILS_USE_SDK=1`
- [x] reproducibility **measured**: the wheel is not byte-reproducible; four distinct SHA-256 values

**The C2 Development target is the minimum defensible set**: one canonical MMCV
CUDA wheel, chosen and named, with an exact SHA-256; the source, toolchain and
dependency recipe recorded; a clean offline install; successful runtime import
and native CUDA operator validation.

**Repeated-build reproducibility is diagnostic evidence, not a gate.** Measured
on the host: A2 versus A3, same tree and venv, differ in 183,339 bytes of
`_ext.cp312-win_amd64.pyd` with only two timestamps accounted for. The wheel is
not reproducible and the residual is not characterised. That is a property of
the build process, not of the pinned artefact, and the functional gates test
the artefact that ships.

**The accepted cost, recorded rather than buried:** the canonical wheel cannot
be reconstructed if lost, cannot be verified by rebuilding, and cross-build
crash analysis is unavailable. Mitigation is operational — archive the wheel
off the build host and treat it as a controlled input. Production qualification
is separate and may impose stronger reproducibility and provenance
requirements.

Completed on the host:

- [x] authoritative `+cu124` wheels acquired from the dedicated index **with `--no-deps`**
- [x] C2.2a run on the **A2/A3 wheels** (same source tree): `divergent-content` / `unexplained-native-difference`, 183,339 residual bytes. **Recorded as diagnostic evidence; not a gate**
- [x] C2.2a run on the A/B wheels for the relocatability record (optional; A2/A3 already establishes non-reproducibility)
- [x] C2.2b run on the preserved A2/A3 object trees: 129 of 136 unparsable as `bigobj_anon_object_header_unsupported`. Consistent with `/GL` IL objects, which carry no machine code. **Not applicable as evidence; closed, no rebuild**
- [x] the BIGOBJ `36:40` question is **closed as not applicable**: the objects are IL, so the field never described emitted code. No further forensics
- [x] canonical MMCV wheel chosen, named, its SHA-256 recorded **together with** the reproducibility verdict, and the wheel archived off the build host
- [x] requirements projection **derived** (not hand-written) and used to drive acquisition — the frozen closure is 21 pinned roots, not a remembered subset
- [x] every Torch/torchvision wheel in the wheelhouse verified to carry `+cu124`
- [x] wheelhouse manifest produced
- [x] `windows-x86_64-cuda.lock` frozen and committed
- [x] `windows-x86_64-cuda.requirements.txt` derived and committed
- [x] clean `--no-index --require-hashes` install proven with the network blackholed
- [x] imports and `mmcv.ops` verified

**BUILD-VERIFIED.** The closure was assembled, the lock frozen and committed,
and C2.5 proved a clean `--no-index --require-hashes` offline install with
`pip check` clean and CUDA imports and native ops passing on the host.

**Reproducibility is not achievable on this toolchain and is not claimed**, in
any form: not byte-identical, and not semantically equivalent after
normalisation either. That was measured, not assumed, and the analyser still
refuses to call the two wheels equivalent. C2 Development accepts a pinned,
functionally validated canonical artefact instead.

## 3. Runtime Pack verification (C3) — COMPLETE ON THE HOST

- [x] pack built from the frozen C2 inputs with the derived native ABI
- [x] manifests and artefact hashes validated
- [x] CUDA Toolkit and MSVC proven **not** to be runtime prerequisites (`nvcc` and `cl` absent)
- [x] pack identity reproduced from an independent second build

| | |
| --- | --- |
| Runtime Pack ID | `mavi-runtime-v2-89fd8bfcc32fb1bd8ab77f0deb9f33675ae228c75ffd11f13e6838e990003a1d` |
| CUDA lock SHA-256 | `f95a7970168eaa903b8acbfd3c8fcc2fb3a9838f5b52ca8a1fc0fcb843b72c64` |
| Requirements SHA-256 | `aef75d1960c0fc07483b5ffba4b6ba1471efde8fdf06d4bae3d0e3275b30b981` |
| Native ABI | `win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75` |
| Installed at | `C:\ProgramData\MAVI\Development\VisionRuntime\windows-x86_64-cuda` |

**RUNTIME-PACK-VERIFIED.** The artefacts are external to the repository; the
repository binding is C5's job.

## 4. Hardware qualification (C4) — COMPLETE

- [x] fresh sanitised host observation captured
- [x] toolchain observation captured on the host
- [x] on-device run on a GTX 1650 Ti through the installed Runtime Pack's interpreter: Torch CUDA matmul and `mmcv.ops` NMS
- [x] physical GPU identity verified (salted digest, driver, memory, compute capability 7.5)
- [x] Development hardware evidence bundle assembled
- [x] `runtime.json` variant moved to `qualified-development-hardware` using the bundle's `variantPatch` verbatim (commit `6889bf4`)

**HARDWARE-QUALIFIED for Development**, and only that.
`windows-x86_64-cuda` is `qualified-development-hardware` in the committed
runtime profile. Per ADR-009 this can never satisfy Production, and the
release record still lists the `windows-x86_64-cuda` gate as `pending` with
`overallResult` `pending` — a test pins that pairing so a later edit cannot
tidy the gate to `passed` because the variant looks qualified.

**Consequence handled here:** the qualification record binds the runtime
profile by whole-file digest, so the CUDA-only promotion moved that digest and
`verify_repo` refused with `qualification_identity_mismatch`. The binding is a
deliberate tripwire and was not loosened; the record's `runtimeProfileSha256`
was re-derived from the file, and a test now derives it rather than trusting
it.

## 5. C5 activation — IN PROGRESS

The C3 pack identity now exists, so the binding has something real to point
at. In progress on the host, uncommitted at the time of writing: the CUDA
runtime-pack binding in `mmdetection-phase1-v1.json`, and the CUDA row in the
boundary-gate workflow.

- [x] component overlay declares `windows-x86_64-cuda` with real identities (commit `4b54f4d`); the pack identity re-derives from the tracked lock and projection and matches the host-reported `mavi-runtime-v2-89fd8bf…`
- [x] boundary-gate matrix row added; the `windows-x86_64-cuda` boundary job passes in CI, which is the first workflow validation of the CUDA lock
- [x] the two pre-C5 pinning tests updated deliberately

**The two Auto decisions now differ, and the difference is recorded rather than
hidden.** The supervisor's Auto (`RuntimeSupervisor._resolve_device`) requires
the CUDA entry in `releaseLocks` to be `qualified-offline-lock`; it is still
`pending-hardware-qualification`, so any entry point that reaches Python with
`MAVI_DEVICE_POLICY=auto` resolves to CPU. `test_development_auto_still_chooses_cpu_against_the_committed_profile`
pins exactly that. The **launcher's** Auto (`Resolve-MaviVisionCudaAvailability`)
does not read `releaseLocks`: it decides from the installed pack's integrity,
the component's declared pack identity and the driver, so on the host with the
C3 pack installed it selects CUDA and starts Python with an explicit `cuda`
policy. That is the behaviour the runbook's C5.4 table and C6 `auto-cuda` case
require, and it is why C6 can be executed at all before the lock is promoted.
The supervisor-side reason remains `cuda_pack_not_declared`, the catch-all for
a not-ready CUDA runtime, which under-describes the cause — left as is, because
the reason vocabulary is closed and mirrored in the JSON schema, the .NET parser
and the PowerShell launcher. Promoting the release lock (which re-aligns the two
decisions and, per ADR-009 §5, changes Production bundle identity) is an owner
decision that follows C6/C7, not something this branch does.
- [ ] explicit CUDA fail-closed verified on the host
- [ ] permitted Auto fallback verified with a stable, logged, persisted reason

Two tests currently enforce that this has **not** happened, on purpose:
`test_every_declared_runtime_pack_is_covered_by_the_boundary_gate` and
`test_development_auto_still_chooses_cpu_against_the_committed_profile`.

## 6. C6 / C7 real execution evidence — PENDING

- [ ] five C6 runs over identical media, bundle assembled
- [ ] 37 C7 cases recorded and the `hardware`-scope bundle assembled

The assemblers exist and are tested; **no run has been executed and no bundle
exists.** Tooling is not execution.

## 7. Production qualification — OUT OF SCOPE

Not entered, not approached, and not reachable from anything above. ADR-009
keeps `qualified-development-hardware` structurally disjoint from
`qualified-hardware`, and the profile-level `qualified` status treats the
Development state as pending. Production will require attestation, signing and
CI-produced evidence with the operator out of the loop.

## 8. Reconciliation and cold review — 2026-09-20

The branch was reconciled onto `main@bdf834a` (PR #50 merged) by a merge commit,
with no conflicts and no history rewrite; every PR #49 file is byte-identical to
the pre-merge head `b89acba`, and every PR #50 file is byte-identical to `main`.
An independent cold review of the whole branch on the reconciled tree found no
P1 and two P2, both fixed and pinned by test in the same pass:

- `verify_windows_cuda_toolchain.py` compared the toolset and SDK identities
  from `VCToolsVersion`/`WindowsSDKVersion` (shell variables) but only
  *recorded* the compiler's self-reported version, and ran `nvcc` with
  `NVCC_PREPEND_FLAGS`/`NVCC_APPEND_FLAGS` inherited and unrecorded. It now
  refuses a compiler version that differs from the frozen
  `toolchain.msvcCompilerVersion` and refuses to run while either nvcc hook is
  set. The R1 observation already on record shows `19.44.35222`, the frozen
  value, so it stands.
- `build_runtime_pack.py` derived the native ABI from the contract without
  checking that the contract described the lock being packed. It now refuses a
  pack whose contract `platformVariant`, `pythonVersion`, `torchBinaryVersion`
  or `torchvisionBinaryVersion` disagree with the inputs. The committed contract
  and lock agree, so the C3 pack identity is unchanged.

C6/C7 evidence still does not exist (§6). What that means for merge is stated in
the pull request: the code, tooling, lock, pack binding and C4 Development
evidence are what is being merged; C6/C7 remain operator-executed on the host.

**Draft status ends with the C8 gate below**, not before.

**Merged 2026-09-20** as `ed1acf4b66a6b60e19593e2cf806316ab2a1fc3e` (head `1a24b50`, base `main@bdf834a`) after every C8 criterion held on the exact head. The C5.4/C6/C7 host work in §5 and §6 remains outstanding and is tracked here, not in the capability roadmap.

## Merge criteria, for when the host session is done

Plan Gate C8 requires, before merge to `main`:

- [ ] full hosted CI green on the exact head — confirmed in the pull request against its final SHA
- [x] hardware evidence reviewed — the committed C4 record, its bindings and the assemblers that consume it were reviewed on the reconciled tree; the evidence bundle itself is external and was not re-executed
- [x] CPU regression path green — Task 10 and Task 12 CPU matrices on the exact head, plus the byte-identical CPU lock
- [x] independent cold review — §8
- [x] documentation updated — §8, the plan's execution point, `docs/runbooks/local-development.md`
- [x] no Production-support claim introduced — §7

C6/C7 execution evidence is not a C8 merge criterion in the plan and is not
claimed here; it stays pending in §6 and is executed on the host after merge.
