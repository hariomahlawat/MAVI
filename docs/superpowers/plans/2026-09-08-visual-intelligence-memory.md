# MAVI Phase 1 — Searchable Visual Intelligence Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first operational MAVI vertical slice: managed MP4 import, person/vehicle detection and single-camera tracking, durable visual-intelligence memory, structured track search, and evidence-linked video playback.

**Architecture:** Keep the existing ASP.NET Core modular platform as the operational authority, PostgreSQL as the authoritative intelligence datastore, React as the operator UI, and Python as an independently deployable vision worker. The worker receives logical media storage keys, produces analytical results/artifacts, and never writes PostgreSQL; .NET validates and atomically persists accepted intelligence.

**Tech Stack:** .NET 10 / ASP.NET Core, EF Core 10.0.11, Npgsql EF Core 10.0.3, PostgreSQL 18, pgvector EF 0.3.0, React 19 + TypeScript + Vite, TanStack Query, Python 3.12, PyAV/FFmpeg, PyTorch/MMDetection RTMDet adapter, ByteTrack, MessagePack, Pydantic/httpx/pytest.

**Spec:** `docs/superpowers/specs/2026-09-08-visual-intelligence-memory-design.md`

## Global Constraints

- Implement on a dedicated branch named `feature/visual-intelligence-memory` from the clean MAVI bootstrap baseline.
- Production runtime must not depend on Internet-hosted APIs, CDNs, fonts, model downloads, authentication or telemetry.
- `Mavi.Domain` must not reference Application, Infrastructure, Api, React, Python, EF Core or PostgreSQL packages.
- Python must not write operational PostgreSQL records.
- React must not access PostgreSQL or filesystem paths directly.
- Subsystem contracts use logical storage keys; never pass `D:\...` or `/mnt/...` absolute paths over HTTP.
- Every accepted Track must resolve to VideoAsset, Camera, ProcessingRun, source video and model/pipeline version.
- Use UUID v7 for new durable IDs.
- Store durable real-world timestamps as UTC; store video-relative offsets as integer milliseconds.
- Track is the primary searchable unit; do not store one relational detection row per processed frame.
- Phase 1 supports recorded MP4 only; no RTSP, VMS, face recognition, ReID, ANPR, cross-camera association, mission rules or LLM/VLM reasoning.
- PostgreSQL migrations are explicit; do not auto-migrate production databases on application startup.
- Tests are written before production changes for every behavioural change.
- Keep `TreatWarningsAsErrors=true`; fix analyzer issues rather than disabling repository-wide analysis.
- Every task ends with a build/test verification and a focused Git commit.

---

# File Structure Map

The plan creates/modifies the following primary units.

```text
src/platform/Mavi.Domain/
  Common/DomainValidationException.cs
  Cameras/Camera.cs
  Media/Artifact.cs
  Media/ArtifactType.cs
  Media/TimestampSource.cs
  Media/VideoAsset.cs
  Media/VideoProcessingStatus.cs
  Media/VideoSourceType.cs
  Processing/ProcessingRun.cs
  Processing/ProcessingRunStatus.cs
  Processing/VisionJob.cs
  Processing/VisionJobStatus.cs
  Intelligence/Entity.cs
  Intelligence/EntityType.cs
  Intelligence/IdentityStatus.cs
  Intelligence/ObjectClass.cs
  Intelligence/Observation.cs
  Intelligence/ObservationType.cs
  Intelligence/ReviewStatus.cs
  Intelligence/Track.cs
  Intelligence/VisualAttribute.cs

src/platform/Mavi.Application/
  Abstractions/Clock/IClock.cs
  Abstractions/Storage/IMediaStore.cs
  Modules/Cameras/ICameraRepository.cs
  Modules/Cameras/CameraService.cs
  Modules/Media/IVideoCatalog.cs
  Modules/Media/IVideoMetadataReader.cs
  Modules/Media/VideoMetadata.cs
  Modules/Media/VideoImportService.cs
  Modules/Processing/IProcessingRepository.cs
  Modules/Processing/ProcessingService.cs
  Modules/Processing/VisionJobLeaseService.cs
  Modules/Intelligence/VisionResultValidator.cs
  Modules/Intelligence/IProcessingResultStore.cs
  Modules/Intelligence/VisionResultIngestService.cs
  Modules/Intelligence/ITrackSearchRepository.cs
  Modules/Intelligence/TrackSearchService.cs

src/platform/Mavi.Contracts/
  Api/Cameras/*.cs
  Api/Videos/*.cs
  Api/Tracks/*.cs
  Worker/VisionJobContracts.cs
  Worker/VisionResultContracts.cs

src/platform/Mavi.Infrastructure/
  Persistence/MaviDbContext.cs
  Persistence/Configurations/*.cs
  Persistence/Repositories/*.cs
  Persistence/Migrations/*
  Storage/LocalMediaStore.cs
  Media/FfprobeVideoMetadataReader.cs
  Time/SystemClock.cs
  DependencyInjection.cs

src/platform/Mavi.Api/
  Endpoints/CameraEndpoints.cs
  Endpoints/VideoEndpoints.cs
  Endpoints/VisionJobEndpoints.cs
  Endpoints/TrackEndpoints.cs
  Endpoints/ArtifactEndpoints.cs
  Program.cs
  appsettings.json

src/vision/
  pyproject.toml
  mavi_vision/common/settings.py
  mavi_vision/common/contracts.py
  mavi_vision/storage/local_media_store.py
  mavi_vision/worker/client.py
  mavi_vision/worker/main.py
  mavi_vision/video/reader.py
  mavi_vision/video/trajectory.py
  mavi_vision/detection/fixture.py
  mavi_vision/detection/rtmdet.py
  mavi_vision/tracking/bytetrack.py
  mavi_vision/quality/scoring.py
  mavi_vision/pipeline/process_video.py
  tests/*.py

src/web/mavi-web/src/
  api/client.ts
  api/cameras.ts
  api/videos.ts
  api/tracks.ts
  app/router.tsx
  features/cameras/CamerasPage.tsx
  features/video-import/VideoImportPage.tsx
  features/processing/ProcessingPage.tsx
  features/visual-search/VisualSearchPage.tsx
  features/video-review/VideoReviewPage.tsx

contracts/
  schemas/vision-job.schema.json
  schemas/vision-result.schema.json
  examples/vision-job.example.json
  examples/vision-result.example.json

models/manifests/rtmdet-phase1.json
sample-data/ground-truth/phase1-example.json
```

---

## Task 1: Add Phase-1 Media Domain Types

**Files:**
- Create: `src/platform/Mavi.Domain/Common/DomainValidationException.cs`
- Create: `src/platform/Mavi.Domain/Cameras/Camera.cs`
- Create: `src/platform/Mavi.Domain/Media/Artifact.cs`
- Create: `src/platform/Mavi.Domain/Media/ArtifactType.cs`
- Create: `src/platform/Mavi.Domain/Media/TimestampSource.cs`
- Create: `src/platform/Mavi.Domain/Media/VideoAsset.cs`
- Create: `src/platform/Mavi.Domain/Media/VideoProcessingStatus.cs`
- Create: `src/platform/Mavi.Domain/Media/VideoSourceType.cs`
- Create: `tests/Mavi.Domain.Tests/CameraTests.cs`
- Create: `tests/Mavi.Domain.Tests/VideoAssetTests.cs`

**Interfaces:**
- Produces: `Camera`, `Artifact`, `VideoAsset` domain types and enum values used by persistence/import tasks.
- IDs are `Guid`; constructors generate UUIDv7 unless an explicit ID is supplied by persistence materialization.

- [ ] **Step 1: Write failing Camera tests**

```csharp
using Mavi.Domain.Cameras;
using Mavi.Domain.Common;

namespace Mavi.Domain.Tests;

public sealed class CameraTests
{
    [Fact]
    public void CreateProducesUuidV7AndNormalizedCode()
    {
        var camera = Camera.Create(" cam-0001 ", "Main Gate", "Asia/Kolkata");

        Assert.Equal(7, camera.Id.Version);
        Assert.Equal("CAM-0001", camera.Code);
        Assert.Equal("Main Gate", camera.Name);
        Assert.True(camera.IsActive);
    }

    [Fact]
    public void CreateRejectsBlankCode()
    {
        var ex = Assert.Throws<DomainValidationException>(
            () => Camera.Create(" ", "Main Gate", "Asia/Kolkata"));

        Assert.Equal("camera_code_required", ex.Code);
    }
}
```

- [ ] **Step 2: Run the Camera tests and verify RED**

Run:

