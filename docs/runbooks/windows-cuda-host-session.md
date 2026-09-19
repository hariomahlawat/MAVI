# Windows CUDA Development Host Session

Everything in the Windows CUDA workstream that a hosted Linux session cannot do,
in the order it must be done, with the exact commands.

The authoritative plan is
`docs/superpowers/plans/2026-09-18-windows-cuda-development.md`; it holds the
reasoning, the gates and the dated history. This runbook holds the procedure, so
the host session executes a reviewed sequence rather than improvising one. A
test checks that every flag named here still exists on the tool named here.

## What this session can and cannot establish

It can establish, with evidence: **BUILD-VERIFIED** (C2), **RUNTIME-PACK-VERIFIED**
(C3), **HARDWARE-QUALIFIED** for Development (C4), and the C5/C6/C7 records.

It cannot establish **PRODUCTION-QUALIFIED**, and nothing here may be presented
as such. ADR-009 keeps `qualified-development-hardware` a state that can never
satisfy Production, which requires CI-produced evidence with the operator out of
the loop.

**Development evidence proves** internal consistency, cross-file identity
agreement, the expected execution relationship, reproducible evidence binding,
and integrity against accidental mismatch. It does **not** prove authenticity,
non-repudiation, operator non-fabrication, or tamper-resistance against a
privileged local operator. That limit is accepted for Development.

## Conventions used below

Every step states: the command, the success signal, the output file, whether
that output is **committed / gitignored / external**, what to record, and
whether a failure means **STOP** or **CONTINUE**.

- **committed** — goes into git in this session.
- **gitignored** — written into the working tree, never committed.
- **external** — kept off the repository tree entirely (wheels, wheelhouse).

**STOP** means do not proceed to the next phase; the failure is a finding, not a
speed bump. Re-running a failed step with different inputs to make it pass is
falsification.

## Before you start

Toolchain, frozen by R1 in `config/vision/windows-cuda-development-build-v1.json`
and **not to be changed**:

| Component | Value |
| --- | --- |
| CUDA Toolkit | 12.4 (`V12.4.99`) |
| MSVC toolset | 14.44.35207 (compiler 19.44.35222) |
| Windows SDK | 10.0.26100.0 |
| Python | 3.12.10 |
| Target GPU | compute capability 7.5, `sm75` (Turing; the GTX 1650 Ti is sm_75) |
| Native ABI | `win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75` |

Never pass `--allow-unsupported-compiler`. Never substitute a different toolset
because a build failed; that is a finding.

Open an **x64 Native Tools Command Prompt for VS 2022** so the MSVC environment
is the qualified one, then:

```powershell
cd <repository root>
$head = (git rev-parse HEAD).Trim()
$utc  = { (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }
$op   = "<workstation or operator label>"
$work = "C:\mavi-c2"        # external scratch, outside the repository
New-Item -ItemType Directory -Path $work -Force | Out-Null
```

Record `$head` in your notes. Every evidence artefact embeds it and the
assemblers require them to agree, so if you re-checkout, start over.

---

# C2 — wheelhouse and lock

**Run step C2.2 (reproducibility) early.** A negative result changes C3's
identity contract rather than merely delaying it.

**What the first host session established, and what it changed.** The three
corrections below were paid for on the machine, not derived here; follow them
literally.

1. `pip download` without `--no-deps` pulls ordinary dependencies (NumPy,
   Pillow) from the PyTorch index into the wheelhouse and contaminates the
   closure C2.3 is supposed to describe.
2. MMCV 2.1.0 imports `pkg_resources`, which setuptools removed. Setuptools 84
   therefore fails the build outright. The pin below is part of the frozen build
   environment, not a convenience.
3. With a Visual Studio developer environment already activated, PyTorch 2.6
   aborts the extension build unless `DISTUTILS_USE_SDK=1` is set.

It also established that the MMCV CUDA wheel is **not byte-reproducible** on
this toolchain, and why. See C2.2.

## C2.1 Acquire the authoritative CUDA wheels

