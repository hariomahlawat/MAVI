# Local Development and Test Runbook

This runbook aligns a Windows/Visual Studio workstation with the MAVI Quality Gate.

## Preferred setup: one click

On a prepared Development workstation, keep the extracted companion binary kit beside the repository:

```text
<workspace>/
  MAVI/
  MAVI-Offline-Binary-Kit/
```

Then double-click:

```text
Setup-MAVI-Development.cmd
```

The launcher auto-detects and verifies the sibling kit. Approve the Administrator prompt. Setup automatically prepares the supported .NET 10, Node.js 22.22.2+, Python 3.13, MAVI-owned PostgreSQL 18 + pgvector environment, `mavi_dev`/`mavi_test` databases, FFmpeg/ffprobe, machine configuration, offline dependency caches and test connection. It also validates the attached workspace when the offline caches are available.

After the first setup, restart Visual Studio once and press **F5**.

### Vision runtime bundle

The ordinary Development binary kit prepares the UI/API/database and the lightweight Python Development environment. Actual RTMDet inference uses a separate, source-bound **MAVI Vision Runtime Bundle** because the qualified Windows CPU graph is CPython 3.12.10 with the frozen Torch/MMDetection wheel closure and model checkpoint.

For the supported Windows CPU Development path, extract the exact Task-12 artifact beside the repository as:

```text
<workspace>/
  MAVI/
  MAVI-Offline-Binary-Kit/
  MAVI-Vision-Runtime-Bundle/
    bundle-manifest.json
    wheels/
    release/
    prerequisites/
```

A nested `windows-x86_64-cpu/` directory is also accepted.

Rerun `Setup-MAVI-Development.cmd`. Setup verifies every runtime-bundle artifact SHA-256, requires the bundle source commit to match the repository HEAD, installs the bundled signed CPython 3.12.10 runtime into ProgramData, creates an isolated runtime venv, installs the exact reviewed lock with `--no-index --require-hashes`, and records the installed bundle identity.

With Mavi.Api running from Visual Studio, start the worker by double-clicking:

```text
Start-MAVI-Vision-Worker.cmd
```

The launcher refuses a source/runtime commit mismatch and supplies the installed model/profile/runtime paths to the worker. A queued Development video should then move to Processing once the runtime reports READY.

The canonical MAVI services are deliberately fixed: Development PostgreSQL runs as `MAVI-Dev-PostgreSQL-18` on `127.0.0.1:55433`. Developers should not edit ports, PATH, connection strings or pgvector installation manually.

Use `tools/setup/Test-MaviEnvironment.ps1 -Profile Development` when you only want to check readiness without changing the machine.

## Supported Development baseline

- .NET 10 SDK
- Python 3.13.x
- Node.js 22.22.2+
- MAVI-owned PostgreSQL 18 on port 55433
- pgvector embedded in the approved PostgreSQL runtime pack
- app-local FFmpeg/ffprobe


## Run MAVI locally from Visual Studio

For normal local development, set **Mavi.Api** as the startup project and press **F5** (or **Ctrl+F5**).

The repository uses ASP.NET Core's development SPA proxy:

1. Visual Studio starts `Mavi.Api` on `https://localhost:62152`.
2. The SPA proxy starts `npm run dev` in `src/web/mavi-web` when Vite is not already running.
3. Vite listens only on `http://127.0.0.1:5173` with a strict port.
4. The browser is redirected to the Vite development UI.
5. Vite proxies `/api/*` back to the running ASP.NET Core API.

This behavior is local-development only. Published MAVI builds continue to serve the compiled React application from ASP.NET Core/IIS as same-origin static content.

### First local launch

After `Setup-MAVI-Development.cmd` completes, start **Mavi.Api** from Visual Studio. The setup process restores the supported offline dependencies when the cache is present, so no separate npm/pgvector/FFmpeg preparation should be necessary. A successful F5 launch should open the React UI rather than the API root.

The local API proxy target defaults to:

```text
https://localhost:62152
```

and is also set explicitly in the Visual Studio launch profile through `MAVI_API_PROXY_TARGET`.

### Manual frontend launch

