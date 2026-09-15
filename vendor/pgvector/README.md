# pgvector offline prerequisite pack

pgvector is a PostgreSQL server extension, not an application-local executable. MAVI startup verifies that the approved extension is installed for PostgreSQL 18 and safely enables it in the selected database, but normal application startup does not modify the PostgreSQL installation directory.

Prepare an offline prerequisite pack with this layout:

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

The manifest must contain `schemaVersion`, `postgresqlMajorVersion`, `pgvectorVersion`, `runtimeId`, and an `artifacts` array of `relativePath` plus lowercase SHA-256 values.

Install it once, with administrative rights, using `tools/native/install_pgvector_windows.ps1`. The bootstrapper validates every payload SHA-256 before copying files into the PostgreSQL installation.

After bootstrap, normal MAVI startup verifies PostgreSQL major version 18, checks `pg_available_extensions`, executes `CREATE EXTENSION IF NOT EXISTS vector` under the MAVI migration lock, and only then applies EF Core migrations.