```powershell
dotnet test tests/Mavi.Domain.Tests/Mavi.Domain.Tests.csproj --filter CameraTests
```

Expected: compile/test failure because `Camera` and `DomainValidationException` do not exist.

- [ ] **Step 3: Implement the minimal validation exception and Camera**

Required public API:

```csharp
namespace Mavi.Domain.Common;

public sealed class DomainValidationException(string code, string message) : Exception(message)
{
    public string Code { get; } = code;
}
```

```csharp
namespace Mavi.Domain.Cameras;

public sealed class Camera
{
    private Camera() { }

    public Guid Id { get; private set; }
    public string Code { get; private set; } = string.Empty;
    public string Name { get; private set; } = string.Empty;
    public string? Description { get; private set; }
    public string? LocationName { get; private set; }
    public string TimeZoneId { get; private set; } = string.Empty;
    public bool IsActive { get; private set; }
    public DateTimeOffset CreatedAtUtc { get; private set; }
    public DateTimeOffset UpdatedAtUtc { get; private set; }

    public static Camera Create(string code, string name, string timeZoneId)
    {
        // validate blank/max-length values exactly as the spec states;
        // normalize Code with Trim().ToUpperInvariant();
        // validate TimeZoneInfo.FindSystemTimeZoneById(timeZoneId);
        // set Guid.CreateVersion7(), UTC timestamps and IsActive=true.
    }
}
```

- [ ] **Step 4: Write failing VideoAsset invariant tests**

```csharp
using Mavi.Domain.Media;

namespace Mavi.Domain.Tests;

public sealed class VideoAssetTests
{
    [Fact]
    public void CreateDerivesRecordingEndFromDuration()
    {
        var start = new DateTimeOffset(2026, 9, 8, 8, 30, 0, TimeSpan.Zero);
        var asset = VideoAsset.Create(
            Guid.CreateVersion7(),
            Guid.CreateVersion7(),
            "gate01.mp4",
            start,
            90_000,
            25,
            1,
            1920,
            1080,
            "h264",
            TimestampSource.Manual,
            1.0);

        Assert.Equal(start.AddMilliseconds(90_000), asset.RecordingEndUtc);
        Assert.Equal(VideoProcessingStatus.NotQueued, asset.ProcessingStatus);
    }

    [Fact]
    public void CreateRejectsZeroDuration()
    {
        Assert.ThrowsAny<Exception>(() => VideoAsset.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), "bad.mp4",
            DateTimeOffset.UtcNow, 0, 25, 1, 1920, 1080, "h264",
            TimestampSource.Manual, 1.0));
    }
}
```

- [ ] **Step 5: Run VideoAsset tests and verify RED**

```powershell
dotnet test tests/Mavi.Domain.Tests/Mavi.Domain.Tests.csproj --filter VideoAssetTests
```

Expected: failure because Phase-1 media types do not exist.

- [ ] **Step 6: Implement Artifact and VideoAsset**

Implement the exact fields and enum values from the spec. Required factories:

```csharp
public static Artifact Create(
    ArtifactType artifactType,
    string storageKey,
    string mimeType,
    long sizeBytes,
    string sha256,
    string? metadataJson = null);
```

```csharp
public static VideoAsset Create(
    Guid cameraId,
    Guid sourceArtifactId,
    string originalFileName,
    DateTimeOffset recordingStartUtc,
    long durationMs,
    int frameRateNumerator,
    int frameRateDenominator,
    int width,
    int height,
    string? codec,
    TimestampSource timestampSource,
    double timestampConfidence);
```

`Artifact.Create` must reject absolute/parent-traversal storage keys. Accept only relative slash-separated keys with no `..`, drive separator, leading slash or backslash.

- [ ] **Step 7: Run Domain tests**

```powershell
dotnet test tests/Mavi.Domain.Tests/Mavi.Domain.Tests.csproj
```

Expected: all existing and new Domain tests pass.

- [ ] **Step 8: Commit**

```powershell
git add src/platform/Mavi.Domain tests/Mavi.Domain.Tests
git commit -m "feat: add phase1 media domain model"
```

---

## Task 2: Add Processing and Intelligence Domain Types

**Files:**
- Create: `src/platform/Mavi.Domain/Processing/ProcessingRun.cs`
- Create: `src/platform/Mavi.Domain/Processing/ProcessingRunStatus.cs`
- Create: `src/platform/Mavi.Domain/Processing/VisionJob.cs`
- Create: `src/platform/Mavi.Domain/Processing/VisionJobStatus.cs`
- Create: `src/platform/Mavi.Domain/Intelligence/Entity.cs`
- Create: `src/platform/Mavi.Domain/Intelligence/EntityType.cs`
- Create: `src/platform/Mavi.Domain/Intelligence/IdentityStatus.cs`
- Create: `src/platform/Mavi.Domain/Intelligence/ObjectClass.cs`
- Create: `src/platform/Mavi.Domain/Intelligence/Observation.cs`
- Create: `src/platform/Mavi.Domain/Intelligence/ObservationType.cs`
- Create: `src/platform/Mavi.Domain/Intelligence/ReviewStatus.cs`
- Create: `src/platform/Mavi.Domain/Intelligence/Track.cs`
- Create: `src/platform/Mavi.Domain/Intelligence/VisualAttribute.cs`
- Create: `tests/Mavi.Domain.Tests/ProcessingStateTests.cs`
- Create: `tests/Mavi.Domain.Tests/TrackTests.cs`

**Interfaces:**
- Consumes: media domain types from Task 1.
- Produces: processing state machines and Track/Observation models used by job/persistence tasks.

- [ ] **Step 1: Write failing processing state tests**

```csharp
using Mavi.Domain.Processing;

namespace Mavi.Domain.Tests;

public sealed class ProcessingStateTests
{
    [Fact]
    public void LeaseTransitionsQueuedJobToLeased()
    {
        var now = new DateTimeOffset(2026, 9, 8, 9, 0, 0, TimeSpan.Zero);
        var job = VisionJob.Create(Guid.CreateVersion7(), "phase1-detection-tracking", now);

        job.Lease("worker-01", now, TimeSpan.FromSeconds(120));

        Assert.Equal(VisionJobStatus.Leased, job.Status);
        Assert.Equal("worker-01", job.LeaseOwner);
        Assert.Equal(1, job.AttemptCount);
        Assert.Equal(now.AddSeconds(120), job.LeaseExpiresAtUtc);
    }

    [Fact]
    public void CompleteRejectsWrongLeaseOwner()
    {
        var now = DateTimeOffset.UtcNow;
        var job = VisionJob.Create(Guid.CreateVersion7(), "phase1-detection-tracking", now);
        job.Lease("worker-01", now, TimeSpan.FromSeconds(120));

        Assert.ThrowsAny<Exception>(() => job.Complete("worker-02", now.AddSeconds(10)));
    }
}
```

- [ ] **Step 2: Run and verify RED**

```powershell
dotnet test tests/Mavi.Domain.Tests/Mavi.Domain.Tests.csproj --filter ProcessingStateTests
```

- [ ] **Step 3: Implement ProcessingRun/VisionJob state machines**

Required methods:

```csharp
ProcessingRun.Create(Guid videoAssetId, string pipelineVersion, string configurationJson, DateTimeOffset nowUtc)
ProcessingRun.MarkRunning(string workerId, DateTimeOffset startedAtUtc)
ProcessingRun.MarkCompleted(long framesProcessed, int tracksCreated, long durationMs, DateTimeOffset completedAtUtc)
ProcessingRun.MarkFailed(string errorCode, string details, DateTimeOffset failedAtUtc)
```

```csharp
VisionJob.Create(Guid processingRunId, string pipeline, DateTimeOffset nowUtc)
VisionJob.CanLease(DateTimeOffset nowUtc)
VisionJob.Lease(string workerId, DateTimeOffset nowUtc, TimeSpan duration)
VisionJob.Heartbeat(string workerId, double progressPercent, DateTimeOffset nowUtc, TimeSpan extension)
VisionJob.Complete(string workerId, DateTimeOffset nowUtc)
VisionJob.Fail(string workerId, string code, string details, DateTimeOffset nowUtc)
```

Enforce the three-attempt rule and all state-transition invariants from the spec.

- [ ] **Step 4: Write failing Track tests**