If you intentionally want to run Vite yourself, keep `Mavi.Api` running and execute:

```powershell
cd src/web/mavi-web
npm run dev
```

Open `http://127.0.0.1:5173`. The strict port prevents Vite from silently moving to a different port and breaking the SPA-proxy contract.

### Local HTTPS certificate

If the browser or Vite proxy reports a local certificate problem, trust the .NET development certificate once:

```powershell
dotnet dev-certs https --trust
```

Restart Visual Studio afterward.

## Advanced release preparation

Developers normally do **not** run native-dependency installers manually. The release/preparation machine stages approved FFmpeg, PostgreSQL 18 + pgvector, SDK installers and offline dependency caches into canonical `vendor/...` preparation locations, builds the verified `MAVI-Offline-Binary-Kit`, and then assembles Production setup media from that kit. Loose `vendor/...` staging is never a normal target-workstation setup source.

See `docs/runbooks/mavi-offline-setup.md` for that build-side workflow.

## Adding or changing a dependency

Do not stop at updating a package file. Follow `docs/architecture/dependency-and-offline-packaging-policy.md` and update `config/dependencies/offline-dependency-policy-v1.json` in the same feature.

For ordinary managed dependencies, the existing cache builders are intentionally generic: NuGet restores the solution closure, npm uses `package-lock.json`, and the Python Development wheelhouse is rebuilt from `pyproject.toml`. If a feature introduces a new optional/native/model/runtime dependency that is outside those closures, update `config/dependencies/offline-binary-catalog-v1.json`, the companion binary kit, Setup/readiness and its verification before considering the feature complete.

## Automatic database migrations

MAVI applies pending EF Core migrations automatically during application startup in both Development and Production.

Startup is intentionally fail-closed:

1. the application connects to PostgreSQL;
2. it acquires a MAVI-specific PostgreSQL advisory lock;
3. it enumerates applied and pending migrations;
4. it applies pending EF Core migrations;
5. it verifies that no migration remains pending;
6. only then does the application begin serving requests.

If migration fails, times out, or the migration lock cannot be obtained within the configured interval, MAVI startup fails rather than serving against an unknown schema state.

Default settings are in `src/platform/Mavi.Api/appsettings.json`:

```json
"DatabaseMigrations": {
  "Enabled": true,
  "LockTimeoutSeconds": 120,
  "CommandTimeoutSeconds": 300
}
```

Production application database credentials must therefore have the schema privileges required by the repository's EF Core migrations. Do not use `EnsureCreated` and do not manually edit `__EFMigrationsHistory`.

The advisory lock serializes migration attempts from concurrent MAVI application starts against the same PostgreSQL server/database session environment. Routine startup against an already-current database performs only the migration-state check and does not modify schema history.

The integration-test host disables automatic startup migration by default because its fixture deliberately resets `mavi_test` and controls migrations explicitly. Dedicated integration tests opt in to startup migration and verify blank-database migration, idempotent current-database startup, and fail-fast lock timeout behavior.

## Managed Development database and integration-test connection

`Setup-MAVI-Development.cmd` owns the Development database environment. It creates and maintains:

- PostgreSQL service `MAVI-Dev-PostgreSQL-18` on `127.0.0.1:55433`;
- `mavi_dev`;
- `mavi_test`;
- pgvector in both databases; and
- machine-scoped `MAVI_TEST_DB_CONNECTION`.

Do not manually create the databases, switch the integration tests to port 5432, or point tests at another PostgreSQL instance as the normal workflow.

The integration fixture is intentionally destructive and may reset only the database named exactly `mavi_test`. If integration tests report a missing/incorrect connection, rerun `Setup-MAVI-Development.cmd` or use:

```powershell
powershell -ExecutionPolicy Bypass -File tools/setup/Test-MaviEnvironment.ps1 -Profile Development
```

Then restart Visual Studio if Setup changed the machine environment.

## Development device policy

The supported Development reference topology is a **single Windows workstation/laptop**. A second Linux or GPU machine is not required for routine development.

Vision execution has three intended device modes:

