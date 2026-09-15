# Development Environment

The supported Windows Development workflow is:

```text
Setup-MAVI-Development.cmd
→ approve elevation
→ restart Visual Studio once
→ F5
```

Development may use Internet-connected preparation tooling, but a prepared repository/offline bundle must be able to establish the supported environment without package registries or manual PostgreSQL/pgvector/FFmpeg configuration.

Setup owns the MAVI Development PostgreSQL 18 instance, pgvector, databases, machine configuration, test connection, SDK checks/installers and offline NuGet/npm/Python caches.

Any future dependency must follow `docs/architecture/dependency-and-offline-packaging-policy.md` and update the machine-readable policy at `config/dependencies/offline-dependency-policy-v1.json`.
