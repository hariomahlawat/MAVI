using Mavi.Application.Modules.SceneAnalytics.Configuration;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.Cameras;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.Infrastructure.SceneAnalytics;
using Mavi.Infrastructure.Storage;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// A camera with an active scene revision and one completed, visible processing run
/// carrying one Track: the smallest world in which an analysis unit is eligible.
/// </summary>
/// <remarks>
/// Built through the real aggregates and the real migration rather than by inserting
/// rows, so a test that passes here passes against the schema the product ships.
/// </remarks>
internal sealed class SceneAnalyticsWorld
{
    public const string AlgorithmVersion = "scene-analytics-v1";

    public static readonly string ParametersSha256 = new('b', 64);

    /// <summary>The engine identity this world's units are created under.</summary>
    public static SceneAnalysisExecutionIdentity ExecutionIdentity { get; } =
        new(AlgorithmVersion, ParametersSha256);

    /// <summary>A host running a different engine, for mixed-version scenarios.</summary>
    public static SceneAnalysisExecutionIdentity IdentityFor(
        string algorithmVersion,
        string? parametersSha256 = null) =>
        new(algorithmVersion, parametersSha256 ?? ParametersSha256);

    private SceneAnalyticsWorld() { }

    public required PostgresFixture Fixture { get; init; }
    public required MutableTimeProvider Clock { get; init; }
    public Guid CameraId { get; private set; }
    public Guid VideoId { get; private set; }
    public Guid RunId { get; private set; }
    public Guid TrackId { get; private set; }
    public Guid RevisionId { get; private set; }
    public Guid ZoneId { get; private set; }
    public Guid LineId { get; private set; }
    public DateTimeOffset RunCompletedAtUtc { get; private set; }
    public DateTimeOffset RecordingStartUtc { get; private set; }
    public string EvidenceRoot { get; private set; } = string.Empty;
    public string MediaRoot { get; private set; } = string.Empty;

    public SceneAnalysisIdentity Identity => IdentityFor(RevisionId, AlgorithmVersion);

    public SceneAnalysisIdentity IdentityFor(Guid revisionId, string algorithmVersion) =>
        new(RunId, revisionId, algorithmVersion, ParametersSha256, SourceCommit: null);

    /// <summary>
    /// An executor wired to the real evidence reader, over this world's evidence root.
    /// </summary>
    /// <remarks>
    /// The reader is the production one, reading real files through the same path safety
    /// it enforces in the product. Substituting a stub here would leave the one part of
    /// the executor that touches the filesystem untested.
    /// </remarks>
    public (SceneAnalysisExecutor Executor, SceneAnalysisLifecycle Lifecycle, MaviDbContext Db) Executor()
    {
        var db = Fixture.CreateDbContext();
        var lifecycle = new SceneAnalysisLifecycle(db, Clock);
        var reader = new AcceptedEvidenceReader(Options.Create(new MediaStorageOptions
        {
            RootPath = MediaRoot,
            EvidenceRootPath = EvidenceRoot,
        }));
        var executor = new SceneAnalysisExecutor(
            lifecycle,
            new SceneAnalysisEvidenceReader(db, reader),
            new SceneConfigurationRepository(db),
            NullLogger<SceneAnalysisExecutor>.Instance);
        return (executor, lifecycle, db);
    }

    /// <summary>An executor with a substituted evidence reader, for fault injection.</summary>
    public SceneAnalysisExecutor ExecutorWith(
        ISceneAnalysisEvidenceReader evidence,
        SceneAnalysisLifecycle lifecycle) =>
        new(lifecycle, evidence, new SceneConfigurationRepository(Read()), NullLogger<SceneAnalysisExecutor>.Instance);