```csharp
using Mavi.Domain.Intelligence;

namespace Mavi.Domain.Tests;

public sealed class TrackTests
{
    [Fact]
    public void CreateDerivesDurationAndUtcTimestamps()
    {
        var recordingStart = new DateTimeOffset(2026, 9, 8, 10, 0, 0, TimeSpan.Zero);
        var track = Track.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), 17, ObjectClass.Person,
            4_120, 21_880, recordingStart, 280, 0.88, 0.96);

        Assert.Equal(17_760, track.DurationMs);
        Assert.Equal(recordingStart.AddMilliseconds(4_120), track.StartTimestampUtc);
        Assert.Equal(recordingStart.AddMilliseconds(21_880), track.EndTimestampUtc);
        Assert.Null(track.EntityId);
    }

    [Fact]
    public void CreateRejectsEndBeforeStart()
    {
        Assert.ThrowsAny<Exception>(() => Track.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), 1, ObjectClass.Vehicle,
            10_000, 9_000, DateTimeOffset.UtcNow, 5, 0.8, 0.9));
    }
}
```

- [ ] **Step 5: Implement Track, Observation, VisualAttribute and dormant Entity**

Use exact spec fields. `Track.Create` signature:

```csharp
public static Track Create(
    Guid processingRunId,
    Guid videoAssetId,
    int localTrackNumber,
    ObjectClass objectClass,
    long startOffsetMs,
    long endOffsetMs,
    DateTimeOffset recordingStartUtc,
    int detectionCount,
    double meanConfidence,
    double maxConfidence);
```

`Observation.Create` must validate finite normalized boxes and confidence/quality ranges.

- [ ] **Step 6: Run full Domain tests**

```powershell
dotnet test tests/Mavi.Domain.Tests/Mavi.Domain.Tests.csproj
```

- [ ] **Step 7: Commit**

```powershell
git add src/platform/Mavi.Domain tests/Mavi.Domain.Tests
git commit -m "feat: add processing and track domain model"
```

---

## Task 3: Add EF Core/PostgreSQL Persistence and Initial Migration

**Files:**
- Modify: `src/platform/Mavi.Infrastructure/Mavi.Infrastructure.csproj`
- Create: `src/platform/Mavi.Infrastructure/Persistence/MaviDbContext.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Configurations/CameraConfiguration.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Configurations/ArtifactConfiguration.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Configurations/VideoAssetConfiguration.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Configurations/ProcessingRunConfiguration.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Configurations/VisionJobConfiguration.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Configurations/TrackConfiguration.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Configurations/ObservationConfiguration.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Configurations/VisualAttributeConfiguration.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Configurations/EntityConfiguration.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Migrations/*`
- Modify: `src/platform/Mavi.Infrastructure/DependencyInjection.cs`
- Modify: `src/platform/Mavi.Api/appsettings.json`
- Modify: `tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj`
- Create: `tests/Mavi.IntegrationTests/PostgresFixture.cs`
- Create: `tests/Mavi.IntegrationTests/MigrationTests.cs`
- Create: `database/scripts/create-local-databases.sql`

**Interfaces:**
- Consumes: all Domain types.
- Produces: `MaviDbContext` and schema used by repositories.

- [ ] **Step 1: Add pinned persistence packages**

Update `Mavi.Infrastructure.csproj` package references to include:

```xml
<PackageReference Include="Microsoft.EntityFrameworkCore" Version="10.0.11" />
<PackageReference Include="Microsoft.EntityFrameworkCore.Design" Version="10.0.11">
  <PrivateAssets>all</PrivateAssets>
  <IncludeAssets>runtime; build; native; contentfiles; analyzers; buildtransitive</IncludeAssets>
</PackageReference>
<PackageReference Include="Microsoft.Extensions.Configuration.Abstractions" Version="10.0.11" />
<PackageReference Include="Npgsql.EntityFrameworkCore.PostgreSQL" Version="10.0.3" />
<PackageReference Include="Pgvector.EntityFrameworkCore" Version="0.3.0" />
```

Add to integration tests:

```xml
<PackageReference Include="Microsoft.AspNetCore.Mvc.Testing" Version="10.0.11" />
<PackageReference Include="Npgsql" Version="10.0.3" />
```

- [ ] **Step 2: Create local database script**

`database/scripts/create-local-databases.sql`:

```sql
CREATE DATABASE mavi_dev;
CREATE DATABASE mavi_test;
```

Developer executes the two `CREATE DATABASE` statements individually if the PostgreSQL client disallows multi-database creation in one transaction.

Verify:

```powershell
psql --version
```

Expected: PostgreSQL 18.x client.

Set environment variables before running API/tests:

```powershell
$env:ConnectionStrings__Mavi = "Host=localhost;Port=5432;Database=mavi_dev;Username=postgres;Password=$env:MAVI_LOCAL_POSTGRES_PASSWORD"
$env:MAVI_TEST_DB_CONNECTION = "Host=localhost;Port=5432;Database=mavi_test;Username=postgres;Password=$env:MAVI_LOCAL_POSTGRES_PASSWORD"
```

- [ ] **Step 3: Write failing migration integration test**

```csharp
using Microsoft.EntityFrameworkCore;
using Npgsql;
using Mavi.Infrastructure.Persistence;

namespace Mavi.IntegrationTests;

public sealed class MigrationTests(PostgresFixture fixture) : IClassFixture<PostgresFixture>
{
    [Fact]
    public async Task InitialMigrationCreatesVectorExtensionAndCoreTables()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();

        await using var conn = new NpgsqlConnection(fixture.ConnectionString);
        await conn.OpenAsync();

        await using var cmd = new NpgsqlCommand(
            "SELECT extname FROM pg_extension WHERE extname='vector';", conn);
        Assert.Equal("vector", await cmd.ExecuteScalarAsync());

        Assert.True(await TableExists(conn, "cameras"));
        Assert.True(await TableExists(conn, "video_assets"));
        Assert.True(await TableExists(conn, "tracks"));
    }
}
```

`PostgresFixture.ResetDatabaseAsync()` shall operate on **mavi_test only** and never use the dev connection string. Reset in this order so the pgvector extension can be recreated by the migration:

```sql
DROP EXTENSION IF EXISTS vector CASCADE;
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
```

- [ ] **Step 4: Run migration test and verify RED**

```powershell
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter MigrationTests
```

Expected: failure because DbContext/migration does not exist.

- [ ] **Step 5: Implement MaviDbContext and configurations**

Required DbSets:

```csharp
public DbSet<Camera> Cameras => Set<Camera>();
public DbSet<Artifact> Artifacts => Set<Artifact>();
public DbSet<VideoAsset> VideoAssets => Set<VideoAsset>();
public DbSet<ProcessingRun> ProcessingRuns => Set<ProcessingRun>();
public DbSet<VisionJob> VisionJobs => Set<VisionJob>();
public DbSet<Track> Tracks => Set<Track>();
public DbSet<Observation> Observations => Set<Observation>();
public DbSet<VisualAttribute> VisualAttributes => Set<VisualAttribute>();
public DbSet<Entity> Entities => Set<Entity>();
```

`OnModelCreating`:

```csharp
modelBuilder.HasPostgresExtension("vector");
modelBuilder.ApplyConfigurationsFromAssembly(typeof(MaviDbContext).Assembly);
```

Use snake_case table/column names explicitly in configuration; do not add a naming-convention package. Persist all domain enums with explicit string conversion (`HasConversion<string>()`) and bounded varchar lengths; raw lease queries therefore compare status values such as `Queued` and `Leased`, never numeric ordinals.

- [ ] **Step 6: Register DbContext**

`DependencyInjection.AddMaviInfrastructure` obtains `ConnectionStrings:Mavi` and registers:

```csharp
services.AddDbContext<MaviDbContext>(options =>
    options.UseNpgsql(connectionString, npgsql => npgsql.UseVector()));
```

Change the method signature to accept `IConfiguration`:

```csharp
public static IServiceCollection AddMaviInfrastructure(
    this IServiceCollection services,
    IConfiguration configuration)
```

Update `Program.cs` call accordingly in this task if required for compilation.

- [ ] **Step 7: Generate initial migration**

From repository root:

```powershell
dotnet ef migrations add InitialVisualMemory `
  --project src/platform/Mavi.Infrastructure/Mavi.Infrastructure.csproj `
  --startup-project src/platform/Mavi.Api/Mavi.Api.csproj `
  --output-dir Persistence/Migrations
```

Inspect generated migration and ensure it includes the vector extension plus all nine Phase-1 tables.

- [ ] **Step 8: Apply dev migration and run integration test**

```powershell
dotnet ef database update `
  --project src/platform/Mavi.Infrastructure/Mavi.Infrastructure.csproj `
  --startup-project src/platform/Mavi.Api/Mavi.Api.csproj

dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter MigrationTests
```

Expected: PASS.

- [ ] **Step 9: Run full .NET build/tests**

```powershell
dotnet build MAVI.sln
dotnet test MAVI.sln
```

- [ ] **Step 10: Commit**

```powershell
git add src/platform/Mavi.Infrastructure src/platform/Mavi.Api tests/Mavi.IntegrationTests database
git commit -m "feat: add postgres visual memory persistence"
```

---

## Task 4: Implement Camera Repository, Service and API

**Files:**
- Create: `src/platform/Mavi.Application/Modules/Cameras/ICameraRepository.cs`
- Create: `src/platform/Mavi.Application/Modules/Cameras/CameraService.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Repositories/CameraRepository.cs`
- Create: `src/platform/Mavi.Contracts/Api/Cameras/CreateCameraRequest.cs`
- Create: `src/platform/Mavi.Contracts/Api/Cameras/CameraResponse.cs`
- Create: `src/platform/Mavi.Api/Endpoints/CameraEndpoints.cs`
- Modify: `src/platform/Mavi.Infrastructure/DependencyInjection.cs`
- Modify: `src/platform/Mavi.Api/Program.cs`
- Create: `tests/Mavi.Application.Tests/CameraServiceTests.cs`
- Create: `tests/Mavi.IntegrationTests/CameraApiTests.cs`

**Interfaces:**

```csharp
public interface ICameraRepository
{
    Task<bool> CodeExistsAsync(string code, CancellationToken cancellationToken);
    Task AddAsync(Camera camera, CancellationToken cancellationToken);
    Task<Camera?> GetAsync(Guid id, CancellationToken cancellationToken);
    Task<IReadOnlyList<Camera>> ListAsync(CancellationToken cancellationToken);
    Task SaveChangesAsync(CancellationToken cancellationToken);
}
```

- [ ] **Step 1: Write failing CameraService unit test**

```csharp
[Fact]
public async Task CreateRejectsDuplicateCameraCode()
{
    var repo = new FakeCameraRepository { ExistingCode = "CAM-0001" };
    var service = new CameraService(repo);

    var result = await service.CreateAsync(
        new CreateCameraCommand("CAM-0001", "Main Gate", "Asia/Kolkata"),
        CancellationToken.None);

    Assert.False(result.IsSuccess);
    Assert.Equal("camera_code_duplicate", result.ErrorCode);
}
```

- [ ] **Step 2: Implement minimal service/repository contracts until unit test passes**

`CameraService.CreateAsync` normalizes/validates through `Camera.Create`, checks duplicate code, saves and returns the created camera DTO/ID.

- [ ] **Step 3: Write failing API integration test**

```csharp
[Fact]
public async Task PostAndGetCameraRoundTrip()
{
    using var client = fixture.CreateClient();

    var post = await client.PostAsJsonAsync("/api/cameras", new
    {
        code = "CAM-0001",
        name = "Main Gate",
        timeZoneId = "Asia/Kolkata"
    });
    post.EnsureSuccessStatusCode();

    var created = await post.Content.ReadFromJsonAsync<CameraResponse>();
    var get = await client.GetAsync($"/api/cameras/{created!.Id}");
    get.EnsureSuccessStatusCode();
}
```

- [ ] **Step 4: Implement minimal API routes**

```http
POST /api/cameras
GET  /api/cameras
GET  /api/cameras/{id}
```

Use `ProblemDetails` with `camera_code_duplicate`, `camera_not_found` and validation codes.

- [ ] **Step 5: Run tests/build**

```powershell
dotnet test tests/Mavi.Application.Tests/Mavi.Application.Tests.csproj --filter CameraServiceTests
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter CameraApiTests
dotnet build MAVI.sln
```

- [ ] **Step 6: Commit**

```powershell
git add src/platform tests
git commit -m "feat: add camera management api"
```

---

## Task 5: Add Managed Media Store and ffprobe Metadata Reader

**Files:**
- Create: `src/platform/Mavi.Application/Abstractions/Storage/IMediaStore.cs`
- Create: `src/platform/Mavi.Application/Modules/Media/IVideoMetadataReader.cs`
- Create: `src/platform/Mavi.Application/Modules/Media/VideoMetadata.cs`
- Create: `src/platform/Mavi.Infrastructure/Storage/LocalMediaStore.cs`
- Create: `src/platform/Mavi.Infrastructure/Media/FfprobeVideoMetadataReader.cs`
- Modify: `src/platform/Mavi.Infrastructure/DependencyInjection.cs`
- Modify: `src/platform/Mavi.Api/appsettings.json`
- Create: `tests/Mavi.Application.Tests/StorageKeyTests.cs`
- Create: `tests/Mavi.IntegrationTests/LocalMediaStoreTests.cs`
- Create: `tests/Mavi.IntegrationTests/FfprobeVideoMetadataReaderTests.cs`

**Interfaces:**

```csharp
public sealed record MediaWriteResult(long SizeBytes, string Sha256);

public interface IMediaStore
{
    Task<MediaWriteResult> WriteAsync(string storageKey, Stream content, CancellationToken cancellationToken);
    Task<Stream> OpenReadAsync(string storageKey, CancellationToken cancellationToken);
    Task<bool> ExistsAsync(string storageKey, CancellationToken cancellationToken);
    Task DeleteAsync(string storageKey, CancellationToken cancellationToken);
}
```

```csharp
public interface IVideoMetadataReader
{
    Task<VideoMetadata> ReadAsync(string storageKey, CancellationToken cancellationToken);
}
```

**Accepted Task-5 implementation refinement:** Application and API contracts remain storage-key based.
`IMediaStore` does not expose `GetLocalPath`, and `IVideoMetadataReader` receives a logical `storageKey`,
not a physical local path. Physical-path resolution is an Infrastructure-only implementation detail
shared internally by `LocalMediaStore` and `FfprobeVideoMetadataReader`. `LocalMediaStore` promotes a
uniquely named temporary sibling with an atomic move, keeping temporary and final files on the same
filesystem without creating a second full-size copy. This refinement preserves the approved Phase-1
scope and storage abstraction.

- [ ] **Step 1: Write failing LocalMediaStore path traversal test**

```csharp
[Theory]
[InlineData("../secret.txt")]
[InlineData("/root/file.mp4")]
[InlineData("C:\\secret.mp4")]
[InlineData("source\\bad.mp4")]
public async Task StorageOperationsRejectUnsafeStorageKeys(string key)
{
    using var temp = new TemporaryDirectory();
    var store = new LocalMediaStore(temp.Path);

    await Assert.ThrowsAnyAsync<Exception>(() =>
        store.ExistsAsync(key, CancellationToken.None));
}
```

- [ ] **Step 2: Implement LocalMediaStore and verify tests**

Storage-key normalization rule: forward slash only; each segment non-empty, not `.`/`..`; no colon/backslash/leading slash.

`WriteAsync` writes to a temporary sibling file then atomically moves to final name on the same volume; computes SHA-256 and byte count while copying.

- [ ] **Step 3: Write failing ffprobe metadata test**

The test generates a 2-second MP4 with the locally installed ffmpeg executable:

```powershell
ffmpeg -y -f lavfi -i "testsrc=size=640x360:rate=25" -t 2 -pix_fmt yuv420p test.mp4
```

Test assertion:

```csharp
var metadata = await reader.ReadAsync("source/test.mp4", CancellationToken.None);
Assert.InRange(metadata.DurationMs, 1_900, 2_100);
Assert.Equal(640, metadata.Width);
Assert.Equal(360, metadata.Height);
Assert.Equal(25, metadata.FrameRateNumerator);
Assert.Equal(1, metadata.FrameRateDenominator);
```

- [ ] **Step 4: Implement ffprobe process invocation**

Invoke:

```text
ffprobe -v error -print_format json -show_streams -show_format <file>
```

Use `ProcessStartInfo.ArgumentList`; redirect stdout/stderr; enforce a 30-second timeout; parse rational `avg_frame_rate` without converting it to an imprecise decimal.

- [ ] **Step 5: Add configuration**

`appsettings.json`:

```json
{
  "MediaStorage": {
    "RootPath": "D:\\MAVI-Data"
  },
  "MediaProcessing": {
    "FfprobePath": "ffprobe"
  }
}
```

Development may override root path through `MediaStorage__RootPath`.

- [ ] **Step 6: Run tests/build**

```powershell
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter "LocalMediaStoreTests|FfprobeVideoMetadataReaderTests"
dotnet build MAVI.sln
```

- [ ] **Step 7: Commit**

```powershell
git add src/platform tests/Mavi.IntegrationTests
git commit -m "feat: add managed media storage and video metadata"
```

---

## Task 6: Implement MP4 Import and Video Catalog API

**Files:**
- Create: `src/platform/Mavi.Application/Modules/Media/IVideoCatalog.cs`
- Create: `src/platform/Mavi.Application/Modules/Media/VideoImportService.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Repositories/VideoCatalog.cs`
- Create: `src/platform/Mavi.Contracts/Api/Videos/VideoAssetResponse.cs`
- Create: `src/platform/Mavi.Api/Endpoints/VideoEndpoints.cs`
- Modify: `src/platform/Mavi.Api/Program.cs`
- Modify: `src/platform/Mavi.Infrastructure/DependencyInjection.cs`
- Create: `tests/Mavi.Application.Tests/VideoImportServiceTests.cs`
- Create: `tests/Mavi.IntegrationTests/VideoImportApiTests.cs`

**Interfaces:**

```csharp
public sealed record ImportVideoCommand(
    Guid CameraId,
    DateTime RecordingStartLocal,
    string OriginalFileName,
    Stream Content);
