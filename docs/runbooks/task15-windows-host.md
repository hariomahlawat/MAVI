# Task 15 Windows Web/API Host Qualification

Task 15 standardizes the Phase-1 operator UI and API as one ASP.NET Core application behind IIS/ANCM. The published React assets are served by `Mavi.Api`; `/api` and `/health` remain API routes and only non-file frontend routes fall back to the React entry document.

Normal Windows deployment is now performed through the canonical offline `Setup-MAVI-Production.cmd` workflow described in `docs/runbooks/mavi-offline-setup.md`. This Task-15 script is a **host qualification check after deployment**, not an alternative installation procedure.

The supported single-request MP4 import ceiling is **3 GiB**, with 1 MiB reserved for multipart overhead. IIS `maxAllowedContentLength`, Kestrel, ASP.NET Core form limits and the application option must remain aligned.

After publishing/deploying to a Windows qualification host, use a valid MP4 larger than 30 MiB and run:

~~~powershell
.\tools\task15\qualify_windows_host.ps1 `
  -BaseUrl "https://mavi-host" `
  -CameraId "<existing-active-camera-guid>" `
  -RecordingStartLocal "2026-09-14T08:30:00" `
  -VideoPath "C:\qualification\task15-over-30mb.mp4" `
  -WebConfigPath "C:\inetpub\mavi\web.config"
~~~

The qualification verifies same-origin API reachability, API-safe SPA fallback, processing deep-link delivery, IIS request-limit configuration, and that a representative multipart request above IIS's default ~30 MB limit reaches MAVI rather than being rejected by the web server.

A `201 Created` import passes. A `409 video_duplicate` also passes only when the response contains the authoritative existing `videoAssetId`, because that is the Task-15 lost-success reconciliation contract. HTTP 413 or 404 is a qualification failure.