```powershell
python -m pip download torch==2.6.0+cu124 torchvision==0.21.0+cu124 `
    --index-url https://download.pytorch.org/whl/cu124 `
    --only-binary=:all: --no-deps --dest $work\wheelhouse
```

- **Success:** exactly two `.whl` files, whose versions carry the `+cu124` local
  segment and nothing else.
- **Output:** `C:\mavi-c2\wheelhouse\*.whl` — **external**. Never committed; the
  Torch wheel alone is ~2.5 GB.
- **Record:** SHA-256 of each wheel.
- **Must NOT change:** the index, or `--no-deps`. Use `--index-url`, never
  `--extra-index-url`, and never a PyPI fallback. A bare `2.6.0` is a
  **different artefact** from `2.6.0+cu124` and will answer a different question
  while appearing to satisfy the gate. Without `--no-deps`, pip resolves Torch's
  ordinary dependencies against the cu124 index and deposits whatever it finds
  there beside the two wheels; those strays then enter the C2.3 manifest as if
  they were part of the CUDA closure.
- **Failure:** STOP. A wheel that will not download from the cu124 index is not
  substitutable.

Verify the Torch wheel is what it claims:

```powershell
python tools\vision\inspect_windows_cuda_torch_wheel.py `
    --wheel $work\wheelhouse\torch-2.6.0+cu124-cp312-cp312-win_amd64.whl `
    --output $work\torch-wheel-inspection.json
```

- **Success:** `{"ok": true, ...}`, `"result": "passed"`.
- **Output:** `$work\torch-wheel-inspection.json` — **external**.
- **Checks:** version identity, that no `nvidia-*`/`triton` dependency lacks a
  Linux marker, and that the CUDA 12 DLL set is present.
- **Failure:** STOP.

## C2.2 Build MMCV twice, from clean trees, and compare

### The build environment

Open an **x64 Native Tools Command Prompt for VS 2022** so the frozen toolset is
the active one, then, in each build's virtual environment:

```powershell
python -m pip install "setuptools==80.10.2" wheel
```

- **Must NOT change:** the setuptools pin. MMCV 2.1.0 imports `pkg_resources`,
  which newer setuptools no longer ships, so setuptools 84 fails the build. This
  is a property of the pinned MMCV commit; do not "fix" it by taking a newer
  MMCV.

Both builds use the frozen toolchain and these exact variables:

```powershell
$env:MMCV_WITH_OPS = "1"
$env:FORCE_CUDA = "1"
$env:TORCH_CUDA_ARCH_LIST = "7.5+PTX"
$env:MAX_JOBS = "2"
$env:DISTUTILS_USE_SDK = "1"
```

- **Must NOT change:** `DISTUTILS_USE_SDK=1`. With the developer environment
  already activated, PyTorch 2.6 refuses to run the extension build without it.
  Do not work around the refusal by launching from a plain shell: that builds
  against whatever toolset happens to be first on `PATH`, which is exactly the
  substitution the frozen contract forbids.

Clone MMCV at commit `57c4e25e06e2d4f8a9357c84bcd24089a284dc88` into **two
separate clean trees**, `$work\mmcv-src-a` and `$work\mmcv-src-b`, and in each:

```powershell
python -m pip wheel . --no-build-isolation --no-deps --wheel-dir $work\build-a
```

- **Success:** `mmcv-2.1.0-cp312-cp312-win_amd64.whl`, roughly 9.5 MB.
- **Output:** `$work\build-a\*.whl`, `$work\build-b\*.whl` — **external**.
- **Record:** SHA-256 and byte size of each wheel.
- **Must NOT change:** `--no-build-isolation` (isolation would install an
  unpinned setuptools and defeat the pin above) or `--no-deps`.
- **Failure:** STOP.

**Preserve the intermediate objects before anything cleans them.** Each tree's
`build\temp.win-amd64-cpython-312` holds the 136 objects; copy the two aside as
`$work\obj-a` and `$work\obj-b`. They are the evidence for C2.2b and they are
deleted by a rebuild.

### C2.2a Compare the two wheels

```powershell
python tools\vision\compare_wheel_reproducibility.py `
    --left  $work\build-a\mmcv-2.1.0-cp312-cp312-win_amd64.whl `
    --right $work\build-b\mmcv-2.1.0-cp312-cp312-win_amd64.whl `
    --output $work\mmcv-reproducibility-ab.json `
    --require semantically-identical-after-native-normalization
