# Local Development and Test Runbook

This runbook aligns a Windows/Visual Studio workstation with the MAVI Quality Gate.

## Preferred setup: one click

On a prepared Development repository, double-click:

```text
Setup-MAVI-Development.cmd
```

Approve the Administrator prompt. Setup automatically prepares the supported .NET 10, Node.js 22.13+, Python 3.13, MAVI-owned PostgreSQL 18 + pgvector environment, `mavi_dev`/`mavi_test` databases, FFmpeg/ffprobe, machine configuration, offline dependency caches and test connection. It also validates the attached workspace when the offline caches are available.

After the first setup, restart Visual Studio once and press **F5**.

The canonical MAVI services are deliberately fixed: Development PostgreSQL runs as `MAVI-Dev-PostgreSQL-18` on `127.0.0.1:55433`. Developers should not edit ports, PATH, connection strings or pgvector installation manually.

Use `tools/setup/Test-MaviEnvironment.ps1 -Profile Development` when you only want to check readiness without changing the machine.

## Supported Development baseline

- .NET 10 SDK
- Python 3.13.x
- Node.js 22.13+
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

Developers normally do **not** run native-dependency installers manually. The release/preparation machine stages approved FFmpeg, PostgreSQL 18 + pgvector, SDK installers and offline dependency caches into the canonical `vendor/...` locations, then `New-MaviOfflineSetupBundle.ps1` produces the single disconnected setup bundle.

See `docs/runbooks/mavi-offline-setup.md` for that build-side workflow.

## Adding or changing a dependency

Do not stop at updating a package file. Follow `docs/architecture/dependency-and-offline-packaging-policy.md` and update `config/dependencies/offline-dependency-policy-v1.json` in the same feature.

For ordinary managed dependencies, the existing cache builders are intentionally generic: NuGet restores the solution closure, npm uses `package-lock.json`, and the Python Development wheelhouse is rebuilt from `pyproject.toml`. If a feature introduces a new optional/native/model/runtime dependency that is outside those closures, extend the cache/runtime-pack/Setup path and its verification before considering the feature complete.

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

### FFmpeg/ffprobe tests fail

Rerun Setup or `Test-MaviEnvironment.ps1 -Profile Development`. The supported Development path uses the approved staged/app-local FFmpeg pack; Production never relies on PATH fallback.

### Tests pass in CI but fail on Windows

Treat this as a cross-platform defect until proven otherwise. Logical storage keys and HTTP contracts must remain OS- and culture-independent; physical path conversion belongs only inside storage implementations.
