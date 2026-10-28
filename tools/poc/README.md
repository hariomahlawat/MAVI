# PoC demo corpus tooling (Development only)

`demo_corpus.py` reproduces the PoC S2 demo state (register rows B1–B5). It uses only the Python standard library and the repository's pinned FFmpeg. It adds no dependency and is not part of the production runtime.

**Single source of truth:** `demo-corpus/demo-corpus-v1.json`. For each of the eight clips it records:
- which acquired Wikimedia Commons original the clip comes from: page revision, provider SHA-1, original SHA-256 and store path;
- the trim window;
- the expected derivative SHA-256;
- the demo camera;
- the Stage-1 scene geometry (zones, restricted zones and directed trip lines in normalised 0..1 coordinates, validated with the server's `SceneRules`).

Selection and rights are documented in `docs/qualification/poc/` (scope declaration, admissibility, attribution).

## Layout outside Git (`--root`)

```
<root>/source-store/      tools/qualification/source_acquisition store: discovery, evidence, receipts, media/commons/... originals
<root>/derivatives/       <clipId>.mp4 trimmed clips (the only media a kit or demo host needs)
<root>/manifests/         originals.sha256, derivatives.sha256 (SHA256SUMS format), derivation-record.json
<root>/approvals/         the purpose-approval documents passed to `acquire`, and their summaries
<root>/owner-machine-only/  platform-licensed demo media (D3); never enters the kit (empty for v1)
```

On the owner laptop, `<root>` is `E:\MAVI-Controlled\PoC\Corpus`.

## Commands

```
python tools/poc/demo_corpus.py validate
python tools/poc/demo_corpus.py trim   --root <root> --ffmpeg <repo>/vendor/ffmpeg/win-x64/ffmpeg.exe
python tools/poc/demo_corpus.py verify --root <root>
python tools/poc/demo_corpus.py import --root <root> --api http://localhost:62153 [--no-process] [--clip <id>]...
```

- **`trim`** first refuses any original whose SHA-256 differs from the definition. It then derives each clip with the pinned argument list `FFMPEG_ARGS`: single-threaded libx264 with bit-exact flags; audio, subtitles, data, metadata and chapters dropped. Each output is checked against the recorded derivative SHA-256, so a rerun with the same FFmpeg binary must reproduce the bytes. The command also writes the manifests and a derivation record holding the FFmpeg SHA-256 and version.
- **`import`** checks every derivative against the definition, then uses only the public HTTP API, clip by clip, in this order:
  1. `POST /api/cameras` creates the camera. An existing camera with the same code is reused only if its name and time zone match.
  2. `POST /api/videos/import` uploads the clip. A `video_duplicate` is reused only if it belongs to the same camera.
  3. `PUT /api/cameras/{id}/scene` saves the scene. This is skipped when the active revision already has identical geometry.
  4. `POST /api/videos/{id}/process` starts processing. The importer then waits until the run is `Completed` and its scene analytics are `Ready`. It requests re-analysis once, with `POST /api/cameras/{id}/scene/analyses` (scope `latestRuns`), in two cases:
     - the analysis is `Stale`;
     - the analysis is still `Pending` 120 s after the importer first saw the run `Completed`. For example, the run finished before its scene existed and outside the reconciler's look-back window.

  Every mutating call is logged with its HTTP status, along with the definition's and the tool's SHA-256. A run that completed with analytics `Disabled` or `NotConfigured` is refused rather than waited on. HTTP proxies are bypassed. A duplicate asset is reused only when its camera and its recording start (from the server's UTC offset) match the definition. Network failures and FFmpeg timeouts end the command with `REFUSED` and exit code 2.

  The import is idempotent, so a second run changes nothing. It never sends credentials: the Development API has no authentication. It refuses any non-loopback API URL.

## What it never does

It creates no label, annotation, count or ground truth (B5). It reads no model output except run status. It writes no media into Git.

## Tests

`tools/poc/tests/test_demo_corpus.py` runs offline: fake FFmpeg runner, fake API. It is run by the Quality Gate's tooling lane.