- **Auto** — prefer a compatible, qualified Windows CUDA runtime/GPU when available; otherwise use CPU with an explicit log/provenance record of the fallback.
- **CUDA** — require Windows CUDA. If the compatible runtime/device is unavailable, fail clearly; do not silently fall back to CPU.
- **CPU** — force CPU for reproducibility, debugging, comparison and machines without a usable GPU.

The device actually used must be observable in worker startup/runtime logs and processing provenance.

The worker now implements this device policy. Explicit `CUDA` never silently becomes CPU. The existing Windows CPU path remains available for deterministic regression/debugging. Windows CUDA still requires real compatible hardware/runtime qualification before it can be treated as qualified evidence.

Development `Auto` is resolved in two places, and both record a reason code:

- the Windows launcher resolves it before Python starts, by checking that a Windows CUDA Runtime Pack is installed, passes its manifest/state/artifact integrity preflight, matches the component's declared Runtime Pack identity, and that the configured device is present according to the NVIDIA driver;
- `RuntimeSupervisor` resolves it for any entry point that reaches Python with `MAVI_DEVICE_POLICY=auto`, by requiring a CUDA runtime variant that is either `qualified-hardware` or `qualified-development-hardware`, with a qualified offline lock and an available device. Production forbids `Auto` outright, so the Development state is honoured only where Production cannot reach.

No Windows CUDA Runtime Pack is declared in this phase, so Development `Auto` always resolves to the qualified CPU path and records `cuda_pack_absent` or `cuda_pack_not_declared`.

**Known gap, required before C4 hardware qualification.** The launcher's Auto check deliberately does not execute code from the candidate CUDA pack, which is why it cannot yet detect a Runtime Pack whose Torch CUDA runtime is installed but cannot initialise (an incompatible VC runtime, a missing CUDA DLL, or a driver older than the packed CUDA family). Once a CUDA Runtime Pack exists, `Auto` in that situation would select CUDA and the worker would then hard-fail, instead of falling back to CPU with a deterministic reason. Closing this needs a post-integrity runtime smoke probe — run only against a pack that has already passed the integrity preflight, so the non-executing trust order established for Auto is preserved — plus a new reason code in the closed vocabulary. It cannot be implemented or validated before a real CUDA Runtime Pack exists, so it is a C3/C4 requirement rather than a C1R one.

### Windows CUDA host observation

Before selecting or building a Windows CUDA Runtime Pack for a development machine, capture the actual NVIDIA host facts from repository root:

```powershell
python tools/vision/probe_windows_cuda_host.py --output windows-cuda-host-observation.json
```

The probe records Windows build/architecture, NVIDIA GPU identity, driver version, VRAM and the CUDA compatibility level advertised by the installed NVIDIA driver. It deliberately records `qualification.status=observation-only` and never decides that a PyTorch/CUDA/MMCV graph is qualified.

Review this observation before choosing the CUDA binary graph. In particular, do not infer that the current `torch 2.6.0+cu124` test fixtures are automatically correct for the machine.

The default output filename is ignored by Git because GPU UUID and workstation-specific identity are local engineering evidence. Do not commit the observation unless it has been deliberately sanitized and approved as a qualification artifact.

### Device resolution reason codes

Every worker run records why its device was selected, as `deviceResolutionReason`
in runtime provenance and in the completion contract. The vocabulary is closed
and shared between `tools/setup/Start-MaviVisionWorker.ps1` and
`src/vision/mavi_vision/runtime/provenance.py`; a code outside it is rejected
rather than recorded, so an offline deployment can always explain its device
choice from the attestation alone.

