# Database

PostgreSQL 18 + pgvector is the approved and implemented initial authoritative datastore for MAVI Phase 1.

EF Core/Npgsql persistence, the initial visual-memory migration, and PostgreSQL-backed integration tests are already part of the platform. Production database migrations remain explicit; the application must not auto-migrate production databases on startup.

Local development uses separate databases:

```text
mavi_dev   application development database
mavi_test  destructive integration-test database
```

Create them with `database/scripts/create-local-databases.sql`. Integration tests deliberately require `MAVI_TEST_DB_CONNECTION` and reject any connection whose database name is not exactly `mavi_test`, because the fixture drops/recreates the public schema and pgvector extension.

See `docs/runbooks/local-development.md` for PostgreSQL/pgvector and Visual Studio Test Explorer setup.
