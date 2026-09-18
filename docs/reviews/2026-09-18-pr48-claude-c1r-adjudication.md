# PR #48 — Claude Cold Review C1R Adjudication

**Date:** 2026-09-18  
**PR:** #48 — Windows CUDA Development qualification foundation  
**Base:** `main@9b0b88f5c9d20ddfa8c4e835e454d24c69921b84`  
**Purpose:** Record the disposition of the independent Claude cold-review findings before C2 is authorized.

## Status vocabulary

- **FIXED** — repository correction is implemented and regression-covered.
- **FIXED / EMPIRICAL PROOF PENDING** — repository guardrail/tooling is implemented; the remaining fact must be observed on the Windows CUDA machine/build host.
- **DEFERRED TO LATER GATE** — not required to enter C2; the implementation plan now places it behind an explicit later gate.
- **ACCEPTED RISK / CONTROLLED** — the risk is real but is handled through an explicit design decision and evidence requirement.

## Confirmed defects

| Finding | Disposition | Repository action |
| --- | --- | --- |
| D1 — no production GPU identity provider | **FIXED** | Added `runtime/gpu_identity.py`; worker wires it into `RuntimeSupervisor`. Physical identity now includes UUID, PCI bus ID and compute capability. |
| D2 — MMCV may build CPU-only ops on GPU-less builder | **FIXED / EMPIRICAL PROOF PENDING** | CUDA build contract requires `MMCV_WITH_OPS=1`, `FORCE_CUDA=1`, `TORCH_CUDA_ARCH_LIST=7.5+PTX`. Added positive CUDA runtime verifier requiring MMCV NMS on CUDA. Actual native build proof is C2/C4 evidence. |
| D3 — target CUDA architecture not frozen | **FIXED / EMPIRICAL PROOF PENDING** | Build contract freezes compute capability 7.5 / sm75 / `7.5+PTX`; C4 verifier requires `sm_75` in Torch architecture list. Fresh host probe v2 must directly observe 7.5. |
| D4 — CPU Torch can enter CUDA-labelled pack | **FIXED** | Offline lock validation now enforces `+cu<digits>` for CUDA and `+cpu` for CPU; freeze/build paths share the invariant; regression tests added. |
| D5 — Auto executed candidate CUDA interpreter before trust checks | **FIXED** | Development Auto selection is now non-executing. It validates installed manifest/state/artifact binding first, checks authoritative component declaration, then uses OS-level `nvidia-smi` device availability. Python runs only after selection enters normal verified startup. |
| D6 — Auto CPU fallback had no reason | **FIXED** | Stable reason codes are emitted and propagated as `MAVI_DEVICE_RESOLUTION_REASON` into runtime provenance and the completion contract. |
| D7 — C4 Development outcome not representable without fake CI evidence | **FIXED** | ADR-009 and runtime metadata introduce `qualified-development-hardware` with non-CI Development evidence. Production profiles still require `qualified-hardware`. |
| D8 — cuda index did not prove physical GPU | **FIXED** | `CUDA_DEVICE_ORDER=PCI_BUS_ID`; provenance captures UUID, PCI bus ID and compute capability; worker/API contract and completion digest carry the physical identity. |
| D9 — CUDA acquisition/prerequisites absent from dependency governance | **FIXED** | Dependency policy/catalog now distinguish cu124 acquisition, NVIDIA driver runtime prerequisite, CUDA Toolkit/MSVC build-only prerequisites and VC++ runtime. Repository verifier requires this governance before a CUDA lock may exist. |
| D10 — VC++ redistributable undeclared | **FIXED AT POLICY LEVEL; C3 LOAD PROOF PENDING** | VC runtime is now a controlled runtime prerequisite. Native MMCV import/load smoke proof remains a C3 installation gate. |
| D11 — editing runtime profile invalidates existing qualification binding | **FIXED IN PLAN / DEFERRED TO C4-C5** | ADR-009 and implementation plan explicitly require qualification reissue and CPU regression proof whenever Development CUDA evidence changes the runtime-profile identity. No runtime metadata has yet been promoted. |
| D12 — semantic Torch comparison rejected `+cu124` before C4 | **FIXED** | PEP 440 public semantic version is used for semantic graph comparison; exact binary-version validation remains separate and strict. |
| D13 — host observation schema existed but was not exercised | **FIXED** | Probe v2 schema is validated with Draft 2020-12 tests, including negative conformance cases. |
| D14 — Development result could contaminate P1 acceptance gate | **FIXED AT RUNTIME-STATE BOUNDARY; DEVELOPMENT GATE EVIDENCE DEFERRED TO C4** | P1 verification rejects `qualified-development-hardware`; regression test proves it. Development evidence is stored separately and must not set Production qualification gates. C4 evidence tooling must retain this separation. |
| D15 — probe omitted load-bearing hardware facts and leaked UUID to stdout | **FIXED / FRESH OBSERVATION PENDING** | Probe v2 adds compute capability, PCI ID, free/used memory, driver/display mode and optional build-toolchain facts. Stdout is sanitized by default; raw UUID remains local evidence only. |