```

- **Success:** verdict `byte-identical`, `semantically-identical`, or
  `semantically-identical-after-native-normalization`.
- **Output:** `$work\mmcv-reproducibility-ab.json` — **external** (the filename
  is also gitignored if written into the tree).
- **Record:** the verdict, every entry of `varianceSources`, the
  `nativeAnalysis` block for `mmcv/_ext.cp312-win_amd64.pyd`, and the embedded
  build paths the tool reports for **both** wheels.
- **Verdict meaning:**
  - `byte-identical` — C3 may enforce exact hash identity on rebuild;
  - `semantically-identical` — the installed members are byte-equal and only the
    container varies;
  - `semantically-identical-after-native-normalization` — the installed members
    are **not** byte-equal, and every byte by which they differ was proved to
    lie inside a documented build-metadata field, each of which the report
    names. This is the expected R1 outcome and it is **weaker** than the tier
    above it: the wheel cannot be re-derived by hash, so C3 binds to the
    selected canonical wheel plus this evidence, not to reproducibility;
  - `divergent-*` — **STOP.** The report names the cause. Two cases to read
    carefully before concluding anything:
    - `embedded-build-path-divergence` on the A-versus-B comparison is
      **expected and is not a failure of the compiler.** The two trees have
      different absolute paths and MSVC embeds them. It means the build is not
      relocatable, which is a real finding, but C2.2b is what tells you whether
      the *code* agrees. Record it and run C2.2b.
    - `undocumented-header-field-divergence` means a header word differs that
      this repository has not established the meaning of. The report decodes
      both values. **Do not normalise it locally.** Record the two values and
      stop; they are the input to the decision, not a step to get past.
- **Failure:** STOP for anything other than `embedded-build-path-divergence`.

### C2.2b Compare the intermediate objects

The wheel comparison sees the linked image, which carries the linker's variance
on top of the compiler's. This step asks the narrower question the A-versus-B
paths make unanswerable: did the **compiler** produce the same code?

Rebuild `$work\mmcv-src-a` a second time into `$work\obj-a2` — same path, same
virtual environment, same flags — so the only variable left is time.

```powershell
python tools\vision\compare_native_object_trees.py `
    --left  $work\obj-a `
    --right $work\obj-a2 `
    --output $work\mmcv-objects-a-a2.json `
    --require normalized-identical