| Code | Meaning |
| --- | --- |
| `explicit_cpu` | CPU was requested explicitly. |
| `explicit_cuda` | CUDA was requested explicitly. CUDA failure never becomes CPU. |
| `cuda_selected` | Auto selected CUDA. |
| `cuda_pack_absent` | Auto chose CPU: no CUDA Runtime Pack is installed. |
| `cuda_pack_integrity_failed` | Auto chose CPU: the installed CUDA pack failed its manifest/state/artifact integrity preflight. |
| `cuda_pack_variant_mismatch` | Auto chose CPU: the installed pack is not `windows-x86_64-cuda`. |
| `cuda_pack_not_declared` | Auto chose CPU: no qualified CUDA Runtime Pack is declared for the component. |
| `cuda_pack_id_mismatch` | Auto chose CPU: the installed pack ID does not match the declared requirement. |
| `cuda_driver_probe_unavailable` | Auto chose CPU: the NVIDIA driver probe is not present. |
| `cuda_device_unavailable` | Auto chose CPU: the configured CUDA device was not available. |
| `cuda_driver_probe_failed` | Auto chose CPU: the driver/device probe raised an error. |

Production runs may not carry any Auto code, and an `auto` policy may not omit
the reason. Adding a code means adding it to both implementations; a contract
test fails otherwise.

### Current Windows CUDA engineering candidate

The reviewed C1 candidate is recorded in:

`docs/qualification/2026-09-18-windows-cuda-c1-compatibility-decision.md`

The candidate retains CPython 3.12.10, PyTorch 2.6.0+cu124, torchvision 0.21.0+cu124, MMCV 2.1.0, MMEngine 0.10.7 and MMDetection 3.3.0 for controlled C2/C3 engineering. The observed development laptop has a GTX 1650 Ti with 4096 MiB VRAM and NVIDIA driver 576.83.

This remains an **engineering candidate**, not a qualified Runtime Pack. Until C2-C5 complete, the authoritative Application Overlay must not declare a Windows CUDA Runtime Pack and Development `Auto` must continue to fall back to the existing qualified CPU path.

## Run the .NET suite

From the repository root:

```powershell
dotnet restore MAVI.sln
dotnet build MAVI.sln
dotnet test MAVI.sln
```

In Visual Studio, after restarting with `MAVI_TEST_DB_CONNECTION` available, run **Test > Run All Tests**. Integration tests should no longer fail with `MAVI_TEST_DB_CONNECTION is required`.

## Run the complete local quality checks

```powershell
python tools/verify_repo.py
python -m pytest -q tools/phase1/tests

cd src/vision
python -m pytest -q
cd ../..

cd src/web/mavi-web
npm ci
npm test
npm run typecheck
npm run build
cd ../../..
```

The target is parity with the hosted MAVI Quality Gate: repository verification, Task-17 deterministic acceptance-tool tests, .NET tests, Python tests, frontend tests/typecheck/build, PostgreSQL/pgvector availability, and FFmpeg availability must all succeed. Disconnected/hardware qualification is intentionally outside normal developer CI; follow `docs/runbooks/phase1-acceptance.md` for those proofs.

## Troubleshooting

### Many integration tests fail immediately

If failures complete in milliseconds and report that `MAVI_TEST_DB_CONNECTION` is missing, this is a workstation setup failure rather than dozens of independent application defects. Rerun `Setup-MAVI-Development.cmd`, verify the Development environment, restart Visual Studio, and rerun the tests.

### Integration tests reject the connection

If the message says tests may reset only `mavi_test`, do not weaken the safeguard or manually repoint tests. Verify the MAVI-owned Development environment; Setup should configure the canonical test database automatically.

### FFmpeg/ffprobe is missing on a connected preparation/development PC

Do not install FFmpeg globally and do not add an arbitrary FFmpeg folder to PATH. On a connected Windows machine, stage the repository-approved pack with:

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/setup/Prepare-MaviFfmpegWindows.ps1
~~~

The helper verifies the pinned source archive SHA-256 before staging `vendor/ffmpeg`. Rebuild `Mavi.Api` afterward so MSBuild copies the app-local tools into the output. This helper is a **connected preparation action**; the supported disconnected target workflow remains the verified `MAVI-Offline-Binary-Kit` and `Setup-MAVI-Development.cmd`.

If the staged pack already exists, rerun Setup or `Test-MaviEnvironment.ps1 -Profile Development`. Production never relies on PATH fallback.

### Tests pass in CI but fail on Windows

Treat this as a cross-platform defect until proven otherwise. Logical storage keys and HTTP contracts must remain OS- and culture-independent; physical path conversion belongs only inside storage implementations.
