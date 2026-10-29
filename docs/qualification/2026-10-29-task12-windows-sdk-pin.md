# Task 12 Windows CPU: MMCV wheel reproducibility and the Windows SDK build pin

- **Date:** 2026-10-29
- **Scope:** Task 12 `windows-x86_64-cpu` Runtime Binary Pack build only. This follows `2026-09-27-task12-windows-mmcv-toolchain-pin.md` (the compiler pin).
- **Outcome:** the committed MMCV wheel bytes are restored under a pinned Windows SDK build. Nothing identity-bearing changes: the lock, `runtimePackId`, `nativeAbi`, requirements and qualification status are all unchanged. No re-lock and no re-qualification.

## Symptom

From hosted image `win25-vs2026/20261021.278` onward, Task 12 `windows-x86_64-cpu` failed at *Regenerate and compare deterministic third-party lock*:

```
windows-x86_64-cpu.lock … differ: char 2323, line 27
```

Line 27 is `mmcv==2.1.0 --hash=sha256:…`, the locally built MMCV wheel. The failure reproduced on unmodified `main@8a03ce8d` (run 40874415956) and on PR #243, which does not touch the CPU build. Linux Task 12 passed throughout.

## Root cause, measured

| | Last green (run 39042669484, 2026-10-17) | Failing (run 40874415956, 2026-10-29) |
|---|---|---|
| Runner image | `win25-vs2026/20261007.264.1` | `win25-vs2026/20261021.278.1` |
| `cl.exe` / `link.exe` (pinned 17.14.40 Build Tools) | 19.44.35228 / 14.44.35228 | 19.44.35228 / 14.44.35228 |
| `VCToolsVersion` / `WindowsSDKVersion` | 14.44.35207 / 10.0.26100.0 | 14.44.35207 / 10.0.26100.0 |
| Image Windows SDK build (runner-images readme) | **10.1.26100.8249** | **10.1.26100.9457** |
| Python packages for the build (setuptools, wheel, ninja, numpy, torch 2.6.0+cpu) | pinned, identical | pinned, identical |
| MMCV wheel | `f1f0a6c9…d2c8`, 1066528 bytes | `f522bd08…c12c`, 1066527 bytes, twice (deterministic) |

The other differences between the runs cannot reach the wheel. pip is reinstalled to 26.2.1 in both. The unpinned Torch runtime dependencies `filelock`, `fsspec`, `networkx` and `pillow` are not build inputs of the MMCV extension.

The Windows SDK is serviced in place, like the MSVC toolset in September. Every 10.0.26100 build installs to the shared `C:\Program Files (x86)\Windows Kits\10\{Include,Lib,bin}\10.0.26100.0` folders. Visual Studio 2026 18.11 on the new image brought SDK build 9457. The 17.14.40 Build Tools installer leaves the newer shared SDK in place, and `vcvarsall … 10.0.26100.0` selects it. The workflow checked only the folder name, so it could not see the change.

## Controlled proof

Task 12 was run with every input identical except the SDK. The headers, import libraries and tools came from Microsoft's fixed-version NuGet packages, with the image's Windows Kits removed from every search path:

| Run | Windows SDK packages | MMCV wheel | Lock comparison |
|---|---|---|---|
| 40879191577 | `Microsoft.Windows.SDK.CPP{,.x64}` 10.0.26100.8249 | `f1f0a6c9…` = committed lock | pass |
| 40879197128 (control, branch not merged) | `Microsoft.Windows.SDK.CPP{,.x64}` 10.0.26100.9457 | `f522bd08…` = failing image | fail |

The 9457 packages reproduce the failing image's bytes exactly, so the NuGet payloads are equivalent to the image SDK of the same build. The SDK build is the only input that moved. In each run, a clean rebuild reproduced the wheel byte for byte.

## Resolution: restore the deterministic build

On Windows, Task 12 now has a step *Install pinned Windows SDK headers and libraries*, after the pinned Build Tools step. It:

- downloads `microsoft.windows.sdk.cpp` and `microsoft.windows.sdk.cpp.x64` version 10.0.26100.8249 from `api.nuget.org`;
- pins them by SHA-256: `f8787b2f6678164ae789bdca6247e696c2a0f529a39ceb969d6ef3d69a987131` and `dba411916afdd47c99fecdf7d5558df7679d291dc338746590ae9adf5fd0511b`;
- verifies them with `dotnet nuget verify --all`;
- extracts only `Include\10.0.26100.0\{ucrt,um,shared,winrt,cppwinrt}`, `bin\10.0.26100.0\x64`, `ucrt\x64` and `um\x64` to `C:\MaviBuildTools\winsdk-10.0.26100.8249`;
- rewrites `INCLUDE`, `LIB`, `LIBPATH` and `PATH`, so every `Windows Kits` entry is removed and the pinned roots replace them.

*Verify qualified Windows native build identity* now fails closed in each of these cases:

- any `\Windows Kits\` path remains in `INCLUDE`, `LIB`, `LIBPATH` or `PATH`;
- the pinned include and library roots are not all present;
- `rc.exe` or `mt.exe` resolves outside the pinned SDK.

All of this happens before anything is compiled.

The pin is recorded in the offline binary catalogue (`visionRuntime.windowsCpuBuildToolchain.windowsSdkBuild` and `windowsSdkPackages`), in the verification text of dependency policy `msvc-cpu-build-toolchain-win-x64`, and in the inventory. `verify_repo` keeps those records and the workflow identical.

Network use is build-time CI only, like the existing Build Tools, Torch and wheel acquisition. Nothing is added to any Runtime Pack, and there is no first-run or runtime download.

## Not changed

- `windows-x86_64-cpu.lock`: MMCV stays at `f1f0a6c9…`.
- `runtimePackId`, `nativeAbi` `win_amd64-msvc-14.44-sdk-10.0.26100.0`, and the requirements projection.
- All Linux identities and every qualification status.

## Known limits

- `nativeAbi` records the SDK folder version (`10.0.26100.0`), not the SDK build. As with the compiler build, the pin is enforced by the Task 12 build gate, not by Runtime Pack identity.
- The pin depends on nuget.org continuing to serve the immutable 10.0.26100.8249 packages. If they ever disappear, the download or SHA-256 check fails closed with a named error, and a deliberate, reviewed re-freeze becomes the path forward.
- Other inputs the image still supplies (`curl`, `tar`, `git`, PowerShell, the OS) are not compiled into the wheel. The CPython 3.12.10 headers and import library come from `setup-python`'s versioned toolcache archive.
