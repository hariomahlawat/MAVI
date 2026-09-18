# Database

PostgreSQL 18 + pgvector is the approved and implemented authoritative datastore for MAVI Phase 1.

## Supported Development topology

`Setup-MAVI-Development.cmd` owns the local database environment:

```text
service: MAVI-Dev-PostgreSQL-18
host:    127.0.0.1
port:    55433
db:      mavi_dev
test db: mavi_test
```

Setup creates both databases, enables pgvector and configures the machine-scoped integration-test connection. Do not manually create databases or repoint normal Development/test execution to an arbitrary PostgreSQL instance.

The integration fixture is deliberately destructive and refuses any database whose name is not exactly `mavi_test`.

## Production topology

`Setup-MAVI-Production.cmd` provisions a dedicated MAVI-owned PostgreSQL 18 service on port 55432 from the approved hash-manifested runtime pack containing pgvector. Production credentials are generated/protected by Setup rather than committed to the repository.

MAVI applies pending EF Core migrations automatically during startup in Development and Production. Startup is fail-closed: PostgreSQL/pgvector prerequisites are verified under the migration advisory lock, migrations are applied, and MAVI does not begin serving against an unverified schema state.

Do not use `EnsureCreated`, manually edit `__EFMigrationsHistory`, or make manual SQL migration steps part of the normal deployment workflow.

See:

- `docs/runbooks/local-development.md`
- `docs/runbooks/mavi-offline-setup.md`
- `docs/architecture/dependency-and-offline-packaging-policy.md`
