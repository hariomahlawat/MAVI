# Offline developer dependency cache

Run `tools/setup/Prepare-MaviDeveloperOfflineCache.ps1` on a connected build/preparation machine.

It recreates the canonical cache under `vendor/developer-cache/win-x64`:

- `nuget-packages/`
- `npm-cache/`
- `python-wheelhouse/`
- `developer-cache-manifest.json`

The generated manifest records the repository input hashes plus an exact, human-readable inventory of:

- NuGet package IDs and versions restored for the solution;
- npm package paths and exact versions from `package-lock.json`; and
- Python wheel/artifact filenames, sizes and SHA-256 values.

The complete cache is then copied into the separately retained MAVI Offline Binary Kit. The binary-kit manifest hashes the cache manifest and every cache byte, so both readable version inventory and cryptographic identity are retained.

Direct .NET/npm/Python dependency changes are tracked by `config/dependencies/offline-dependency-policy-v1.json`. Rebuild this cache and then rebuild the binary kit after such changes so a fresh disconnected Development workstation receives the matching dependency closure.
