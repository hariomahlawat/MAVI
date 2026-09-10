# Local Development and Test Runbook

This runbook aligns a Windows/Visual Studio workstation with the MAVI Quality Gate. It covers the prerequisites that are intentionally supplied by GitHub Actions but are not automatically created by Visual Studio Test Explorer.

## Required local toolchain

Install and verify:

```powershell
dotnet --info
python --version
node --version
npm --version
ffmpeg -version
ffprobe -version
psql --version
```

Current repository baseline:

- .NET 10 SDK
- Python 3.13+
- Node.js 22+
- PostgreSQL 18
- pgvector extension compatible with PostgreSQL 18
- FFmpeg and ffprobe

## PostgreSQL databases

MAVI development and integration tests use separate databases. Never point the integration-test variable at the development or production database.

Create the databases using `database/scripts/create-local-databases.sql`, running the statements individually if required by the PostgreSQL client:

```sql
CREATE DATABASE mavi_dev;
CREATE DATABASE mavi_test;
```

The integration fixture is destructive by design: it drops and recreates the `public` schema and the `vector` extension while preparing tests. For that reason, the code rejects any integration-test connection whose database name is not exactly `mavi_test`.

## Configure the integration-test connection

Set `MAVI_TEST_DB_CONNECTION` to the dedicated test database. Substitute your local PostgreSQL credentials; do not commit passwords or connection strings containing secrets.

For the current PowerShell session:

```powershell
$env:MAVI_TEST_DB_CONNECTION = "Host=localhost;Port=5432;Database=mavi_test;Username=postgres;Password=<LOCAL_PASSWORD>"
```

For Visual Studio Test Explorer, Visual Studio must inherit the variable. One simple Windows approach is to create a user environment variable and then restart Visual Studio:

```powershell
setx MAVI_TEST_DB_CONNECTION "Host=localhost;Port=5432;Database=mavi_test;Username=postgres;Password=<LOCAL_PASSWORD>"
```

`setx` affects future processes, not the already-running shell or Visual Studio instance. Close all Visual Studio instances and reopen the solution after setting it.

Alternatively, define `MAVI_TEST_DB_CONNECTION` through the Windows Environment Variables UI and restart Visual Studio.

## Confirm PostgreSQL and pgvector

Before running integration tests:

```powershell
pg_isready -h localhost -p 5432 -U postgres -d mavi_test
psql "Host=localhost Port=5432 Database=mavi_test User=postgres" -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql "Host=localhost Port=5432 Database=mavi_test User=postgres" -c "SELECT extname FROM pg_extension WHERE extname='vector';"
```

If `CREATE EXTENSION vector` is unavailable, install/enable pgvector for the same PostgreSQL major version before continuing.

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

The target is parity with the hosted MAVI Quality Gate: repository verification, .NET tests, Python tests, frontend tests/typecheck/build, PostgreSQL/pgvector availability, and FFmpeg availability must all succeed.

## Troubleshooting

### Many integration tests fail immediately

If failures complete in milliseconds and show:

```text
MAVI_TEST_DB_CONNECTION is required for PostgreSQL integration tests
```

this is a workstation configuration failure, not dozens of independent application defects. Set the variable, restart Visual Studio, and rerun.

### Integration tests reject the connection

If the message says tests may reset only `mavi_test`, inspect the database component of the connection string. Do not weaken the safeguard and do not point tests at `mavi_dev`.

### FFmpeg/ffprobe tests fail

Confirm both executables are available on `PATH` from the same process environment used by Visual Studio or the test shell.

### Tests pass in CI but fail on Windows

Treat this as a cross-platform defect until proven otherwise. Logical storage keys and HTTP contracts must remain OS- and culture-independent; physical path conversion belongs only inside storage implementations.