```

- **Success:** verdict `identical` or `metadata-normalized-identical`, with
  `unresolvedCount` **0**.
- **Output:** `$work\mmcv-objects-a-a2.json` — **external**.
- **Record:** `comparedCount` (expected 136), `metadataNormalizedCount`,
  `unresolvedCount`, and the whole `normalizedFieldCounts` map. That map is the
  evidence: it names which field excused each object and how many objects it
  excused.
- **Must NOT change:** the source path or the virtual environment between the
  two builds. Changing either reintroduces embedded-path variance and the step
  stops answering its question.
- **Failure:** STOP. A non-zero `unresolvedCount` means the compiler is not
  deterministic on this toolchain, which is a far larger finding than a
  timestamp and changes C3, not just C2.

Also run the same comparison across `$work\obj-a` and `$work\obj-b`. It is
expected to report embedded build paths; run it so the result is on the record
rather than assumed.

### What C2.2 does and does not establish

It establishes that independent rebuilds produce **semantically equivalent**
native artefacts under a mechanically verified normalisation of named metadata
fields. It does **not** establish byte reproducibility, and no document may say
it does. It is a Development build reproducibility result: it is not a runtime
result, not a hardware qualification, and never satisfies a Production gate.

**Two predictions worth checking while you are there**, because they cost
nothing and both are currently inferences rather than observations:

- The report's `nativeAnalysis` block carries `detail.left.debugEntries`.
  `pip wheel` builds release, so there should be **no** debug directory and no
  CodeView record in `_ext.cp312-win_amd64.pyd`. If that list is empty, the
  ~463 embedded source-root strings come from `__FILE__`, not from a PDB path,
  and `/PDBALTPATH` is irrelevant here. If it is *not* empty, say so: an
  assumption in the plan is wrong.
- The A2/A3 BIGOBJ words at offsets 36 and 40 are decoded in the C2.2b report
  as `left`/`right` `uint32`/`hex`. Copy both values out verbatim. Two values a
  few thousand apart, in the 0x68xxxxxx range, would be two timestamps and
  would settle the question; a small integer would mean something else differs
  and the finding is larger than a timestamp.

**Do not add `/Brepro`, `--frandom-seed` or `/PDBALTPATH` to make this step
pass.** They are recorded in the plan as R2 candidates with the experiment that
would evaluate them. Adding a flag to change a verdict, before knowing whether
it changes the artefact, is what the checker exists to prevent.

## C2.3 Assemble the wheelhouse manifest

Choose **one** of the two MMCV wheels as the canonical artefact and record which
and why. Build A is the conventional choice; whichever it is, its SHA-256 is
what the lock, and through the lock the Runtime Pack identity, will bind to.
The other wheel is reproducibility evidence, not a substitute: the C2.2a report
establishes that they are semantically equivalent, not interchangeable by hash.

Collect every wheel (Torch, torchvision, the canonical MMCV wheel, and the
ordinary PyPI dependencies) into one directory, and write an origins file recording where each
came from:

```powershell
python tools\vision\build_wheelhouse_manifest.py `
    --wheelhouse $work\wheelhouse `
    --platform-variant windows-x86_64-cuda `
    --python-version 3.12.10 `
    --origins $work\origins.json `
    --output $work\wheelhouse-manifest.json
```

- **Success:** `{"ok": true, ...}`.
- **Output:** `$work\wheelhouse-manifest.json` — **external**.
- **Record:** the manifest SHA-256.
- **Failure:** STOP. The manifest refuses symlinks, subdirectories and strays;
  a refusal means the wheelhouse is not a clean set.

## C2.4 Freeze the lock

```powershell
python tools\vision\freeze_offline_lock.py `
    --wheelhouse $work\wheelhouse `
    --platform-variant windows-x86_64-cuda `
    --python-version 3.12.10 `
    --output src\vision\runtime\mmdetection-phase1-v1\windows-x86_64-cuda.lock
```

- **Success:** the lock is written and the transitive closure check passes.
- **Output:** `src\vision\runtime\mmdetection-phase1-v1\windows-x86_64-cuda.lock`
  — **committed**.
- **Record:** the lock's SHA-256; C3 and C5 both bind to it.
- **Determinism:** regenerate to a second path and compare byte for byte.
- **Failure:** STOP.

Also generate the tracked requirements projection C5 will bind to:

```powershell
python tools\vision\write_requirements_projection.py `
    --platform-variant windows-x86_64-cuda --python-version 3.12.10 `
    --output src\vision\runtime\mmdetection-phase1-v1\windows-x86_64-cuda.requirements.txt
```

- **Success:** `{"ok": true, "written": ...}`.
- **Output:** **committed**. It is derived from `src/vision/pyproject.toml`, so
  never hand-edit it; the boundary gate regenerates it and requires byte
  equality.
- **Record:** its SHA-256.

## C2.5 Prove the offline install

In a **clean** venv, with the network blackholed:

```powershell
python -m venv $work\verify-venv
$work\verify-venv\Scripts\python.exe -m pip install `
    --no-index --find-links $work\wheelhouse --only-binary=:all: `
    --require-hashes -r src\vision\runtime\mmdetection-phase1-v1\windows-x86_64-cuda.lock
$work\verify-venv\Scripts\python.exe -m pip check
$work\verify-venv\Scripts\python.exe -c "import torch, torchvision, mmengine, mmdet, mmcv, mmcv.ops; print(torch.__version__, torch.version.cuda)"
```

