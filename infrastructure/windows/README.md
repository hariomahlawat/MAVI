# Windows Operational Deployment

Target platform role: ASP.NET Core operational platform behind IIS on Windows Server. Detailed service-account, certificate, PostgreSQL placement and backup procedures remain separate from Task-12 vision runtime work.

## Task-12 Windows vision CPU bundle

Where a native Windows vision worker is deployed, the qualified hosted CPU baseline uses:

~~~text
platform variant: windows-x86_64-cpu
Python: CPython 3.12.10
~~~

Provision CPython `3.12.10` before consuming the bundle. Install only from the supplied wheelhouse and lock using the command in `infrastructure/offline-bundle/README.md` / bundle `INSTALL.txt`.

The Task-12 bundle is a `qualification-candidate` until Task 14 completes formal disconnected-install and remaining hardware/quality gates.

Do not infer Windows CUDA qualification from the CPU bundle. `windows-x86_64-cuda` remains pending hardware qualification and requires a separately frozen/qualified CUDA wheel closure.

Model/config/profile/runtime artifacts are consumed from local controlled storage. No package-index, model-hub, online licence or first-run download fallback is permitted.