    /// <summary>
    /// Seals a trajectory artefact for the Track and records it, as the worker would.
    /// </summary>
    /// <param name="payload">The encoded v1 trajectory.</param>
    /// <param name="write">False to record the artefact but leave no file behind.</param>
    /// <param name="declaredSha256">Overrides the recorded digest, to fake corruption.</param>
    public async Task AttachTrajectoryAsync(
        byte[] payload,
        bool write = true,
        string? declaredSha256 = null)
    {
        var storageKey = $"evidence/{RunId:D}/attempt-0001/trajectories/person-000001.msgpack";
        var artifact = Artifact.Create(
            ArtifactType.TrackTrajectory,
            storageKey,
            "application/x-msgpack",
            payload.Length,
            declaredSha256 ?? TrajectoryPayload.Sha256Hex(payload));

        if (write)
        {
            var path = Path.Combine(
                EvidenceRoot,
                storageKey["evidence/".Length..].Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            await File.WriteAllBytesAsync(path, payload);
        }

        await using var db = Read();
        db.Artifacts.Add(artifact);
        await db.SaveChangesAsync();
        await db.Database.ExecuteSqlInterpolatedAsync(
            $"UPDATE tracks SET trajectory_artifact_id = {artifact.Id} WHERE id = {TrackId}");
    }

    /// <summary>A lifecycle bound to its own DbContext, as a separate host would have.</summary>
    public (SceneAnalysisLifecycle Lifecycle, MaviDbContext Db) Host()
    {
        var db = Fixture.CreateDbContext();
        return (new SceneAnalysisLifecycle(db, Clock), db);
    }

    public MaviDbContext Read() => Fixture.CreateDbContext();

    /// <summary>
    /// A host whose statements give up rather than queue behind another host's row lock.
    /// </summary>
    /// <remarks>
    /// This is what makes "did not block" assertable. A claim that waits for a lock and a
    /// claim that steps around it are indistinguishable once both have finished, so the
    /// only way to tell them apart is to make waiting fail.
    /// </remarks>
    public (SceneAnalysisLifecycle Lifecycle, MaviDbContext Db) ImpatientHost(int commandTimeoutSeconds = 3)
    {
        var connectionString = new NpgsqlConnectionStringBuilder(Fixture.ConnectionString)
        {
            CommandTimeout = commandTimeoutSeconds,
        }.ConnectionString;
        var options = new DbContextOptionsBuilder<MaviDbContext>()
            .UseNpgsql(connectionString, npgsql => npgsql.UseVector())
            .Options;
        var db = new MaviDbContext(options);
        return (new SceneAnalysisLifecycle(db, Clock), db);
    }

    public async Task<SceneAnalysis> UnitAsync(Guid analysisId)
    {
        await using var db = Read();
        return await db.SceneAnalyses.AsNoTracking().SingleAsync(x => x.Id == analysisId);
    }

    // Construction
    public static async Task<SceneAnalyticsWorld> CreateAsync(
        PostgresFixture fixture,
        DateTimeOffset nowUtc,
        bool analyticsEnabled = true,
        bool runVisible = true)
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();

        var world = new SceneAnalyticsWorld
        {
            Fixture = fixture,
            Clock = new MutableTimeProvider(nowUtc),
        };

        var camera = Camera.Create("CAM-LC-01", "Lifecycle Test Camera", "UTC");
        var source = Artifact.Create(
            ArtifactType.SourceVideo,
            $"source/CAM-LC-01/{Guid.CreateVersion7()}.mp4",
            "video/mp4",
            1,
            new string('a', 64));
        var video = VideoAsset.Create(
            camera.Id,
            source.Id,
            "lifecycle.mp4",
            nowUtc.AddMinutes(-30),
            10_000,
            25,
            1,
            640,
            360,
            "h264",
            TimestampSource.Manual,
            1.0);

        // The revision is activated before the run completes, so the run is inside the
        // automatic reconciliation window rather than history.
        var configuration = SceneConfiguration.Create(camera.Id, nowUtc.AddMinutes(-25));
        var revision = configuration.SaveRevision(
            null,
            Draft(analyticsEnabled),
            null,
            SceneRules.UnattributedDevelopmentActor,
            nowUtc.AddMinutes(-25));

        var completedAtUtc = nowUtc.AddMinutes(-10);
        var run = ProcessingRun.Create(video.Id, "phase1-detection-tracking-v1", "{}", nowUtc.AddMinutes(-20));
        run.MarkRunning("worker-01", nowUtc.AddMinutes(-15));
        run.MarkCompleted(250, 1, 5_000, completedAtUtc);
        if (runVisible)
        {
            run.AssignCompletionVisibilitySequence(1);
        }

        var track = Track.Create(
            run.Id,
            video.Id,
            1,
            ObjectClass.Person,
            0,
            8_000,
            nowUtc.AddMinutes(-30),
            detectionCount: 8,
            meanConfidence: 0.8,
            maxConfidence: 0.9,
            createdAtUtc: completedAtUtc);

        // A real run always has a job behind it, and the processing-status projection
        // joins the two; a world without one would look complete and project nothing.
        var job = VisionJob.Create(run.Id, "phase1-detection-tracking", nowUtc.AddMinutes(-20));

        db.AddRange(camera, source, video, configuration, revision, run, job, track);
        await db.SaveChangesAsync();

        world.CameraId = camera.Id;
        world.VideoId = video.Id;
        world.RunId = run.Id;
        world.TrackId = track.Id;
        world.RevisionId = revision.Id;
        world.ZoneId = revision.Zones.Count > 0 ? revision.Zones[0].ZoneId : Guid.Empty;
        world.LineId = revision.TripLines.Count > 0 ? revision.TripLines[0].LineId : Guid.Empty;
        world.RunCompletedAtUtc = completedAtUtc;
        world.RecordingStartUtc = nowUtc.AddMinutes(-30);
        world.MediaRoot = CreateRoot("media");
        world.EvidenceRoot = CreateRoot("evidence");
        return world;
    }

