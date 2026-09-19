# Windows CUDA Development Host Session

Everything in the Windows CUDA workstream that a hosted Linux session cannot do,
in the order it must be done, with the exact commands.

The authoritative plan is
`docs/superpowers/plans/2026-09-18-windows-cuda-development.md`; it holds the
reasoning, the gates and the dated history. This runbook holds the procedure, so
the host session executes a reviewed sequence rather than improvising one.

**What this session can and cannot establish.** It can produce build
verification, a Runtime Pack, hardware execution evidence and a Development
hardware qualification. It cannot produce Production qualification, and nothing
here may be presented as such: ADR-009 keeps `qualified-development-hardware` a
state that can never satisfy Production, which requires CI-produced evidence
with the operator out of the loop.

## Before you start

- Windows host with the qualified toolchain: CUDA 12.4, MSVC 14.44.35207,
  Windows SDK 10.0.26100.0. This was verified by R1 and is frozen in
  `config/vision/windows-cuda-development-build-v1.json`. Do not substitute a
  different toolset, and never pass `--allow-unsupported-compiler`.
- The repository checked out at the head under test. Every evidence artefact
  records a 40-hex source head and the assemblers require them to agree, so note
  it once and reuse it:

  ```powershell
  $head = (git rev-parse HEAD).Trim()
  ```

- A scratch directory outside the repository for artefacts. All the filenames
  below are gitignored, but keep them out of the tree anyway.

**Nothing produced here is committed except where a step says so explicitly.**
Raw host observations contain the GPU UUID and must never be committed; the
2.5 GB Torch wheel and the built wheels must never be committed.

## 1. Host and toolchain observation

```powershell
python tools\vision\probe_windows_cuda_host.py --sanitized `
    --output host-observation.json
python tools\vision\verify_windows_cuda_toolchain.py `
    --contract config\vision\windows-cuda-development-build-v1.json `
    --output toolchain-observation.json