- **Success:** install completes with no network access, `pip check` is clean,
  every import succeeds, and the printed version is `2.6.0+cu124 12.4`.
- **Failure:** STOP. A missing wheel here means the lock is not a closure.

### Gate C2

All of C2.1–C2.5 passed, including both halves of C2.2. Only now is the branch
**BUILD-VERIFIED**.

**What BUILD-VERIFIED asserts here.** That the frozen toolchain produces a
working CUDA wheel, that one named wheel was selected as canonical, and that an
independent rebuild is semantically equivalent to it under a mechanically
verified normalisation of documented Windows native build metadata. It does
**not** assert byte reproducibility. Write the reproducibility verdict down
beside the canonical wheel's SHA-256: the verdict is what qualifies the SHA, and
a SHA recorded without it claims more than was measured.

---

# C3 — Runtime Pack

## C3.1 Build the pack from the frozen C2 inputs

The `--native-abi` is **not hand-typed**. It is the `nativeAbi` field of the
build contract, derived from the verified toolchain and pinned by test:

```powershell
python tools\vision\build_runtime_pack.py `
    --wheelhouse $work\wheelhouse `
    --lock src\vision\runtime\mmdetection-phase1-v1\windows-x86_64-cuda.lock `
    --requirements src\vision\runtime\mmdetection-phase1-v1\windows-x86_64-cuda.requirements.txt `
    --platform-variant windows-x86_64-cuda `
    --python-version 3.12.10 `
    --contract config\vision\windows-cuda-development-build-v1.json `
    --assembled-from-commit $head `
    --output $work\runtime-pack
```

`--contract` derives the ABI; there is no `--native-abi` to type. A `-cuda`
pack refuses to build without it.

- **Success:** `{"ok": true, ...}` and a `runtime-pack-manifest.json` in the
  output directory.
- **Output:** `$work\runtime-pack\` — **external**.
- **Record:** the `runtimePackId`, the manifest SHA-256, and the pack's
  `thirdPartyLockSha256` / `runtimeRequirementsSha256`.
- **Must NOT change:** the ABI. It is derived, and supplying `--native-abi`
  alongside `--contract` is refused when the two disagree
  (`native_abi_contract_conflict`) rather than silently preferring one.
- **Failure:** STOP.

## C3.2 Validate manifests and hashes

Re-hash every declared artefact against the manifest, and confirm the installed
state binds the manifest. On Windows this is what
`Assert-MaviVisionRuntimeInstalledStatePreflight` does at launcher startup, so
the check is: install the pack, then start the worker in CPU mode and confirm it
reaches the runtime without a `mavi_launch_failed:` refusal.

- **Success:** the worker starts.
- **Failure:** STOP. The refusal carries a stable code
  (`launch_runtime_pack_preflight_failed` and neighbours) — record it.

## C3.3 Prove CUDA Toolkit and compiler are not runtime prerequisites

On a machine (or a shell) with **no CUDA Toolkit and no MSVC on PATH**, install
the pack and run the import check from C2.5 against the pack's interpreter.

- **Success:** imports and `mmcv.ops` load with no Toolkit present.
- **Failure:** STOP. A pack that needs the build toolchain at runtime is not a
  Runtime Pack; Runtime Pack identity and build-toolchain identity are separate
  by design and this is the step that proves it.

## C3.4 Reproduce the pack identity

Rebuild the pack from the same inputs into a second output directory and compare
`runtimePackId`.

- **Success:** identical IDs.
- **Failure:** STOP, unconditionally.

This step is **not** a rebuild of MMCV, and C2.2's verdict does not soften it.
`runtimePackId` is derived from the platform variant, the Python version, the
native ABI, the lock digest and the requirements-projection digest — and the
lock pins the canonical MMCV wheel by SHA-256. The same inputs therefore must
produce the same identity, whatever the compiler does on a different day. If
they do not, the pack builder is non-deterministic, which is a defect in this
repository rather than a property of MSVC.

The converse is the thing to keep straight: because identity binds to the
canonical wheel's hash and not to the ability to reproduce that hash, a rebuilt
MMCV wheel is **not** substitutable into a pack. C2.2's evidence says the two
wheels are semantically equivalent; it does not make them the same artefact, and
nothing downstream may treat them as interchangeable.

### Gate C3

All of C3.1–C3.4 passed. Only now is the pack **RUNTIME-PACK-VERIFIED**.

---

# C4 — Development hardware qualification

## C4.1 Capture a fresh host observation

```powershell
python tools\vision\probe_windows_cuda_host.py --sanitized `
    --output $work\host-observation.json
```

