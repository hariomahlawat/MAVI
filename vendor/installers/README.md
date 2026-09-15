# Offline installer staging

Place the approved Windows x64 installers here using the canonical names below:

- `dotnet-hosting.exe` — ASP.NET Core Hosting Bundle for the MAVI .NET baseline.
- `dotnet-sdk.exe` — .NET 10 SDK used by Development workstations.
- `node.msi` — approved Node.js 22.13+ x64 MSI.
- `python.exe` — approved Python 3.13 x64 installer.

These files are release inputs. The normal source repository should not carry large third-party installers in ordinary Git history. The release-media builder copies them into the SHA-256-manifested MAVI offline setup bundle.

If the organisation later chooses Git LFS or a dedicated binary repository, keep these same canonical paths so the setup tooling does not change.
