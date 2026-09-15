# Offline developer dependency cache

Run `tools/setup/Prepare-MaviDeveloperOfflineCache.ps1` on a connected build/preparation machine.

It creates the canonical cache under `vendor/developer-cache/win-x64`:

- `nuget-packages/`
- `npm-cache/`
- `python-wheelhouse/`

The cache is copied into the MAVI offline setup bundle so a fresh Development workstation can restore the repository without Internet access.

Direct .NET/npm/Python dependency changes are tracked by `config/dependencies/offline-dependency-policy-v1.json`. Rebuild this cache after such changes so a fresh disconnected Development workstation receives the updated dependency closure.