- **Success:** `{"ok": true, ...}` and the GPU appears with compute capability
  `7.5`.
- **Output:** `$work\host-observation.json` — **gitignored**, never committed.
- **`--sanitized` is not optional.** Without it the file carries the raw GPU
  UUID, so the digest every later artefact records would name a file that may
  never be shown to anyone. The C4 builder refuses an unsanitised observation.
- **Record:** the file's SHA-256 and the `uuidSha256` of the target GPU.
- **Failure:** STOP.

## C4.2 Capture the toolchain observation

```powershell
python tools\vision\verify_windows_cuda_toolchain.py `
    --contract config\vision\windows-cuda-development-build-v1.json `
    --output $work\toolchain-observation.json
```

- **Success:** `"status": "passed"`.
- **Output:** **gitignored**.
- **Record:** its SHA-256.
- **What it now compares:** the CUDA toolkit version, the MSVC toolset **and**
  the Windows SDK against the frozen contract. A refusal reading
  `cuda_toolchain_msvc_toolset_mismatch:<observed>!=<frozen>` means the shell
  is not the qualified one -- fix the environment, do not edit the contract.
- **Note:** this compiles; it does **not** touch a GPU. Passing it is not
  hardware evidence.

## C4.3 Execute the native operators on the device

```powershell
$env:CUDA_DEVICE_ORDER = "PCI_BUS_ID"
python tools\vision\verify_windows_cuda_runtime.py --device-index 0 `
    --resolved-config src\vision\runtime\mmdetection-phase1-v1\rtmdet_m_resolved.py `
    --host-observation $work\host-observation.json `
    --output $work\runtime-verification.json
```

- **Success:** `"result": "passed"`, with `mmcvNmsExecutedOnCuda` and
  `torchMatmulExecutedOnCuda` both `true` and `peakMemoryAllocatedBytes` above
  zero.
- **Output:** **gitignored**.
- **Record:** its SHA-256, the `gpuUuidSha256`, the `driverVersion`.
- **Physical identity:** the CUDA ordinal is bound to a physical card through
  the driver's own inventory, never by assuming the CUDA and nvidia-smi orders
  agree. `CUDA_DEVICE_ORDER=PCI_BUS_ID` is required and the tool refuses
  without it.
- **Failure:** the tool **also writes the record**, with `result: "failed"` and
  both flags false. Keep it — C7 wants it. Then STOP.

## C4.4 Assemble the Development hardware evidence bundle

```powershell
python tools\vision\build_development_hardware_evidence.py `
    --host-observation $work\host-observation.json `
    --toolchain-observation $work\toolchain-observation.json `
    --runtime-verification $work\runtime-verification.json `
    --source-head-sha $head `
    --captured-at-utc (& $utc) `
    --operator-reference $op `
    --device-index 0 `
    --output $work\development-evidence.json
