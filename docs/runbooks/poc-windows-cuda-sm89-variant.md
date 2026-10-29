# PoC Windows CUDA Runtime Pack variant `sm_75;sm_89` (S1b)

**Profile:** `poc-single-host` only (ADR-020). **Not** a Production runtime; nothing here satisfies P1, P2 or P3 (ADR-008, ADR-009).
**Decision:** plan `docs/superpowers/plans/2026-10-28-mavi-poc-end-to-end.md` D9. **Register row:** A6 (built, hashed, locked); A7 (the bound observation on the RTX 4090 host, slice S12) is what can earn `qualified-development-hardware`.

## What this variant is

| | v1 (frozen, unchanged) | v2 (this variant) |
| --- | --- | --- |
| Build contract | `config/vision/windows-cuda-development-build-v1.json` | `config/vision/windows-cuda-development-build-v2.json` |
| Target GPUs | `sm_75` (`TORCH_CUDA_ARCH_LIST=7.5+PTX`) | `sm_75`, `sm_89` (`TORCH_CUDA_ARCH_LIST=7.5;8.9+PTX`) |
| Native ABI | `win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75` | `win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75-sm89` |
| Lock | `src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cuda.lock` | `src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cuda-sm75-sm89.lock` |
| Requirements projection | `windows-x86_64-cuda.requirements.txt` | the same file |
| Build host | controlled build host (authoritative) | the Development laptop, accepted by the owner for the PoC only (D9) |
| Status | `qualified-development-hardware` (laptop) | `built-hashed-locked` (catalogue `visionRuntime.windowsCudaPocSm89Candidate`) |

The platform variant is the same (`windows-x86_64-cuda`): same Python 3.12.10, the same torch `2.6.0+cu124` and torchvision `0.21.0+cu124` wheels, the same 60 other wheels. **The v2 lock differs from the v1 lock only in the MMCV wheel line**; `tools/verify_repo.py` enforces this, re-derives the Runtime Pack id from the lock and the ABI, and holds the contract, the catalogue entry and the shared toolchain identity equal.

torch `2.6.0+cu124` ships SASS for `sm_50 … sm_90` (`torch.cuda.get_arch_list()`), with no `sm_89` entry; on an `sm_89` GPU it runs through binary-compatible `sm_86` SASS. Only MMCV's native ops are recompiled.

## Rebuilding (only if the canonical wheel is lost)

The MMCV CUDA wheel is not byte-reproducible on this toolchain (runbook `windows-cuda-host-session.md`, C2.2). A rebuild is a **different artefact**: new SHA-256, new lock, new pack id, A6 and A7 re-done. The canonical wheel and the built pack are retained under `E:\MAVI-Controlled\PoC\S1b\` with `SHA256SUMS`.

All work under `E:\MAVI-Working\` (`TMP`/`TEMP` there; never C:). The recipe is v1's (`windows-cuda-host-session.md` C2/C3) with the v2 contract:

1. **Toolchain preflight.** In a shell with `vcvars64.bat -vcvars_ver=14.44.35207 10.0.26100.0` active and `MMCV_WITH_OPS=1 FORCE_CUDA=1 TORCH_CUDA_ARCH_LIST=7.5;8.9+PTX`:
   `python tools\vision\verify_windows_cuda_toolchain.py --contract config\vision\windows-cuda-development-build-v2.json --output <evidence>\toolchain-observation-v2.json`
   It compiles one probe for `-gencode compute_75/sm_75`, `compute_89/sm_89` and `compute_89` PTX and refuses a drifted toolset, SDK or `cl.exe` (`19.44.35229`).
2. **Inputs.** `pip download torch==2.6.0+cu124 torchvision==0.21.0+cu124 --index-url https://download.pytorch.org/whl/cu124 --only-binary=:all: --no-deps`; the rest of the closure with `pip download -r <v1 lock without mmcv/torch lines> --require-hashes --no-deps --only-binary=:all:`; `python-3.12.10-amd64.exe` (SHA-256 `67b5635e…95fb`, Authenticode `Valid`, ProductVersion `3.12.10150.0`).
3. **Build MMCV** at `57c4e25e06e2d4f8a9357c84bcd24089a284dc88` in a venv with torch, `setuptools==80.10.2`, `wheel`; `DISTUTILS_USE_SDK=1`, `MAX_JOBS=2`; `pip wheel . --no-build-isolation --no-deps`.
4. **Lock.** `tools\vision\freeze_offline_lock.py --wheelhouse <wheelhouse> --platform-variant windows-x86_64-cuda --python-version 3.12.10 --output src\vision\runtime\mmdetection-phase1-v1\windows-x86_64-cuda-sm75-sm89.lock`.
5. **Pack.** `tools\vision\build_runtime_pack.py --lock <v2 lock> --requirements src\vision\runtime\mmdetection-phase1-v1\windows-x86_64-cuda.requirements.txt --platform-variant windows-x86_64-cuda --python-version 3.12.10 --contract config\vision\windows-cuda-development-build-v2.json --python-installer <exe> --assembled-from-commit <sha> --output <pack>`. The ABI is derived from the contract.
6. **Verify on the laptop:** clean offline install of the lock (`--no-index --require-hashes`), `pip check`, torch + `mmcv.ops` import, and an MMCV CUDA op (`nms`, `roi_align`) executed on `cuda:0` (sm_75).
7. **Record** the canonical wheel SHA-256, lock SHA-256, `runtimePackId`, manifest SHA-256 and the compiled architecture list (`cuobjdump --list-elf`/`--list-ptx` on `mmcv\_ext.pyd`) in the catalogue entry and register row A6.