```

- [ ] **Step 1: Write failing timestamp conversion tests**

```csharp
[Fact]
public async Task ImportUsesCameraTimezoneToCreateUtcStart()
{
    var camera = Camera.Create("CAM-0001", "Main Gate", "Asia/Kolkata");
    // fake repositories/media/metadata return a 60-second valid MP4
    var local = new DateTime(2026, 9, 8, 14, 0, 0, DateTimeKind.Unspecified);

    var result = await service.ImportAsync(
        new ImportVideoCommand(camera.Id, local, "gate.mp4", stream),
        CancellationToken.None);

    Assert.Equal(new DateTimeOffset(2026, 9, 8, 8, 30, 0, TimeSpan.Zero), result.RecordingStartUtc);
}
```

Add a separate test using a DST timezone/date that `TimeZoneInfo.IsAmbiguousTime` detects; service must return `invalid_recording_time` rather than choose an offset.

- [ ] **Step 2: Implement import service**

Required algorithm:

```text
get active camera
validate .mp4 filename
generate VideoAsset UUIDv7 before writing source media
build final source/<camera-id>/<yyyy>/<MM>/<dd>/<video-asset-id>.mp4 key from immutable IDs
write incoming stream directly to the final logical key
let IMediaStore.WriteAsync perform its own temp-sibling write and atomic final move
ffprobe the managed file
check duplicate SHA-256 in catalog
create Artifact + VideoAsset transaction
compensating-delete newly written managed media on duplicate, metadata failure, or DB failure
```

Do not buffer the complete stream in memory. Do not add a second whole-file copy to promote a staging object; `IMediaStore.WriteAsync` owns the temporary sibling and atomic move to the final key. This is an implementation refinement and does not change Phase-1 scope.

- [ ] **Step 3: Write failing API integration test**

Generate a 2-second MP4, POST multipart form, then delete the local source fixture and GET the imported VideoAsset.

Assert:

```text
201 Created
ProcessingStatus = NotQueued
managed source artifact exists
GET /api/videos/{id} works
```

Add duplicate test expecting `409 Conflict` and `video_duplicate`.

- [ ] **Step 4: Implement API endpoints**

```http
POST /api/videos/import
GET  /api/videos
GET  /api/videos/{id}
```

Configure ASP.NET form/request body limit to 10 GiB. Use `IFormFile.OpenReadStream()` and asynchronous copy; never call `ReadAllBytes`.

- [ ] **Step 5: Run tests/build**

```powershell
dotnet test tests/Mavi.Application.Tests/Mavi.Application.Tests.csproj --filter VideoImportServiceTests
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter VideoImportApiTests
dotnet build MAVI.sln
```

- [ ] **Step 6: Manual acceptance**

Register Camera 01, import a real MP4, remove/move the original source file, and confirm the managed source remains accessible through MAVI.

- [ ] **Step 7: Commit**

```powershell
git add src/platform tests
git commit -m "feat: add managed mp4 ingestion"
```

---

## Task 7: Define Worker Transport Contracts and Job Leasing

**Files:**
- Replace/expand: `src/platform/Mavi.Contracts/Worker/WorkerContracts.cs`
- Create: `src/platform/Mavi.Contracts/Worker/VisionJobContracts.cs`
- Create: `src/platform/Mavi.Contracts/Worker/VisionResultContracts.cs`
- Update: `contracts/schemas/vision-job.schema.json`
- Update: `contracts/schemas/vision-result.schema.json`
- Update: `contracts/examples/vision-job.example.json`
- Update: `contracts/examples/vision-result.example.json`
- Create: `src/platform/Mavi.Application/Modules/Processing/IProcessingRepository.cs`
- Create: `src/platform/Mavi.Application/Modules/Processing/ProcessingService.cs`
- Create: `src/platform/Mavi.Application/Modules/Processing/VisionJobLeaseService.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingRepository.cs`
- Create: `src/platform/Mavi.Api/Endpoints/VisionJobEndpoints.cs`
- Modify: `src/platform/Mavi.Api/Endpoints/VideoEndpoints.cs`
- Create: `tests/Mavi.Application.Tests/VisionJobLeaseServiceTests.cs`
- Create: `tests/Mavi.IntegrationTests/VisionJobLeaseApiTests.cs`

**Interfaces:**

`LeaseVisionJobRequest`:

```csharp
public sealed record LeaseVisionJobRequest(string WorkerId, string Pipeline);
```

`VisionJobLeaseResponse` contains exact fields from the spec and no absolute path.

- [ ] **Step 1: Write failing lease concurrency test**

Application/service test creates one queued job and invokes two lease operations concurrently. Exactly one receives the job; the other receives no job.

Pseudo-assertion:

```csharp
Assert.Equal(1, results.Count(x => x is not null));
Assert.Equal(1, repository.Job.AttemptCount);
```

- [ ] **Step 2: Implement atomic PostgreSQL lease**

In `ProcessingRepository.LeaseNextAsync`, use one transaction and PostgreSQL row locking equivalent to:

```sql
SELECT *
FROM vision_jobs
WHERE pipeline = @pipeline
  AND (
    status = 'Queued'
    OR (status = 'Leased' AND lease_expires_at_utc < @now)
  )
  AND attempt_count < 3
ORDER BY created_at_utc
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

Then update lease owner/expiry/attempt in the same transaction.

Do not implement lease by `SELECT` then unlocked `UPDATE`.

- [ ] **Step 3: Write failing process endpoint test**

`POST /api/videos/{id}/process` must create one ProcessingRun + VisionJob and set VideoAsset to Queued. A second call while active returns `409 processing_already_active`.

- [ ] **Step 4: Implement process/lease/heartbeat endpoints**

```http
POST /api/videos/{id}/process
GET  /api/videos/{id}/processing
POST /api/vision/jobs/lease
POST /api/vision/jobs/{id}/heartbeat
POST /api/vision/jobs/{id}/fail
```

Heartbeat default lease extension: 120 seconds. Reject invalid worker ownership.

- [ ] **Step 5: Verify JSON schemas/examples**

Use repository `tools/verify_repo.py` plus a small Python JSON-schema check if already available; otherwise validate examples in `src/vision/tests` when Python contracts land in Task 8.

- [ ] **Step 6: Run tests/build**

```powershell
dotnet test tests/Mavi.Application.Tests/Mavi.Application.Tests.csproj --filter VisionJobLeaseServiceTests
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter VisionJobLeaseApiTests
dotnet build MAVI.sln
```

- [ ] **Step 7: Commit**

```powershell
git add src/platform contracts tests
git commit -m "feat: add leasable vision processing jobs"
```

---

## Task 8: Build a Dummy Python Worker Against the Real Job API

**Files:**
- Modify: `src/vision/pyproject.toml`
- Modify: `src/vision/mavi_vision/common/contracts.py`
- Create: `src/vision/mavi_vision/common/settings.py`
- Create: `src/vision/mavi_vision/storage/local_media_store.py`
- Create: `src/vision/mavi_vision/worker/client.py`
- Create: `src/vision/mavi_vision/worker/main.py`
- Create: `src/vision/tests/test_worker_client.py`
- Create: `src/vision/tests/test_storage.py`

**Interfaces:**
- Consumes: Task-7 JSON/API contracts.
- Produces: worker that leases, heartbeats and fails/completes jobs without AI.

- [ ] **Step 1: Change Python support baseline to 3.12**

`pyproject.toml`:

```toml
[project]
requires-python = ">=3.12,<3.13"
dependencies = [
  "httpx>=0.28,<0.29",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.10,<3",
  "msgpack>=1.1,<2"
]

[project.optional-dependencies]
dev = ["pytest>=8.4,<9"]
```

Create a Python 3.12 virtual environment and install editable dev package:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e "src/vision[dev]"
```

- [ ] **Step 2: Write failing contract parsing test**

```python
def test_job_lease_contract_rejects_absolute_storage_path():
    payload = valid_job_payload()
    payload["sourceStorageKey"] = r"D:\MAVI-Data\source\x.mp4"

    with pytest.raises(ValidationError):
        VisionJobLease.model_validate(payload)
```

- [ ] **Step 3: Implement Pydantic worker contracts**

Mirror JSON names/types exactly. `source_storage_key` validator enforces logical forward-slash storage key.

- [ ] **Step 4: Write failing worker lifecycle test with httpx.MockTransport**

The test must verify:

```text
lease called
heartbeat called with workerId
fail called when processor raises
```

No real HTTP server required.

- [ ] **Step 5: Implement WorkerClient and dummy loop**

Environment settings:

```text
MAVI_API_BASE_URL=https://localhost:62152
MAVI_WORKER_ID=dev-worker-01
MAVI_MEDIA_ROOT=D:\MAVI-Data
MAVI_PIPELINE=phase1-detection-tracking
```

`worker.main` polls every 2 seconds; when a job is leased, dummy processing performs heartbeat then reports a deliberate `vision_dummy_not_implemented` failure until Task 9 supplies a processor. This proves orchestration without fake success intelligence.

- [ ] **Step 6: Test against running MAVI API**

Queue one imported VideoAsset, run:

```powershell
python -m mavi_vision.worker.main
```

Expected: job transitions Queued → Running → Failed with `vision_dummy_not_implemented`, source video stays intact, retry can create/release a new run.

- [ ] **Step 7: Run Python tests**

```powershell
pytest src/vision/tests -q
```

- [ ] **Step 8: Commit**

```powershell
git add src/vision
git commit -m "feat: add vision worker job client"
```

---

## Task 9: Build the Independent Vision Pipeline With Deterministic Fixtures

**Files:**
- Create: `src/vision/mavi_vision/video/reader.py`
- Create: `src/vision/mavi_vision/video/trajectory.py`
- Create: `src/vision/mavi_vision/detection/fixture.py`
- Create: `src/vision/mavi_vision/tracking/fixture.py`
- Create: `src/vision/mavi_vision/quality/scoring.py`
- Create: `src/vision/mavi_vision/pipeline/process_video.py`
- Create: `src/vision/tests/test_trajectory.py`
- Create: `src/vision/tests/test_quality.py`
- Create: `src/vision/tests/test_process_video_fixture.py`

**Interfaces:**
- Produces: model-independent `VideoProcessor.process(job) -> VisionProcessingResult`.
- Uses the existing detector/tracker interfaces; fixture implementations make pipeline tests deterministic before GPU integration.

- [ ] **Step 1: Add non-model video dependencies**

Add to Python dependencies:

```toml
"av>=15,<16",
"numpy>=2.2,<3",
"pillow>=11,<12"
```

Install editable package again.

- [ ] **Step 2: Write failing trajectory round-trip test**

```python
def test_trajectory_messagepack_round_trip(tmp_path):
    trajectory = TrackTrajectory(
        schema="mavi.track-trajectory.v1",
        track_local_number=17,
        points=[TrajectoryPoint(1, 40, .1, .2, .3, .4, .9)],
    )
    path = tmp_path / "track.msgpack"

    write_trajectory(path, trajectory)
    loaded = read_trajectory(path)

    assert loaded == trajectory
```

- [ ] **Step 3: Implement MessagePack trajectory model/writer**

Use float32-compatible values; ensure no Python-specific object serialization is used. Serialize plain maps/arrays only.

- [ ] **Step 4: Write failing quality-scoring tests**

Assert that a large, sharp, central high-confidence crop scores higher than a small edge-clipped low-confidence crop. Keep the function deterministic:

```python
score = 0.35 * area_score + 0.30 * sharpness_score + 0.25 * confidence + 0.10 * edge_score
```

Clamp to `[0,1]`.

- [ ] **Step 5: Implement PTS-aware frame reader**

`reader.py` yields:

```python
@dataclass(frozen=True)
class DecodedFrame:
    source_frame_number: int
    video_offset_ms: int
    image: np.ndarray
```

Derive offset from frame PTS/time base where present; fall back to source-frame/rational-frame-rate only when PTS is unavailable and record a warning.

- [ ] **Step 6: Write failing deterministic pipeline test**

Use a generated 2-second video plus `FixtureDetector`/`FixtureTracker` that yield one stable Person track. Assert result has:

```text
1 Track
ordered offsets
representative observation
thumbnail staging artifact
trajectory staging artifact
```

- [ ] **Step 7: Implement fixture pipeline until test passes**

Artifacts go only under:

```text
staging/<job-id>/thumbnails/...
staging/<job-id>/trajectories/...
```

- [ ] **Step 8: Run Python tests**

```powershell
pytest src/vision/tests -q
```

- [ ] **Step 9: Commit**

```powershell
git add src/vision
git commit -m "feat: add deterministic vision processing pipeline"
```

---

## Task 10: Integrate RTMDet and ByteTrack Behind the Existing Interfaces

**Files:**
- Create: `src/vision/mavi_vision/detection/rtmdet.py`
- Create: `src/vision/mavi_vision/tracking/bytetrack.py`
- Modify: `src/vision/mavi_vision/pipeline/process_video.py`
- Modify: `src/vision/pyproject.toml`
- Create: `src/vision/tests/test_rtmdet_mapping.py`
- Create: `src/vision/tests/test_bytetrack_adapter.py`
- Create: `models/manifests/rtmdet-phase1.json`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: model-independent pipeline from Task 9.
- Produces: real Person/Vehicle Track results.

- [ ] **Step 1: Record GPU/runtime evidence before installing model stack**

Run and save output in the implementation log/commit notes:

```powershell
nvidia-smi
py -3.12 --version
```

The implementation must use an official PyTorch wheel compatible with the installed NVIDIA driver. Do not install a nightly build. If GPU installation is blocked, use the official CPU wheel to complete functional integration; performance optimization is not a correctness gate for Phase 1.

- [ ] **Step 2: Add model extras as an isolated optional dependency group**

Keep base worker install usable without MMDetection. `pyproject.toml` adds:

```toml
[project.optional-dependencies]
vision = [
  "mmengine>=0.10,<1",
  "mmdet>=3.3,<4",
  "supervision>=0.25,<1"
]
```

PyTorch/torchvision are installed from the official PyTorch index for the selected compute platform before `pip install -e "src/vision[vision,dev]"`.

Use `supervision.ByteTrack` as the ByteTrack implementation adapter; MAVI exposes only its own `Tracker` interface.

- [ ] **Step 3: Write failing detector class-mapping test**

```python
@pytest.mark.parametrize(
    ("label", "expected"),
    [("person", ObjectClass.PERSON),
     ("car", ObjectClass.VEHICLE),
     ("motorcycle", ObjectClass.VEHICLE),
     ("bus", ObjectClass.VEHICLE),
     ("truck", ObjectClass.VEHICLE)],
)
def test_coco_label_mapping(label, expected):
    assert map_detector_label(label) is expected