    /// <summary>Activates a second revision, as a geometry edit would.</summary>
    public async Task<Guid> ActivateNewRevisionAsync(DateTimeOffset atUtc)
    {
        await using var db = Read();
        var repository = new SceneConfigurationRepository(db);
        var configuration = await repository.GetByCameraAsync(CameraId, default)
            ?? throw new InvalidOperationException("The camera has no scene configuration.");
        var active = await repository.GetRevisionAsync(configuration.ActiveRevisionId!.Value, default);
        var revision = configuration.SaveRevision(
            active,
            Draft(analyticsEnabled: true),
            active!.RevisionNumber,
            SceneRules.UnattributedDevelopmentActor,
            atUtc);
        await repository.AddRevisionAsync(revision, default);
        await repository.SaveChangesAsync(default);
        return revision.Id;
    }

    // Facts
    public SceneAnalysisFacts Facts(Guid analysisId, string heading = "NE") =>
        new(
            [TrackAnalysisOutcome.Analysed(analysisId, TrackId, "bbox-centre", 120, 1, 400)],
            [
                TrackZoneVisit.Create(
                    analysisId, TrackId, ZoneId, 0, 1_000, 5_000,
                    RunCompletedAtUtc, RunCompletedAtUtc.AddSeconds(4), 4_000,
                    beganInside: false, endedInside: false, closedByGap: false, heading, "SW"),
            ],
            [
                TrackZoneSummary.Create(
                    analysisId, TrackId, ZoneId, 1, 4_000,
                    RunCompletedAtUtc, RunCompletedAtUtc.AddSeconds(4), true, 45, 4_000),
            ],
            [
                TrackLineCrossing.Create(
                    analysisId, TrackId, LineId, 0, 2_000,
                    RunCompletedAtUtc.AddSeconds(2), "AToB", 0.25, 0.5),
            ],
            [
                TrackMotionSummary.Create(
                    analysisId, TrackId, heading, 0.42, 0.01, 2_500, 2_500,
                    [new StationaryInterval(1_000, 3_500)], [ZoneId]),
            ]);

    private static string CreateRoot(string kind)
    {
        var path = Path.Combine(Path.GetTempPath(), $"mavi-analytics-{kind}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(path);
        return path;
    }

    private static SceneRevisionDraft Draft(bool analyticsEnabled) => new(
        "Lifecycle fixture",
        null,
        null,
        [
            new SceneZoneDraft(
                null,
                "Gate",
                null,
                analyticsEnabled,
                [
                    new ScenePointDraft(0.1, 0.1),
                    new ScenePointDraft(0.4, 0.1),
                    new ScenePointDraft(0.4, 0.4),
                    new ScenePointDraft(0.1, 0.4),
                ],
                45),
        ],
        [
            new TripLineDraft(
                null,
                "Kerb",
                analyticsEnabled,
                new ScenePointDraft(0.1, 0.5),
                new ScenePointDraft(0.9, 0.5),
                true,
                "inbound",
                "outbound"),
        ]);
}
