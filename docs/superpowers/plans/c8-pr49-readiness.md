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
| CPU baseline untouched | VERIFIED | three protected blobs byte-identical to `main@0225779` |

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

Still required before Gate C2:

- [ ] authoritative `+cu124` wheels acquired from the dedicated index **with `--no-deps`**
- [x] C2.2a run on the **A2/A3 wheels** (same source tree): `divergent-content` / `unexplained-native-difference`, 183,339 residual bytes. **Recorded as diagnostic evidence; not a gate**
- [ ] C2.2a run on the A/B wheels for the relocatability record (optional; A2/A3 already establishes non-reproducibility)
- [x] C2.2b run on the preserved A2/A3 object trees: 129 of 136 unparsable as `bigobj_anon_object_header_unsupported`. Consistent with `/GL` IL objects, which carry no machine code. **Not applicable as evidence; closed, no rebuild**
- [x] the BIGOBJ `36:40` question is **closed as not applicable**: the objects are IL, so the field never described emitted code. No further forensics
- [ ] canonical MMCV wheel chosen, named, its SHA-256 recorded **together with** the reproducibility verdict, and the wheel archived off the build host
- [ ] wheelhouse manifest produced
- [ ] `windows-x86_64-cuda.lock` frozen and committed
- [ ] `windows-x86_64-cuda.requirements.txt` derived and committed
- [ ] clean `--no-index --require-hashes` install proven with the network blackholed
- [ ] imports and `mmcv.ops` verified

**Not BUILD-VERIFIED.** A partially executed phase is not a passed gate, and
four successful builds are not a closure. What remains is the closure and the
functional proof — C2.3 through C2.5 — not more binary forensics.

**Reproducibility is not achievable on this toolchain and is not claimed**, in
any form: not byte-identical, and not semantically equivalent after
normalisation either. That was measured, not assumed, and the analyser still
refuses to call the two wheels equivalent. C2 Development accepts a pinned,
functionally validated canonical artefact instead.

## 3. Runtime Pack verification (C3) — PENDING

- [ ] pack built from the frozen C2 inputs with the derived native ABI
- [ ] manifests and artefact hashes validated
- [ ] CUDA Toolkit and MSVC proven **not** to be runtime prerequisites
- [ ] pack identity reproduced from a second build

**Not RUNTIME-PACK-VERIFIED.**

## 4. Hardware qualification (C4) — PENDING

- [ ] fresh sanitised host observation captured
- [ ] toolchain observation captured on the host
- [ ] on-device run: `mmcvNmsExecutedOnCuda` and `torchMatmulExecutedOnCuda` true, non-zero peak allocation
- [ ] physical GPU identity verified (salted digest, driver, memory, compute capability 7.5)
- [ ] Development hardware evidence bundle assembled
- [ ] `runtime.json` variant moved to `qualified-development-hardware` using the bundle's `variantPatch` verbatim

**Not HARDWARE-QUALIFIED.** `windows-x86_64-cuda` remains
`pending-hardware-qualification` in the committed runtime profile.

## 5. C5 activation — PENDING

Blocked on a real C3 pack identity; there is nothing to bind to yet.

- [ ] component overlay declares `windows-x86_64-cuda` with real identities
- [ ] boundary-gate matrix row added
- [ ] the two pre-C5 pinning tests updated deliberately
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

**PR #49 must remain Draft and unmerged.**

## Merge criteria, for when the host session is done

Plan Gate C8 requires, before merge to `main`:

- [ ] full hosted CI green on the exact head
- [ ] hardware evidence reviewed
- [ ] CPU regression path green
- [ ] independent cold review
- [ ] documentation updated
- [ ] no Production-support claim introduced

The first, the last and the CPU regression path hold today. The middle two
cannot be satisfied until the evidence exists.