```

- [ ] **Step 4: Implement RTMDet adapter**

Use `mmdet.apis.DetInferencer` or the supported MMDetection inference API for the installed release. Model/config/checkpoint paths are read from settings, never downloaded implicitly during worker startup.

Reject/ignore unsupported detector classes before tracker input.

- [ ] **Step 5: Write and pass ByteTrack adapter test**

Feed a deterministic sequence of boxes representing one moving person across frames and assert one stable local track ID is returned.

- [ ] **Step 6: Create model manifest**

`models/manifests/rtmdet-phase1.json` contains:

```json
{
  "modelId": "rtmdet-phase1",
  "framework": "mmdetection",
  "purpose": "person-vehicle-detection",
  "checkpointFile": "rtmdet-phase1.pth",
  "configFile": "rtmdet-phase1.py",
  "sha256": null,
  "verificationStatus": "unverified",
  "classes": ["person", "car", "motorcycle", "bus", "truck"]
}
```

Do not commit checkpoint/config binaries under Git. An `unverified` manifest with `sha256: null` is permitted only during development before model staging. When the model is staged, compute the SHA-256, set the 64-character value, change `verificationStatus` to `verified`, and require repository verification to reject an unverified manifest in an offline release bundle.

- [ ] **Step 7: Process a sample video independently**

Run a CLI entrypoint that uses real adapters:

```powershell
python -m mavi_vision.pipeline.process_video --input sample-data\phase1\sample.mp4 --output D:\MAVI-Data\staging\manual-test
```

Expected: at least one valid Track on footage containing visible persons/vehicles; no requirement for real-time throughput.

- [ ] **Step 8: Run Python tests**

```powershell
pytest src/vision/tests -q
```

- [ ] **Step 9: Commit**

```powershell
git add src/vision models/manifests .gitignore
git commit -m "feat: add rtmdet and bytetrack adapters"
```

---

## Task 11: Validate and Atomically Persist Worker Results

**Files:**
- Create: `src/platform/Mavi.Application/Modules/Intelligence/VisionResultValidator.cs`
- Create: `src/platform/Mavi.Application/Modules/Intelligence/IProcessingResultStore.cs`
- Create: `src/platform/Mavi.Application/Modules/Intelligence/VisionResultIngestService.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingResultStore.cs`
- Modify: `src/platform/Mavi.Api/Endpoints/VisionJobEndpoints.cs`
- Modify: `src/platform/Mavi.Infrastructure/DependencyInjection.cs`
- Create: `tests/Mavi.Application.Tests/VisionResultValidatorTests.cs`
- Create: `tests/Mavi.IntegrationTests/VisionResultPersistenceTests.cs`

**Interfaces:**

```csharp
public sealed record VisionResultValidationContext(
    VisionJob Job,
    ProcessingRun Run,
    VideoAsset Video,
    VisionProcessingResult Result);
```

- [ ] **Step 1: Write failing result-validation tests**

At minimum:

```csharp
[Fact]
public void RejectsTrackOffsetBeyondVideoDuration()
{
    var context = VisionResultTestData.ValidContext(videoDurationMs: 60_000);
    context.Result.Tracks[0].EndOffsetMs = 60_001;

    var result = validator.Validate(context);

    Assert.False(result.IsValid);
    Assert.Contains(result.Errors, x => x.Code == "track_offset_out_of_range");
}

[Fact]
public void RejectsDuplicateLocalTrackNumbers()
{
    var context = VisionResultTestData.ValidContext();
    context.Result.Tracks.Add(context.Result.Tracks[0] with { TrackId = Guid.CreateVersion7() });

    var result = validator.Validate(context);

    Assert.Contains(result.Errors, x => x.Code == "duplicate_local_track_number");
}

[Fact]
public void RejectsInvalidNormalizedBoundingBox()
{
    var context = VisionResultTestData.ValidContext();
    context.Result.Tracks[0].Observations[0].BoundingBox =
        new BoundingBoxContract(-0.1f, 0.2f, 0.3f, 0.4f);

    var result = validator.Validate(context);

    Assert.Contains(result.Errors, x => x.Code == "invalid_bounding_box");
}

[Fact]
public void RejectsMissingTrajectoryArtifact()
{
    var context = VisionResultTestData.ValidContext();
    artifactInspector.MarkMissing(context.Result.Tracks[0].Trajectory.StorageKey);

    var result = validator.Validate(context);

    Assert.Contains(result.Errors, x => x.Code == "artifact_missing");
}
```

Create `tests/Mavi.Application.Tests/VisionResultTestData.cs` in this task. It must return one fully valid 10-second Person Track with one representative Observation, one trajectory descriptor and deterministic IDs, so each test changes exactly one invalid condition.

Use a fake `IArtifactInspector`/media-store abstraction for artifact existence/hash checks.

- [ ] **Step 2: Implement validator exactly to spec**

Return a structured validation result with stable error code `vision_result_invalid` and a list of field-level reasons. Do not partially sanitize bad results into accepted intelligence.

- [ ] **Step 3: Write failing atomicity integration test**

Construct a result containing two Tracks where the second has an invalid FK/artifact descriptor that causes persistence failure after the first Track would otherwise be inserted.

After failure assert:

```csharp
Assert.Empty(await db.Tracks.ToListAsync());
Assert.Empty(await db.Observations.ToListAsync());
```

The SourceVideo Artifact/VideoAsset must still exist.

- [ ] **Step 4: Implement ProcessingResultStore transaction**

Use `await db.Database.BeginTransactionAsync()` and persist all accepted intelligence plus status transitions in one transaction.

Artifact integrity:

```text
ExistsAsync(storageKey)
size matches descriptor
SHA-256 matches descriptor
```

- [ ] **Step 5: Add completion endpoint**

```http
POST /api/vision/jobs/{jobId}/complete
```

Success returns `200 OK` with ProcessingRun ID and accepted Track count. Duplicate completion after a committed success returns the same successful status without inserting duplicates.

- [ ] **Step 6: Replace dummy worker failure with real completion**

Update Python worker to call `VideoProcessor.process(job)` and POST result. On uncaught processing exceptions, call `/fail` with a stable error code.

- [ ] **Step 7: Run .NET/Python tests**

```powershell
dotnet test MAVI.sln
pytest src/vision/tests -q
```

- [ ] **Step 8: Manual end-to-end backend test**

Without React:

```text
POST camera
POST video import
POST process
run Python worker
GET video processing -> Processed
query database/API -> Tracks exist
```

- [ ] **Step 9: Commit**

```powershell
git add src/platform src/vision tests
git commit -m "feat: persist validated visual intelligence results"
```

---

## Task 12: Add Track Search and Evidence Content APIs

**Files:**
- Create: `src/platform/Mavi.Application/Modules/Intelligence/ITrackSearchRepository.cs`
- Create: `src/platform/Mavi.Application/Modules/Intelligence/TrackSearchService.cs`
- Create: `src/platform/Mavi.Infrastructure/Persistence/Repositories/TrackSearchRepository.cs`
- Create: `src/platform/Mavi.Contracts/Api/Tracks/TrackSearchResponse.cs`
- Create: `src/platform/Mavi.Contracts/Api/Tracks/TrackDetailResponse.cs`
- Create: `src/platform/Mavi.Api/Endpoints/TrackEndpoints.cs`
- Create: `src/platform/Mavi.Api/Endpoints/ArtifactEndpoints.cs`
- Modify: `src/platform/Mavi.Api/Endpoints/VideoEndpoints.cs`
- Create: `tests/Mavi.Application.Tests/TrackSearchServiceTests.cs`
- Create: `tests/Mavi.IntegrationTests/TrackSearchApiTests.cs`
- Create: `tests/Mavi.IntegrationTests/VideoContentApiTests.cs`

**Interfaces:**

```csharp
public sealed record TrackSearchQuery(
    Guid? CameraId,
    Guid? VideoAssetId,
    ObjectClass? ObjectClass,
    DateTimeOffset? FromUtc,
    DateTimeOffset? ToUtc,
    long? MinimumDurationMs,
    double? MinimumConfidence,
    int Page = 1,
    int PageSize = 50);
```

- [ ] **Step 1: Write failing structured-search tests**

Seed completed and failed ProcessingRuns. Assert `GET /api/tracks` returns only Tracks from completed runs and correctly combines Camera + ObjectClass + time filters.

- [ ] **Step 2: Implement paged search repository**

Query joins Track → VideoAsset → Camera → representative Observation/Thumbnail Artifact. Use `AsNoTracking()`. Maximum page size 100. Default order newest first.

- [ ] **Step 3: Write failing HTTP Range test**

Request:

```http
GET /api/videos/{id}/content
Range: bytes=0-99
```

Assert status `206 Partial Content`, 100 response bytes, and appropriate `Content-Range` header.

- [ ] **Step 4: Implement content endpoints**

```http
GET /api/videos/{videoAssetId}/content
GET /api/artifacts/{artifactId}/content
GET /api/tracks/{trackId}
```

Resolve every file through Artifact + `IMediaStore`. Use seekable stream/file result with range processing. Do not expose storage keys or local paths in public DTOs unless a storage key is explicitly required by the worker contract.

- [ ] **Step 5: Run tests/build**

```powershell
dotnet test tests/Mavi.Application.Tests/Mavi.Application.Tests.csproj --filter TrackSearchServiceTests
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter "TrackSearchApiTests|VideoContentApiTests"
dotnet build MAVI.sln
```

- [ ] **Step 6: Commit**

```powershell
git add src/platform tests
git commit -m "feat: add track search and evidence streaming"
```

---

## Task 13: Add React Application Foundation, Cameras, Import and Processing UI

**Files:**
- Modify: `src/web/mavi-web/package.json`
- Modify: `src/web/mavi-web/src/App.tsx`
- Create: `src/web/mavi-web/src/api/client.ts`
- Create: `src/web/mavi-web/src/api/cameras.ts`
- Create: `src/web/mavi-web/src/api/videos.ts`
- Create: `src/web/mavi-web/src/app/router.tsx`
- Create: `src/web/mavi-web/src/features/cameras/CamerasPage.tsx`
- Create: `src/web/mavi-web/src/features/video-import/VideoImportPage.tsx`
- Create: `src/web/mavi-web/src/features/processing/ProcessingPage.tsx`
- Create: `src/web/mavi-web/src/features/cameras/CamerasPage.test.tsx`
- Create: `src/web/mavi-web/src/features/video-import/VideoImportPage.test.tsx`

**Interfaces:**
- Consumes: Tasks 4, 6 and 7 API routes.

- [ ] **Step 1: Add frontend dependencies/test tooling**

```powershell
cd src/web/mavi-web
npm install react-router-dom @tanstack/react-query
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

