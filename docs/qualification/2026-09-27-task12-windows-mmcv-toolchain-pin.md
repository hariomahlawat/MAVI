# Task 12 Windows CPU: MMCV wheel reproducibility and the MSVC compiler-build pin

- **Date:** 2026-09-27
- **Scope:** Task 12 `windows-x86_64-cpu` Runtime Binary Pack build only.
- **Outcome:** the original, committed MMCV wheel bytes are restored under a pinned compiler. Nothing identity-bearing changes: the lock, `runtimePackId`, `nativeAbi`, requirements and qualification status are all unchanged.

## Symptom

From hosted image `win25-vs2026/20260922.246` onward, Task 12 `windows-x86_64-cpu` failed at *Regenerate and compare deterministic third-party lock*:

```
windows-x86_64-cpu.lock … differ: char 2322, line 27
```

Line 27 is `mmcv==2.1.0 --hash=sha256:…`, the locally built MMCV wheel. The failure reproduced on unmodified `main@1a20a562` (run 36314412687). Linux Task 12 passed throughout.

## Root cause, measured

| | Last green (run 35486319277, 2026-09-20) | Failing (e.g. run 36319483661) |
|---|---|---|
| Runner image | `win25-vs2026/20260907.229` | `win25-vs2026/20260922.246` |
| VS instance (`VSCMD_VER`) | 18.9.2 | 18.10.1 |
| Toolset directory (`VCToolsVersion`) | 14.44.35207 | 14.44.35207 |
| `cl.exe` / `link.exe` | 19.44.35228 / 14.44.35228 (from the wheel's Rich header) | 19.44.35229 / 14.44.35229 |
| Windows SDK | 10.0.26100.0 | 10.0.26100.0 |
| MMCV wheel SHA-256 | `f1f0a6c94fcbf91f1298e8038ea07a22a5f3a8ed0551103f58ecc5b1d608d2c8` | `4422ec501a669e43aecd997f883221ca0d75742d387dae9ce5fada2cd5a80cd2` |

Visual Studio services the 14.44 toolset **in place**: the directory name stays `14.44.35207` while every compiler and linker binary moves to a new build (`cl`, `c1`, `c1xx`, `c2`, `link`, `lib`, `mspdbcore`: all 35229 on the new image). The previous workflow pinned only the toolset *directory* (`toolset: "14.44"`, `VCToolsVersion` starts with `14.44.`), so it could not see the change.

**Controlled proof.** The fixed-version Visual Studio 2022 Build Tools bootstrappers were installed on today's image, with every other input identical to Task 12:

| Build Tools | `cl` / `link` | MMCV wheel SHA-256 |
|---|---|---|
| 17.14.39 | 19.44.35228 / 14.44.35228 | `f1f0a6c9…` = committed lock |
| 17.14.40 | 19.44.35228 / 14.44.35228 | `f1f0a6c9…` = committed lock (byte-identical to the archived 2026-09-20 wheel) |
| 17.14.41 | 19.44.35229 / 14.44.35229 | `4422ec50…` = current image |

Two clean builds on one current-image runner produced the same bytes (`4422ec50…` twice). The build is deterministic under a fixed compiler; the compiler build is the only input that moved.

## Why the bytes change

The old and new wheels were compared member by member:

- They have the same 528 members, in the same order, with identical ZIP metadata (the timestamps are normalised to 2024-01-01 by `SOURCE_DATE_EPOCH`).
- Exactly two members differ: `mmcv/_ext.cp312-win_amd64.pyd` (927744 bytes in both) and its `RECORD` line.

Within the extension, 392 bytes differ, all of them explained:

1. **Rich header.** The C++ compiler, linker, export and resource-converter entries record build 35228 versus 35229, and `e_lfanew` shifts (0x118 → 0x108) with the re-encoded Rich block.
2. **One code constant.** `.text` offset 0x60f69 is `mov edx, 0x0B96D89C` versus `0x0B96D89D`, which is `_MSC_FULL_VER` 194435228 versus 194435229, compiled into MMCV's `get_compiler_version()` (`mmcv/ops/csrc/pytorch/info.cpp`).
3. **`/Brepro` content hashes.** Because `/Brepro` derives these from the image content, they change with 1 and 2: the COFF timestamp, the POGO and REPRO debug-directory timestamps, the export-directory `TimeDateStamp`, and the 32-byte REPRO hash itself. The image has no CodeView/PDB record.

No other code or data byte differs.

## Resolution: restore the deterministic build

Task 12 now installs the **fixed-version VS 2022 17.14.40 Build Tools** on Windows instead of using the image's floating Visual Studio. The step:

- pins the bootstrapper by SHA-256 `aac092d0d839fd078e86b301d886130f1605891061242b36facf55ccbdd5a0a7`;
- requires a valid Microsoft Authenticode signature;
- installs only `VC.Tools.x86.x64` and `Windows11SDK.26100`;
- enters `vcvarsall x64 10.0.26100.0 -vcvars_ver=14.44`.

Before compiling, it asserts:

- `cl.exe` is `19.44.35228.0`;
- `link.exe` is `14.44.35228.0`;
- both come from the pinned installation.

It then proves that a clean rebuild reproduces the wheel byte for byte, as Linux already does. The regenerated lock must still equal the committed lock.

Network use is build-time CI only, like the existing Torch, wheel and CPython-installer acquisition. Nothing is added to any Runtime Pack, and there is no first-run or runtime download.

## Not changed

- `windows-x86_64-cpu.lock`: MMCV stays at `f1f0a6c9…`.
- `runtimePackId` `mavi-runtime-v2-5d6229da58554bc951ddc8bd719574c1b33109a7916afdf717339d8847e39e61`, `nativeAbi` `win_amd64-msvc-14.44-sdk-10.0.26100.0`, and the requirements projection.
- All Linux identities and every qualification status. No Production or CUDA qualification is promoted.

## Known limits and follow-ups

- `nativeAbi` records the toolset minor (`msvc-14.44`), not the compiler build. The pin is enforced by the Task 12 build gate, not by Runtime Pack identity. Encoding the compiler build into `nativeAbi` would change `runtimePackId` and needs its own reviewed decision.
- The pin depends on Microsoft continuing to serve the 17.14.40 fixed-version payload. If it ever stops, the SHA-256 check or the exact-build assertion fails closed with a named error, and a deliberate, reviewed re-freeze becomes the path forward.
- Task 10 still compiles MMCV with the image toolset. It verifies the semantic graph, not wheel bytes, so it is not affected.