```

`--sanitized` is not optional. Without it the observation carries the raw GPU
UUID, so the digest recorded in every later artefact would name a file that may
never be shown to anyone. The C4 builder refuses an unsanitised observation.

Both are validated against published schemas at
`tools/vision/windows-cuda-host-observation.schema.json` and
`tools/vision/windows-cuda-toolchain-observation.schema.json`.

## 2. C2 — wheelhouse and lock

Run the reproducibility experiment **early**. A negative result changes C3's
identity contract rather than merely delaying it.

Follow the plan's "C2 tooling and execution order" section in full. In summary:

1. acquire Torch and torchvision from the dedicated cu124 index only -- never
   `--extra-index-url`, never a PyPI fallback. A bare `2.6.0` is a different
   artefact from `2.6.0+cu124`;
2. build MMCV **twice from clean trees** at the pinned commit, then compare:

   ```powershell
   python tools\vision\compare_wheel_reproducibility.py `
       --left build-a\mmcv-....whl --right build-b\mmcv-....whl `
       --output mmcv-reproducibility.json --require semantically-identical
   ```

3. assemble the wheelhouse manifest, freeze the lock, prove the offline install
   in a clean venv with the network blackholed.

**Gate C2** is in the plan. Do not proceed past a `divergent-*` verdict.

## 3. C3 — Runtime Pack

The pack's `--native-abi` is **not** hand-typed. It is the `nativeAbi` field of
the build contract, derived from the verified toolchain by
`build_runtime_pack.derive_native_abi` and pinned by test:

```
win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75
```

C3 remains Development-only. Bind the pack strongly to the frozen lock, the
manifest, the Python identity, the Torch and torchvision identities, the
MMCV/native ABI identity, the build toolchain identity, and the model, config
and checkpoint identities.

## 4. C4 — hardware qualification

Prove the native operators execute on the device, then assemble the bundle:

```powershell
python tools\vision\verify_windows_cuda_runtime.py --device-index 0 `
    --resolved-config src\vision\runtime\mmdetection-phase1-v1\rtmdet_m_resolved.py `
    --host-observation host-observation.json `
    --output runtime-verification.json

python tools\vision\build_development_hardware_evidence.py `
    --host-observation host-observation.json `
    --toolchain-observation toolchain-observation.json `
    --runtime-verification runtime-verification.json `
    --source-head-sha $head `
    --captured-at-utc (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") `
    --operator-reference "<workstation or operator label>" `
    --device-index 0 `
    --output development-evidence.json
```

A failed verification also writes its record, with `result: "failed"` and both
execution flags false. Keep it: C7 wants it.

The builder refuses anything it cannot corroborate -- the run and the
observation must name the same card by its salted identity digest and agree on
driver and memory, the run must name the observation it was produced against,
the toolchain must name the same revision and target architecture, and peak
device allocation must be above zero.

**Gate C4.** Only after this passes may `windows-x86_64-cuda` move from
`pending-hardware-qualification` to `qualified-development-hardware` in
`src/vision/runtime/mmdetection-phase1-v1/runtime.json`. Use the bundle's
`variantPatch` verbatim and add its `developmentEvidence` block -- it is
machine-generated precisely so those identities are not typed by hand. This is
the one step here that changes a committed file.

## 5. C5 — Overlay binding

Add `windows-x86_64-cuda` to `src/vision/config/components/mmdetection-phase1-v1.json`
with the exact Runtime Pack ID, third-party lock SHA-256, runtime-requirements
SHA-256 and native ABI.

Two tests will fail until you do the rest of the job, deliberately:

- `test_every_declared_runtime_pack_is_covered_by_the_boundary_gate` -- add the
  matching matrix row to `.github/workflows/vision-runtime-component-boundary.yml`,
  or the gate that enforces this binding produces no job for it;
- `test_development_auto_still_chooses_cpu_against_the_committed_profile` and
  the declared-set assertion in `test_runtime_projection_repository_contract.py`
  -- update them on purpose, because the pre-C5 property they pin has genuinely
  changed.

## 6. C6 — Development end-to-end

Record each run as a `mavi-windows-cuda-development-e2e-run-v1` document, then:

```powershell
python tools\vision\build_development_e2e_evidence.py `
    --development-evidence development-evidence.json `
    --run explicit-cuda=run-explicit-cuda.json `
    --run auto-cuda=run-auto-cuda.json `
    --run explicit-cpu=run-explicit-cpu.json `
    --run restart-recovery=run-restart-recovery.json `
    --run cuda-oom-recovery=run-cuda-oom-recovery.json `
    --source-head-sha $head `
    --captured-at-utc (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") `
    --operator-reference "<workstation or operator label>" `
    --output development-e2e-evidence.json
```

All five runs must be over the same media and the same frame count -- a
CPU-versus-CUDA comparison between two different videos characterises nothing.
Timing is engineering characterisation only; no Production threshold may be
derived from it.

## 7. C7 — failure matrix

Print the matrix first and use it as the run sheet:

```powershell
python tools\vision\build_failure_matrix_evidence.py --print-matrix `
    --scope hardware --source-head-sha x --captured-at-utc x `
    --operator-reference x
```

37 cases. Five are exercisable anywhere and can be recorded before this session;
20 more need the Windows launcher but no GPU; 12 need a real device. Record each
as a `mavi-windows-cuda-failure-case-v1` document, then:

```powershell
python tools\vision\build_failure_matrix_evidence.py --scope hardware `
    --development-evidence development-evidence.json `
    --case <id>=case-<id>.json `   # repeat for every declared case
    --source-head-sha $head `
    --captured-at-utc (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") `
    --operator-reference "<workstation or operator label>" `
    --output failure-matrix-evidence.json
```

Scope is never implied. A `hardware` bundle requires the C4 evidence and every
hardware case must name the same card; a narrower scope may not carry a case it
could not have observed.

When pasting an operator diagnostic, do not worry about a driver message
containing a GPU UUID -- the assembler redacts it -- but do not paste a whole
log: diagnostics are bounded at 2000 characters.

## 8. Before leaving the host

- the full vision suite, `python tools/verify_repo.py`, and the Windows
  PowerShell contract scripts;
- confirm the three protected CPU baseline files are byte-identical to
  `main@0225779` (the plan records the expected blob hashes);
- push, and confirm hosted CI is green on the exact head;
- commit no raw host observation, no wheel, no evidence artefact other than the
  runtime-profile change Gate C4 authorises.

## What must not happen here

- no Production qualification, and no change to Production qualification status;
- no `qualified-development-hardware` without a genuine C4 bundle;
- no substitution of a PyPI `torch` for `torch==2.6.0+cu124`;
- no `--allow-unsupported-compiler`;
- no hand-typed Runtime Pack ID, native ABI, Python identity or binary identity
  where a tool derives it.