Add scripts:

```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 2: Write failing Cameras page test**

Mock fetch/API module and assert returned cameras render with code/name and an Add Camera form submits the expected request.

- [ ] **Step 3: Implement shared API client/router/Cameras page**

Routes:

```text
/cameras
/import
/processing/:videoAssetId
/search
/review/video/:videoAssetId
```

TanStack Query owns server-state caching. No Redux.

- [ ] **Step 4: Write failing Video Import page test**

Assert:

```text
camera selector required
recording date/time required
.mp4 file required
successful import calls process endpoint and navigates to processing route
```

- [ ] **Step 5: Implement Import and Processing pages**

Processing page polls `GET /api/videos/{id}/processing` every 2 seconds while queued/running, stops polling on processed/failed, and exposes Retry on failure.

- [ ] **Step 6: Verify frontend**

```powershell
npm test
npm run typecheck
npm run build
```

- [ ] **Step 7: Commit**

```powershell
cd ../../..
git add src/web/mavi-web
git commit -m "feat: add camera import and processing ui"
```

---

## Task 14: Add React Visual Search and Evidence Review

**Files:**
- Create: `src/web/mavi-web/src/api/tracks.ts`
- Create: `src/web/mavi-web/src/features/visual-search/VisualSearchPage.tsx`
- Create: `src/web/mavi-web/src/features/visual-search/TrackResultCard.tsx`
- Create: `src/web/mavi-web/src/features/video-review/VideoReviewPage.tsx`
- Create: `src/web/mavi-web/src/features/visual-search/VisualSearchPage.test.tsx`
- Create: `src/web/mavi-web/src/features/video-review/VideoReviewPage.test.tsx`

**Interfaces:**
- Consumes: Task-12 Track/evidence APIs.

- [ ] **Step 1: Write failing Visual Search test**

Render page with mocked cameras and tracks. Set `Vehicle`, Camera 01 and time range; click Search; assert query parameters are sent and result cards show thumbnail, camera, start time, duration, confidence.

- [ ] **Step 2: Implement structured search UI**

Filters exactly match Phase-1 API. Use URL query parameters so searches are bookmarkable/reloadable.

- [ ] **Step 3: Write failing review seek test**

Mock HTMLMediaElement and a Track detail with `StartOffsetMs=197420`. Assert loaded metadata handler sets:

```text
currentTime = 196.420
```

(one-second preroll, clamped at zero).

- [ ] **Step 4: Implement Video Review**

Use native `<video controls>` with:

```text
src=/api/videos/{videoAssetId}/content
```

Display selected Track metadata and representative thumbnail. Do not implement trajectory overlay until basic seek/playback is stable.

- [ ] **Step 5: Verify frontend**

```powershell
cd src/web/mavi-web
npm test
npm run typecheck
npm run build
```

- [ ] **Step 6: Commit**

```powershell
cd ../../..
git add src/web/mavi-web
git commit -m "feat: add visual track search and evidence review"
```

---

## Task 15: End-to-End PoC Hardening, Ground Truth and Offline Readiness

**Files:**
- Create: `sample-data/ground-truth/phase1-example.json`
- Create: `tools/phase1_e2e_check.py`
- Create: `docs/runbooks/phase1-local-development.md`
- Modify: `docs/runbooks/offline-readiness.md`
- Modify: `README.md`
- Create: `tests/Mavi.IntegrationTests/ProcessingFailureRecoveryTests.cs`
- Create: `src/vision/tests/test_worker_end_to_end_contract.py`

**Interfaces:**
- Validates the complete Phase-1 system rather than adding new analytical capability.

- [ ] **Step 1: Write failing failure-recovery integration test**

Scenario:

```text
import video
queue processing
lease job
fail job
assert VideoAsset source remains
assert no Tracks exist
queue processing again
assert new ProcessingRun and new VisionJob IDs
```

- [ ] **Step 2: Implement any missing retry/recovery behaviour only to satisfy the test**

Do not add automatic infinite retry. Explicit reprocess creates a new run.

- [ ] **Step 3: Create controlled ground-truth manifest schema/example**

Example:

```json
{
  "video": "controlled-gate-01.mp4",
  "cameraCode": "CAM-0001",
  "events": [
    { "objectClass": "Person", "startOffsetMs": 4200, "endOffsetMs": 9100 },
    { "objectClass": "Vehicle", "startOffsetMs": 22000, "endOffsetMs": 31500 }
  ]
}
```

No identities/biometric labels are required for Phase 1.

- [ ] **Step 4: Add performance/acceptance checker**

`tools/phase1_e2e_check.py` calls MAVI APIs and prints:

```text
video duration
processing duration
frames processed
processing FPS
tracks by class
search latency
tracks resolving to source evidence
orphan track count
```

The script exits nonzero if any accepted Track lacks source evidence or if processing status is inconsistent.

- [ ] **Step 5: Verify offline runtime path**

With required packages/model/FFmpeg already staged locally, disconnect Internet or block outbound access and verify:

```text
API starts
React loads without CDN calls
PostgreSQL works
worker starts without downloading model weights
one already-imported/sample video can be processed
search and evidence playback work
```

Document every required offline artifact in `docs/runbooks/offline-readiness.md`.

- [ ] **Step 6: Run complete verification**

From repository root:

```powershell
dotnet build MAVI.sln
dotnet test MAVI.sln

.\.venv\Scripts\Activate.ps1
pytest src/vision/tests -q

cd src/web/mavi-web
npm test
npm run typecheck
npm run build
cd ../../..

python tools/verify_repo.py
```

Then execute the manual Phase-1 acceptance sequence from the spec.

Expected:

```text
all .NET tests pass
all Python tests pass
frontend tests/typecheck/build pass
repo verification passes
end-to-end import → process → search → evidence playback succeeds
```

- [ ] **Step 7: Commit**

```powershell
git add .
git commit -m "test: harden phase1 visual memory poc"
```

---

# Phase-1 Review Checkpoints

Do not execute all tasks without review. Recommended agentic checkpoints:

1. **After Task 3:** inspect domain model, migration and DB constraints before APIs build on them.
2. **After Task 6:** manually prove managed import and evidence ownership.
3. **After Task 8:** prove .NET↔Python job orchestration without AI.
4. **After Task 10:** review detector/tracker runtime, license provenance and model manifest.
5. **After Task 11:** inspect atomic intelligence persistence before exposing search.
6. **After Task 14:** conduct operator-flow review of Import → Processing → Search → Review.
7. **After Task 15:** formally decide whether Phase 1 is accepted before starting Phase 2 embeddings/entity memory.

# Final Phase-1 Acceptance Command Set

```powershell
# .NET
dotnet build MAVI.sln
dotnet test MAVI.sln

# Python
.\.venv\Scripts\Activate.ps1
pytest src/vision/tests -q

# React
cd src/web/mavi-web
npm test
npm run typecheck
npm run build
cd ../../..

# Repository invariants
python tools/verify_repo.py
```

Manual acceptance is then performed against one controlled MP4:

```text
1. Create Camera 01.
2. Import MP4 with recording start time.
3. Verify managed source video survives removal of original source.
4. Queue processing.
5. Run Python worker.
6. Observe Queued → Processing → Processed.
7. Search Person and Vehicle Tracks.
8. Open representative thumbnail.
9. Click View Video and verify correct source-video time.
10. Re-run with Internet disconnected and locally staged dependencies/model.
```

Phase 1 is not accepted merely because the detector produces boxes. It is accepted only when the complete evidence-linked searchable-memory workflow is repeatable and the automated verification suite is green.