## Carrying and installing it

- **Kit:** `New-MaviOfflineBinaryKit.ps1 … -VisionCudaRuntimePack <v1 pack>,<v2 pack> -OnnxRuntimeGpuWheel <wheel>` copies each pack to `vendor\vision\runtime\<build>` (only a pack the release binding or the catalogue names) and the pinned onnxruntime-gpu wheel to `vendor\vision\onnxruntime-gpu`, and records them under `payload.pocVision`.
- **PoC bundle:** `New-MaviPocSetupBundle.ps1 … -VisionRuntimeCudaSource <v1 pack> -VisionRuntimeCudaSm89Source <v2 pack>`; the v2 pack lands in `vision\runtime\windows-x86_64-cuda-sm75-sm89\` and must carry the catalogue's `runtimePackId`.
- **Installer:** `Install-MAVI-PoC.cmd [-CudaRuntimePack Auto|sm75|sm75-sm89]`. `Auto` installs the first build whose contract lists the GPU's exact compute capability: **sm_75 keeps the v1 pack**; sm_89 gets the v2 pack; any other capability (for example sm_86) gets none. Naming a build installs it only if it targets the GPU (the v2 pack may be named on the sm_75 laptop to exercise it). Release metadata records the build, its contract and its own status (`built-hashed-locked`), never v1's.

## Known limit: the worker binding names the v1 pack

The release component binding (`src/vision/config/components/phase1-bindings-v2.json`) names exactly one `windows-x86_64-cuda` Runtime Pack, the v1 pack, and the launcher, the bundle builder and the Python resolver all enforce it (ADR-014). With the v2 pack installed, the launcher's Auto decision therefore resolves **CPU with reason `cuda_pack_id_mismatch`**, and explicit `-DevicePolicy CUDA` refuses. Accepting the v2 pack at worker launch needs an ADR-014 amendment (a Development runtime-variant binding for `poc-single-host`); it is tracked as a follow-up that must land before S12. The installer and kit work above do not depend on it.

## onnxruntime-gpu (Development grade, for S3/S4/S6)

- Pin: `onnxruntime-gpu==1.26.0`, `onnxruntime_gpu-1.26.0-cp312-cp312-win_amd64.whl`, SHA-256 `5f49c44689894650990e4c8a857d2edafc276fbd79bba57ceb224bd18d25d491` (equals PyPI), MIT.
- Why not the CPU pin (`onnxruntime==1.31.0`): every `onnxruntime-gpu` release from 1.27.0 on PyPI is a CUDA 13 build (`nvidia-cuda-runtime~=13.0`, driver ≥ 580); 1.26.0 is the last CUDA 12 build.
- It does not bundle CUDA or cuDNN. Verified on the laptop (sm_75, driver 576.83, CUDA Toolkit removed from `PATH`): with the torch `2.6.0+cu124` wheel's CUDA 12.4 / cuDNN 9.1 DLLs loaded (import torch, or `onnxruntime.preload_dlls(directory=<torch>\lib)`), the CUDA EP runs a convolution and matches torch to `4.8e-7`. A family that uses it without torch must ship CUDA 12 and cuDNN 9 runtime DLLs; that is the consuming slice's dependency change.
- Not bundled with the MMCV pack (v1 carries no onnxruntime).
