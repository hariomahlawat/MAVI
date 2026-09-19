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
the active one, then start PowerShell inside it:

```
powershell -NoExit
```

Every fenced block in this runbook is PowerShell. The Native Tools shortcut
opens `cmd.exe`, so running them there fails on the first line; starting
PowerShell *from within* it keeps the 14.44 toolset on `PATH`, which is the
part that must not change. Do not open PowerShell from the Start menu instead:
the toolset would not be the frozen one.

Create a virtual environment per build tree and install the build inputs into
it. Torch must be installed, not merely downloaded: MMCV's `setup.py` imports
`torch` to obtain `CUDAExtension`, and `--no-build-isolation` means nothing
else will provide it.

```powershell
python -m venv $work\venv-a
$work\venv-a\Scripts\python.exe -m pip install --no-index `
    --find-links $work\wheelhouse torch torchvision
$work\venv-a\Scripts\python.exe -m pip install "setuptools==80.10.2" wheel
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
separate clean trees**, `$work\mmcv-src-a` and `$work\mmcv-src-b`, and in each
(from inside that tree, with that tree's venv):

```powershell
$work\venv-a\Scripts\python.exe -m pip wheel . `
    --no-build-isolation --no-deps --wheel-dir $work\build-a
```

- **Success:** `mmcv-2.1.0-cp312-cp312-win_amd64.whl`, roughly 9.5 MB.
- **Output:** `$work\build-a\*.whl`, `$work\build-b\*.whl` — **external**.
- **Record:** SHA-256 and byte size of each wheel.
- **Must NOT change:** `--no-build-isolation` (isolation would install an
  unpinned setuptools and defeat the pin above) or `--no-deps`.
- **Must NOT change:** the `--wheel-dir` for a given build. Two builds writing
  to one directory silently overwrite each other, and since no two builds of
  this wheel are byte-identical, the hash you recorded would then belong to a
  file that no longer exists. C2.3 binds the lock to that hash.
- **Failure:** STOP.

**Preserve the intermediate objects before anything cleans them.** `pip wheel`
leaves them in the *source tree*, at
`build\temp.win-amd64-cpython-312`, not in the wheel directory. Copy each
tree's aside before doing anything else:

```powershell
Copy-Item -Recurse $work\mmcv-src-a\build\temp.win-amd64-cpython-312 $work\obj-a
Copy-Item -Recurse $work\mmcv-src-b\build\temp.win-amd64-cpython-312 $work\obj-b
```

They are the evidence for C2.2b and a rebuild deletes them.

### C2.2a Compare the wheels

Two comparisons, answering two different questions. Both use wheels you already
have; neither needs a rebuild.

**The one that matters: A2 versus A3** — same source tree, same venv, so the
only variable is time. This is the comparison that establishes there is no
unexplained native divergence.

```powershell
python tools\vision\compare_wheel_reproducibility.py `
    --left  $work\build-a2\mmcv-2.1.0-cp312-cp312-win_amd64.whl `
    --right $work\build-a3\mmcv-2.1.0-cp312-cp312-win_amd64.whl `
    --output $work\mmcv-reproducibility-a2a3.json
```

- **Expected:** `verdict` `semantically-identical-after-native-normalization`,
  and `nativeAnalysis["mmcv/_ext.cp312-win_amd64.pyd"].classification`
  `metadata-normalized-identical`.
- **This is the C2 acceptance evidence.** If it holds, two independent builds
  of the frozen recipe differ only in named build-metadata fields, and the
  compiled code is the same. That is the whole question.

**The other: A versus B** — different source trees, so MSVC embeds two
different absolute roots. This one is about *relocatability*, not correctness.

```powershell
python tools\vision\compare_wheel_reproducibility.py `
    --left  $work\build-a\mmcv-2.1.0-cp312-cp312-win_amd64.whl `
    --right $work\build-b\mmcv-2.1.0-cp312-cp312-win_amd64.whl `
    --output $work\mmcv-reproducibility-ab.json
```

- **Expected:** `verdict` `divergent-content`, with the `.pyd` classified
  `embedded-build-path-divergence`. That is the correct answer and not a
  failure of the compiler; record it and move on.

**There is deliberately no `--require` on either.** Both are **recording runs**:
their job is to put the variance on the record. Enforcing a tier on A-vs-B
would fail on the expected result.

- **Expected:** `verdict` is `divergent-content`. Exit code 0 (nothing is
  being enforced).
- **Output:** both JSON files — **external** (the filenames are also gitignored
  if written into the tree).
- **Record:** for each, the `verdict`, every entry of `varianceSources`, the
  embedded build paths reported for **both** wheels, and
  `nativeAnalysis["mmcv/_ext.cp312-win_amd64.pyd"].classification` with the
  `normalizedFields` it names.

**Read the verdict and the classification as two different things.** The
*verdict* describes the whole wheel and is one of `byte-identical`,
`semantically-identical`,
`semantically-identical-after-native-normalization`, `divergent-inventory` or
`divergent-content`. The *classification* describes one native member and is
reported under `nativeAnalysis`. `embedded-build-path-divergence` is a
classification, never a verdict; expecting to see it as the verdict will send
you looking for something that cannot appear.

What the member classification means here:

| `nativeAnalysis[...].classification` | Meaning | Action |
| --- | --- | --- |
| `embedded-build-path-divergence` | The two trees' absolute paths are compiled in. **Expected for A-vs-B, and a defect if it appears for A2-vs-A3.** | Record it; continue |
| `metadata-normalized-identical` | Every differing byte was inside a named metadata field. **Expected for A2-vs-A3; this is the acceptance evidence.** | Record which fields; continue |
| `undocumented-header-field-divergence` | A header word differs whose meaning this repository has not established. Both values are decoded in the report | Record both values; continue to C2.2b |
| `unexplained-native-difference` | Bytes differ that nothing accounts for | **STOP** |
| `native-size-mismatch` | The images are different sizes | **STOP** |
| `unparsable-native-format` | The `.pyd` did not parse | **STOP** |

- **Failure:** STOP on the last three only. Do **not** re-run with different
  inputs to obtain a different classification.

### C2.2b Compare the intermediate objects

The wheel comparison sees the linked image, which carries the linker's variance
on top of the compiler's, and A-vs-B additionally carries two different source
roots. This step asks the narrower question those make unanswerable: did the
**compiler** produce the same code?

**Use the objects you already preserved.** The first host session kept A2's and
A3's object trees. Point the tool at those. Do **not** rebuild MMCV to produce
fresh ones: a rebuild costs the better part of an hour and answers no question
that the preserved trees do not already answer.

```powershell
python tools\vision\compare_native_object_trees.py `
    --left  $work\obj-a2 `
    --right $work\obj-a3 `
    --output $work\mmcv-objects-a2-a3.json
```

(Only if those trees are gone: rebuild `$work\mmcv-src-a` once, into a
**different** wheel directory, and copy `build\temp.win-amd64-cpython-312`
aside first.)

**No `--require`**, for a reason that is the one open question of this phase.
The first session measured a `/bigobj` CPU object differing at offsets 8, 9, 36
and 37. Offset 8 is the documented `TimeDateStamp` and is normalised. Offset 36
is `MetaDataSize`, which is **not** a timestamp in the documented layout, so the
tool reports it rather than excusing it — which means a **non-zero**
`unresolvedCount` is the expected outcome today.

- **Expected:** `comparedCount` 136; every unresolved object classified
  `undocumented-header-field-divergence` on `bigobj.MetaDataSize` (and possibly
  `bigobj.MetaDataOffset`); no object classified anything else.
- **Output:** `$work\mmcv-objects-a2-a3.json` — **external**.
- **Record:** `comparedCount`, `metadataNormalizedCount`, `unresolvedCount`,
  `normalizedFieldCounts`, `outOfScopeNativeFiles`, and from
  `unresolved[].analysis.residualDifferences` the decoded `left` and `right`
  values for `bigobj.MetaDataSize`.
- **Failure:** STOP if any object is classified `unexplained-native-difference`,
  `native-size-mismatch` or `unparsable-native-format`, or if `comparedCount`
  is not 136. Those would mean the compiler itself differs, which changes C3
  rather than just C2.

#### How much this question is worth

`MetaDataSize` and `MetaDataOffset` are CLR metadata fields. A native object
does not carry CLR metadata, and the native linker does not consume them, so a
difference there is **not** on the path to the code that runs.

That is an argument, not a proof — but the proof is cheap and you already have
it: **the linked image is the artefact that executes.** If the `.pyd` in C2.2a
reduces to `metadata-normalized-identical`, then whatever differs at object
offset 36 did not change a byte the linker emitted, and the functional question
is closed regardless of what the field turns out to be.

So: record the two decoded values, and read them against the `.pyd` result.
Two values a few thousand apart in the `0x68xxxxxx` range are two timestamps
and the field can later be ratified as normalisable. A small integer means
something else, and it still carries no functional risk if the image compares
clean. **Do not rebuild MMCV to investigate this further.** It is a labelling
question about a header word, tracked openly, not a blocker — and it is not
worth an hour of build time, let alone a change to the frozen recipe.

Also run the same comparison across `$work\obj-a` and `$work\obj-b` if those
trees are still present. It is expected to report embedded build paths; run it
so the result is on the record rather than assumed. If they are gone, skip it:
A-vs-B relocatability is already recorded by C2.2a.

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
pass**, and do not chase byte-for-byte equality across Development rebuilds.
The target here is a known-good canonical artefact with its recipe recorded and
no unexplained native divergence — not theoretical reproducibility. Those flags
are recorded in the plan as R2 candidates; Production carries the stronger
qualification burden, and this is not it.

## C2.3 Acquire the remaining dependencies and assemble the manifest

C2.1 used `--no-deps`, so the wheelhouse holds only Torch and torchvision. The
rest of the closure -- `mmengine`, `mmdet`, `numpy`, `pillow` and their
transitive dependencies -- must be downloaded from PyPI into the *same*
directory, or the manifest, the lock's closure check and the offline install
all fail for want of them.

```powershell
python -m pip download mmengine mmdet numpy pillow `
    --only-binary=:all: --dest $work\wheelhouse
```

- **Success:** the wheelhouse now holds the full set.
- **Must NOT change:** the index. These come from PyPI; only Torch,
  torchvision and MMCV are special. If a dependency resolves to a `+cu124`
  version here, stop: it belongs to the CUDA set and should have come from
  C2.1.
- **Failure:** STOP.

Copy the **canonical** MMCV wheel into the wheelhouse as well -- one of the two,
chosen and recorded per the paragraph below.


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

`origins.json` maps every wheel filename to where it came from:

```json
{
  "torch-2.6.0+cu124-cp312-cp312-win_amd64.whl": {
    "kind": "index",
    "indexUrl": "https://download.pytorch.org/whl/cu124"
  },
  "mmcv-2.1.0-cp312-cp312-win_amd64.whl": {
    "kind": "local-build",
    "sourceRepository": "https://github.com/open-mmlab/mmcv",
    "sourceCommit": "57c4e25e06e2d4f8a9357c84bcd24089a284dc88",
    "buildToolchain": "win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75"
  }
}
```

Every wheel needs an entry and every entry needs a wheel; the manifest refuses
either mismatch.

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

A Windows Runtime Pack embeds the CPython installer, and `build_runtime_pack.py`
refuses without one (`runtime_pack_python_installer_required`). Acquire it
first, and check what you acquired:

```powershell
Invoke-WebRequest -Uri https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe `
    -OutFile $work\python-3.12.10-amd64.exe
(Get-AuthenticodeSignature $work\python-3.12.10-amd64.exe).Status
(Get-Item $work\python-3.12.10-amd64.exe).VersionInfo.ProductVersion
```

- **Success:** signature `Valid`, ProductVersion `3.12.10150.0`.
- **Output:** `$work\python-3.12.10-amd64.exe` — **external**.
- **Record:** its SHA-256.
- **Failure:** STOP. An unsigned or mismatched installer is not substitutable.


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
    --python-installer $work\python-3.12.10-amd64.exe `
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

The Development laptop is the C4/C6 execution target and **not** the build
host, so this is a new shell on a different machine. Re-establish the session
variables and the contract's build environment before anything else -- the
toolchain verifier in C4.2 compares `os.environ` against the contract and
refuses with `cuda_build_environment_mismatch:<name>` on any difference:

```powershell
$head = (git rev-parse HEAD).Trim()
$op   = "<workstation or operator label>"
$work = "C:\mavi-c4"
New-Item -ItemType Directory -Path $work -Force | Out-Null
$env:MMCV_WITH_OPS = "1"
$env:FORCE_CUDA = "1"
$env:TORCH_CUDA_ARCH_LIST = "7.5+PTX"
$env:MAX_JOBS = "2"
$env:DISTUTILS_USE_SDK = "1"
```

`$head` must be the same commit you recorded at C2. If it is not, stop: the
assemblers require every artefact to name one head.

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
$packPython = "$work\runtime-pack\venv\Scripts\python.exe"
$resolved = "<Model Pack root>\rtmdet_m_resolved.py"
& $packPython tools\vision\verify_windows_cuda_runtime.py --device-index 0 `
    --resolved-config $resolved `
    --host-observation $work\host-observation.json `
    --output $work\runtime-verification.json
```

Two things here are easy to get wrong and both invalidate the result.

**The interpreter must be the pack's.** The tool imports `torch` from whatever
interpreter runs it, and the record it writes is what C4.4 turns into a
qualification. A bare `python` qualifies whichever environment happened to be
on `PATH`, which is worse than failing.

**`rtmdet_m_resolved.py` is not in this repository.** It is generated by
`tools/vision/resolve_mmdet_config.py` and ships inside the **Model Pack**;
`src\vision\runtime\mmdetection-phase1-v1\` contains only the locks, the
requirements projections and `runtime.json`. Point `--resolved-config` at the
installed Model Pack's copy, and check it is the qualified one:

```powershell
(Get-FileHash $resolved -Algorithm SHA256).Hash.ToLower()
```

It must equal `resolvedConfig.sha256` in
`src\vision\runtime\mmdetection-phase1-v1\runtime.json`. If it does not, stop:
you would be qualifying a different model configuration from the one the
release metadata describes.

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

37 cases: **7** exercisable anywhere (record before the session), **20** needing
the Windows launcher but no GPU, **10** needing a real device.

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