## Risks requiring empirical verification

| Risk | Disposition | Required evidence |
| --- | --- | --- |
| R1 — CUDA 12.4 may reject MSVC 14.44 | **PENDING — BLOCKS C2** | Run `verify_windows_cuda_toolchain.py` with CUDA Toolkit 12.4. Freeze the actual successful MSVC toolset and SDK; do not use `--allow-unsupported-compiler`. |
| R2 — MMCV CUDA wheel byte reproducibility | **PENDING — MUST COMPLETE BEFORE C3** | Build twice from clean controlled inputs and compare bytes. If irreducibly non-deterministic, stop and adopt a separate ADR for an archived hash-pinned controlled binary input. |
| R3 — Windows Torch cu124 dependency markers | **TOOLING READY / PENDING OBSERVATION** | Run `inspect_windows_cuda_torch_wheel.py` against the real cp312 win_amd64 wheel. |
| R4 — CUDA DLL inventory inside Torch Windows wheel | **TOOLING READY / PENDING OBSERVATION** | Same wheel inspector enumerates and hashes the CUDA DLL inventory. |
| R5 — pack/media/disk footprint | **DEFERRED TO C2 AS MEASURED INPUT** | Record wheelhouse size, Runtime Pack size, installed venv size and replacement peak-disk requirement before offline media freeze. |
| R6 — 4 GB VRAM practical envelope | **DEFERRED TO C4/C6** | Capture max allocated/reserved CUDA memory, nvidia-smi free/used memory, host RAM, full `2min.mp4` run and bounded OOM/recovery evidence. |

## Optional improvements from review

- O1 CUDA-aware `nativeAbi`: **implemented**; CUDA packs require CUDA family + sm architecture and CPU packs reject CUDA ABI labels.
- O2 cache paths: **deferred before C5**; no Production/Development CUDA authoritative launch yet.
- O3 launcher TOCTOU reduction: **partially superseded** by non-executing candidate selection; final selected runtime is revalidated before launch.
- O4 uninstall/stale CUDA root handling: **deferred before C5**.
- O5 explicit reason when driver-advertised CUDA version is unavailable: **low priority; retain for C1R cold review**.
- O6 minimum driver bound for cu124: **must be frozen from authoritative compatibility evidence before C4**, not guessed from the laptop's current driver.

## C1R exit criteria

Repository-side C1R may be called **green** only when:

1. the full PR exact head passes all hosted gates;
2. the C# / Python / canonical JSON completion contracts agree;
3. GPU identity and Development-vs-Production separation tests pass;
4. no CUDA lock or authoritative CUDA Runtime Pack has been committed;
5. the Windows CPU lock and existing qualified CPU Runtime Pack remain unchanged.

C2 remains blocked even after repository-side C1R is green until:

- the fresh host observation v2 is reviewed; and
- R1 freezes an actually working CUDA 12.4 + MSVC + Windows SDK toolchain.

## Qualification boundary

Nothing in this adjudication marks Windows CUDA, P1, P2, the development laptop, or any CUDA Runtime Pack as Production-qualified.