```

- **Success:** `{"ok": true, ...}`.
- **Output:** **gitignored**.
- **Record:** `evidenceBundleSha256` and `hostObservationSha256`.
- **What it refuses:** a run and an observation that do not name the same card
  by salted identity digest; disagreeing driver versions or memory; a run that
  does not name the observation it was produced against; a toolchain naming a
  different revision or target architecture; zero peak device allocation.
- **Failure:** STOP.

### Gate C4

Only now may `windows-x86_64-cuda` move from `pending-hardware-qualification` to
`qualified-development-hardware` in
`src/vision/runtime/mmdetection-phase1-v1/runtime.json`.

Use the bundle's `variantPatch` **verbatim** and add its `developmentEvidence`
block. It is machine-generated precisely so those identities are not typed by
hand. This is the one step in C4 that changes a committed file.

- **Output:** `runtime.json` — **committed**.
- **Consequence:** the runtime-profile SHA-256 changes, so qualification
  metadata binding it must be reissued (ADR-009 required follow-up 1–3).
- The variant is now **HARDWARE-QUALIFIED for Development**. It is not
  Production-qualified and cannot become so by this route.

---

# C5 — Overlay binding

Do **not** start C5 until Gate C4 has passed with a real bundle.

## C5.1 Bind the component overlay

Add `windows-x86_64-cuda` to
`src/vision/config/components/mmdetection-phase1-v1.json` with the exact
`runtimePackId`, `thirdPartyLockSha256`, `runtimeRequirementsSha256` and
`nativeAbi` recorded in C2.4 and C3.1.

- **Output:** **committed**.
- **Must NOT change:** the three protected CPU baseline files (see Final
  validation).

## C5.2 Add the boundary-gate matrix row

`.github/workflows/vision-runtime-component-boundary.yml` enforces this binding
and is matrix-driven, so a variant with no row is checked by nothing. Add:

```yaml
          - variant: windows-x86_64-cuda
            python-version: '3.12.10'
            native-abi: win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75
```

## C5.3 Update the two tests that are supposed to fail

These pin the pre-C5 state deliberately and must be changed **on purpose**:

- `test_every_declared_runtime_pack_is_covered_by_the_boundary_gate` — passes
  once C5.2 is done;
- `test_development_auto_still_chooses_cpu_against_the_committed_profile` and
  the declared-set assertion in `test_runtime_projection_repository_contract.py`
  — the property they pin has genuinely changed.

## C5.4 Verify device-resolution behaviour on the host

| Case | Command | Expected |
| --- | --- | --- |
| Explicit CUDA succeeds | `Start-MaviVisionWorker.ps1 -DevicePolicy cuda` | starts on `cuda:0`, reason `explicit_cuda` |
| Explicit CUDA fails closed | same, with the CUDA pack uninstalled | refusal `mavi_launch_failed:launch_runtime_pack_not_installed`, **never** CPU |
| Auto selects CUDA | `-DevicePolicy auto` | reason `cuda_selected` |
| Auto falls back | same, with the pack uninstalled | CPU, reason `cuda_pack_absent`, logged and persisted |

- **Failure:** any explicit-CUDA run that lands on CPU is a **STOP** and a
  defect report, not a configuration problem.

---

# C6 — Development end-to-end

Record each run as a `mavi-windows-cuda-development-e2e-run-v1` document (schema:
`tools/vision/windows-cuda-development-e2e-run.schema.json`). All five runs must
be over the **same media** and the **same frame count**.

```powershell
python tools\vision\build_development_e2e_evidence.py `
    --development-evidence $work\development-evidence.json `
    --run explicit-cuda=$work\run-explicit-cuda.json `
    --run auto-cuda=$work\run-auto-cuda.json `
    --run explicit-cpu=$work\run-explicit-cpu.json `
    --run restart-recovery=$work\run-restart-recovery.json `
    --run cuda-oom-recovery=$work\run-cuda-oom-recovery.json `
    --source-head-sha $head `
    --captured-at-utc (& $utc) `
    --operator-reference $op `
    --output $work\development-e2e-evidence.json
