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


## Task-15 web/API co-host qualification

Task 15 standardizes the Phase-1 operator UI and API as one ASP.NET Core application behind IIS/ANCM. The published React assets are served by `Mavi.Api`; `/api` and `/health` remain API routes and only non-file frontend routes fall back to the React entry document.

The supported single-request MP4 import ceiling is **3 GiB**, with 1 MiB reserved for multipart overhead. IIS `maxAllowedContentLength`, Kestrel, ASP.NET Core form limits and the application option must remain aligned.

After publishing/deploying to a Windows qualification host, use a valid MP4 larger than 30 MiB and run:

~~~powershell
.\infrastructure\windows\qualify-task15-host.ps1 `
  -BaseUrl "https://mavi-host" `
  -CameraId "<existing-active-camera-guid>" `
  -RecordingStartLocal "2026-09-14T08:30:00" `
  -VideoPath "C:\qualification\task15-over-30mb.mp4" `
  -WebConfigPath "C:\inetpub\mavi\web.config"
~~~

The qualification verifies same-origin API reachability, API-safe SPA fallback, processing deep-link delivery, IIS request-limit configuration, and that a representative multipart request above IIS's default ~30 MB limit reaches MAVI rather than being rejected by the web server.
