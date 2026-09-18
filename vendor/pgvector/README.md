# pgvector maintenance pack

pgvector is a PostgreSQL server extension, not an application-local executable.

## Normal MAVI installation

Normal Development and Production setup does **not** require a separate pgvector install. The approved pgvector files are integrated into the MAVI-owned PostgreSQL 18 runtime pack under `vendor/postgresql/pg18/win-x64`, then carried in the canonical offline setup media.

`Setup-MAVI-Development.cmd` / `Setup-MAVI-Production.cmd` deploy that isolated PostgreSQL runtime. Application startup independently verifies PostgreSQL 18, confirms pgvector availability, enables `vector` in the selected database under the migration lock when required, and then applies EF Core migrations.

## Lower-level maintenance use only

The standalone pgvector staging/install tooling remains available for controlled build-machine or maintenance scenarios where an already-installed PostgreSQL 18 tree must be prepared before the complete MAVI runtime pack is staged.

Its package layout is:

```text
vendor/pgvector/pg18/win-x64/
  manifest.json
  lib/
    vector.dll
  share/
    extension/
      vector.control
      vector--*.sql
```

The manifest records the PostgreSQL major version, pgvector version, runtime ID and SHA-256 identities. `tools/native/install_pgvector_windows.ps1` validates the payload before copying it.

Do not turn this lower-level maintenance path back into a normal end-user prerequisite. Future database/native dependencies must follow `docs/architecture/dependency-and-offline-packaging-policy.md` and be integrated into the canonical Setup/runtime-pack methodology.
