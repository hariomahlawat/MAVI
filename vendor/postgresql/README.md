# Vendored PostgreSQL runtime pack

The repository does not carry ad-hoc PostgreSQL binaries.

For an approved Windows x64 offline release, use tools/native/stage_postgresql_runtime_windows.ps1 against a known-good PostgreSQL 18 installation that already contains the approved pgvector version. Supply the pgvector licence and, when it cannot be discovered automatically, the PostgreSQL licence/copyright file.

The staged pack is written under:

~~~text
vendor/postgresql/pg18/win-x64/
  manifest.json
  LICENSE-POSTGRESQL.txt
  LICENSE-PGVECTOR.txt
  bin/
  lib/
  share/
~~~

The manifest records the exact PostgreSQL version, pgvector version, file sizes and SHA-256 values. The canonical offline setup bundle copies this isolated runtime onto the target machine and registers a MAVI-owned PostgreSQL service, avoiding dependence on arbitrary machine-wide PostgreSQL installations.