```

- **Success:** `{"ok": true, ...}`.
- **Output:** **gitignored**.
- **Record:** `evidenceBundleSha256`, `gpuUuidSha256`, `mediaSha256`.
- **What it refuses:** a CUDA case that resolved to CPU; an Auto fallback
  standing in for the Auto→CUDA case; a run on a card C4 did not qualify, at
  another ordinal, on an architecture C4 did not build, or under a different
  CUDA runtime; a C4 bundle whose own digest does not recompute; runs over
  different media; `trackCount: 0`; provenance claiming `verified`.
- **On the permitted Auto→CPU case:** it belongs in C7's matrix
  (`auto-pack-absent` and its seven siblings), not in C6's `auto-cuda` case. A
  legitimate fallback is a real result but is not evidence Auto chose CUDA.
- **Timing** is engineering characterisation only. No Production threshold may
  be derived from it.
- **Failure:** STOP.

---

# C7 — failure matrix

Print the matrix and use it as the run sheet:

```powershell
python tools\vision\build_failure_matrix_evidence.py --print-matrix `
    --scope hardware --source-head-sha x --captured-at-utc x --operator-reference x
```

37 cases: **7** exercisable anywhere (record before the session), **18** needing
the Windows launcher but no GPU, **12** needing a real device.

Record each as a `mavi-windows-cuda-failure-case-v1` document (schema:
`tools/vision/windows-cuda-failure-case.schema.json`), then:

```powershell
python tools\vision\build_failure_matrix_evidence.py --scope hardware `
    --development-evidence $work\development-evidence.json `
    --case auto-pack-absent=$work\case-auto-pack-absent.json `
    ... one --case per declared case ... `
    --source-head-sha $head `
    --captured-at-utc (& $utc) `
    --operator-reference $op `
    --output $work\failure-matrix-evidence.json
```

- **Success:** `{"ok": true, ...}` with `caseCount: 37`.
- **Output:** **gitignored**.
- **Record:** `evidenceBundleSha256`.
- **Scope is never implied.** A `hardware` bundle requires the C4 evidence and
  every hardware case must name the same card; a narrower scope may not carry a
  case it could not have observed.
- **Stable codes:** each case declares the failure codes it may legitimately
  report. A case carrying another case's code is refused.
- **Diagnostics:** a raw GPU UUID in a pasted driver message is redacted
  automatically, but diagnostics are bounded at 2000 characters — paste the
  relevant lines, not a whole log.
- **Failure:** a refused case is usually the observation, not the tool. Read the
  code: it names the case and the disagreement.

---

# Before leaving the host

```powershell
cd src\vision; python -m pytest -q; cd ..\..
python tools\verify_repo.py
python tools\vision\check_guard_coverage.py
python -m pytest -q tools\phase1\tests
.\tools\setup\Test-MaviSetupContracts.ps1
.\tools\setup\Test-MaviVisionRuntimeStateContracts.ps1
.\tools\setup\Test-MaviVisionModelPackStateContracts.ps1
.\tools\setup\Test-MaviVisionWorkerComponentContracts.ps1
```

Confirm the three protected CPU baseline files are **byte-identical** to
`main@0225779`:

```powershell
git hash-object src\vision\runtime\mmdetection-phase1-v1\windows-x86_64-cpu.lock   # aed2dd2e382cd6bb4a2c581b549a44378fca490b
git hash-object src\vision\runtime\mmdetection-phase1-v1\runtime.json              # 4af6574a27f27d87f72f2061a5f6d2d2d0252d78  (changes ONLY at Gate C4)
git hash-object src\vision\config\components\mmdetection-phase1-v1.json            # 3a0c210353940809c44ff50fca178a63d7b157ab  (changes ONLY at C5.1)
```

The CPU lock must never change. The other two change only at the gates named.

Then push and confirm hosted CI is green on the exact head.

## What must not happen here

- no Production qualification, and no change to Production qualification status;
- no `qualified-development-hardware` without a genuine C4 bundle;
- no substitution of a PyPI `torch` for `torch==2.6.0+cu124`;
- no `--allow-unsupported-compiler`, and no alternative MSVC toolset;
- no hand-typed Runtime Pack ID, native ABI, Python identity, binary identity or
  requirements projection where a tool derives it;
- no committed raw host observation, wheel, or evidence artefact other than the
  lock, the requirements projection, and the two gate-authorised config changes.
