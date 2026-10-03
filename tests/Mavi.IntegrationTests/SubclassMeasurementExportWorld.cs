using System.Security.Cryptography;
using System.Text.Json;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Measurement;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// A completed completion-3.3 run persisted through the Domain factories and the real
/// schema: Vehicle Tracks resolved to each v1 value, one Vehicle whose vote abstained,
/// and a Person, each with an Evidence Set whose crops have real bytes, a trajectory and
/// a Representative pointer; the run's job has completed and its provenance attests the
/// supplied pipeline profile.
/// </summary>
internal sealed class SubclassMeasurementExportWorld : IDisposable
{
    public static readonly DateTimeOffset CompletedAt = new(2026, 10, 3, 9, 0, 0, TimeSpan.Zero);
    private static readonly JsonSerializerOptions WebJson = new(JsonSerializerDefaults.Web);

    private readonly List<string> _scratch = [];

    private SubclassMeasurementExportWorld(ApiTestFactory factory)
    {
        Factory = factory;
        Scratch = CreateScratch("mavi-s32-export");
    }

    public ApiTestFactory Factory { get; }
    public Task14TestData.BaseVideo Video { get; private set; } = null!;
    public Guid RunId { get; private set; }
    public string ProfilePath { get; private set; } = string.Empty;
    public string ProfileSha256 { get; private set; } = string.Empty;
    public string Scratch { get; }
    public IReadOnlyList<SeededTrack> Tracks { get; private set; } = [];

    internal sealed record SeededTrack(
        Guid TrackId,
        int LocalTrackNumber,
        ObjectClass ObjectClass,
        string? Subclass,
        IReadOnlyList<Guid> ObservationIds,
        IReadOnlyList<string> CropStorageKeys);

    /// <summary>The shipped pipeline profile, the one a Stage-3 run attests.</summary>
    public static byte[] ShippedProfileBytes() =>
        File.ReadAllBytes(Path.Combine(FindRepositoryRoot(), "src", "vision", "config", "pipelines", "phase1-detection-tracking-v1.json"));

    public static async Task<SubclassMeasurementExportWorld> CreateAsync(
        byte[]? profileBytes = null,
        string? provenanceJson = null,
        bool completeRun = true,
        bool completeJob = true,
        string cameraCode = "CAM-S32",
        bool finalizeJob = false)
    {
        var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var world = new SubclassMeasurementExportWorld(factory);
        world.ProfilePath = Path.Combine(world.Scratch, "pipeline-profile.json");
        var bytes = profileBytes ?? ShippedProfileBytes();
        await File.WriteAllBytesAsync(world.ProfilePath, bytes);
        world.ProfileSha256 = Sha256(bytes);
        world.Video = await Task14TestData.SeedBaseVideoAsync(factory, cameraCode);
        (world.RunId, world.Tracks) = await SeedRunAsync(
            factory,
            world.Video,
            provenanceJson ?? ProvenanceJson(world.ProfileSha256),
            world.ProfileSha256,
            completeRun,
            completeJob,
            finalizeJob: finalizeJob);
        return world;
    }

    /// <summary>Another completed run of the same video, with its own Vehicle Track.</summary>
    public async Task<Guid> AddOtherCompletedRunAsync() =>
        (await SeedRunAsync(Factory, Video, ProvenanceJson(ProfileSha256), ProfileSha256, true, true, localTrackBase: 100, vehicleOnly: true)).RunId;

    public static SubclassMeasurementExporter CreateExporter(
        IServiceScope scope,
        Func<MaviDbContext, CancellationToken, Task>? snapshotObserver = null) =>
        new(
            scope.ServiceProvider.GetRequiredService<MaviDbContext>(),
            scope.ServiceProvider.GetRequiredService<VisionRuntimeProvenanceParser>(),
            scope.ServiceProvider.GetRequiredService<IMediaStore>(),
            scope.ServiceProvider.GetRequiredService<IAcceptedEvidenceReader>())
        {
            SnapshotObserver = snapshotObserver,
        };

    public async Task<SubclassMeasurementExportResult> ExportAsync(string outputDirectory, Guid? runId = null, string? profilePath = null)
    {
        using var scope = Factory.Services.CreateScope();
        return await CreateExporter(scope).RunAsync(runId ?? RunId, profilePath ?? ProfilePath, outputDirectory, CancellationToken.None);
    }

    public string NewOutputPath(string name = "export") => Path.Combine(Scratch, $"{name}-{Guid.NewGuid():N}");

    public async Task ExecuteSqlAsync(FormattableString sql)
    {
        using var scope = Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        await db.Database.ExecuteSqlInterpolatedAsync(sql);
    }

    public async Task ExecuteRawSqlAsync(string sql)
    {
        using var scope = Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        await db.Database.ExecuteSqlRawAsync(sql);
    }

    public string EvidencePath(string storageKey) =>
        Path.Combine(Factory.EvidenceRoot, storageKey["evidence/".Length..].Replace('/', Path.DirectorySeparatorChar));

    public string SourcePath() =>
        Path.Combine(Factory.MediaRoot, Video.SourceStorageKey.Replace('/', Path.DirectorySeparatorChar));

    public static string ProvenanceJson(string pipelineProfileSha256)
    {
        var contract = new VisionRuntimeProvenanceContract(
            "rtmdet-m",
            "1",
            new string('1', 64),
            new string('2', 64),
            new string('3', 64),
            "phase1-detection-tracking-v1",
            "1.3.0-candidate",
            pipelineProfileSha256,
            null,
            null,
            "unverified",
            "runtime-v1",
            new string('5', 64),
            "linux-x86_64-cpu",
            null,
            "mmdetection",
            new Dictionary<string, string>
            {
                ["python"] = "3.12.14",
                ["torch"] = "2.6.0",
                ["torchvision"] = "0.21.0",
                ["mmdet"] = "3.3.0",
                ["mmcv"] = "2.1.0",
                ["mmengine"] = "0.10.7",
                ["trackers"] = "2.6.0",
                ["supervision"] = "0.30.2",
                ["scipy"] = "1.18.1",
                ["numpy"] = "2.5.3",
                ["opencv"] = "5.0.0",
                ["opencvPython"] = "5.0.0.93",
                ["av"] = "16.1.0",
                ["pillow"] = "11.3.0",
            },
            "ffmpeg-7",
            new VisionPlatformIdentityContract(
                "Linux", "6.8", "qualified", "x86_64", "x86_64",
                "3.12.14", "CPython", ["main", "Sep 2026"], "GCC"),
            "cpu",
            0,
            "cpu",
            null,
            "build-attestation",
            new string('a', 40),
            "every-frame",
            new VisionTrackerParametersContract(30, .25, .1, .2, 2, 1),
            "RGB");
        return JsonSerializer.Serialize(contract with
        {
            CapabilityId = "detector",
            ModelPackId = "mavi-model-v2-" + new string('7', 64),
            RuntimePackId = "mavi-runtime-v2-" + new string('8', 64),
            RuntimePackSource = "installed-pack",
            ComponentBindingSha256 = new string('9', 64),
        }, WebJson);
    }

    private sealed record TrackSpec(int Number, ObjectClass ObjectClass, string? Subclass, ObservationType[] Roles);

    private static async Task<(Guid RunId, IReadOnlyList<SeededTrack> Tracks)> SeedRunAsync(
        ApiTestFactory factory,
        Task14TestData.BaseVideo video,
        string provenanceJson,
        string profileSha256,
        bool completeRun,
        bool completeJob,
        int localTrackBase = 0,
        bool vehicleOnly = false,
        bool finalizeJob = false)
    {
        var source = VehicleSubclass.DetectorNativeSourcePrefix + profileSha256;
        TrackSpec[] specs = vehicleOnly
            ? [new(localTrackBase + 1, ObjectClass.Vehicle, "car", [ObservationType.Representative])]
            :
            [
                new(localTrackBase + 1, ObjectClass.Vehicle, "car",
                    [ObservationType.Representative, ObservationType.NearView, ObservationType.EarlyDiverse, ObservationType.LateDiverse]),
                new(localTrackBase + 2, ObjectClass.Vehicle, "truck", [ObservationType.Representative, ObservationType.EarlyDiverse]),
                new(localTrackBase + 3, ObjectClass.Vehicle, "bus", [ObservationType.Representative]),
                new(localTrackBase + 4, ObjectClass.Vehicle, "motorcycle", [ObservationType.Representative, ObservationType.LateDiverse]),
                // The vote abstained: vocabulary and source, no value.
                new(localTrackBase + 5, ObjectClass.Vehicle, null, [ObservationType.Representative]),
                new(localTrackBase + 6, ObjectClass.Person, null, [ObservationType.Representative, ObservationType.NearView]),
            ];

        var run = ProcessingRun.Create(video.VideoId, "phase1-detection-tracking-v1", "{}", CompletedAt.AddMinutes(-3));
        run.MarkRunning("worker-01", CompletedAt.AddMinutes(-2));
        var job = VisionJob.Create(run.Id, "phase1-detection-tracking", CompletedAt.AddMinutes(-3));
        job.Lease("worker-01", SHA256.HashData([1, 2, 3]), CompletedAt.AddMinutes(-2), TimeSpan.FromMinutes(30), 3);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        db.ProcessingRuns.Add(run);
        db.VisionJobs.Add(job);

        var seeded = new List<SeededTrack>();
        var tracks = new List<(Track Track, List<Observation> Observations)>();
        foreach (var spec in specs)
        {
            var isVehicle = spec.ObjectClass == ObjectClass.Vehicle;
            var track = Track.Create(
                run.Id,
                video.VideoId,
                spec.Number,
                spec.ObjectClass,
                startOffsetMs: 1_000L * (spec.Number % 10),
                endOffsetMs: 1_000L * (spec.Number % 10) + 8_000,
                video.RecordingStartUtc,
                detectionCount: 5 + spec.Number,
                meanConfidence: 0.70 + spec.Number % 10 * 0.01,
                maxConfidence: 0.95,
                createdAtUtc: CompletedAt,
                objectSubclass: isVehicle ? spec.Subclass : null,
                objectSubclassVocabulary: isVehicle ? VehicleSubclass.VocabularyV1 : null,
                objectSubclassSource: isVehicle ? source : null);

            var trajectoryBytes = Enumerable.Range(0, 64 + spec.Number).Select(i => (byte)((i * 3 + spec.Number) % 253)).ToArray();
            var trajectorySha = Sha256(trajectoryBytes);
            var trajectoryKey = $"evidence/{run.Id:D}/attempt-0001/trajectories/{spec.Number:D6}-{trajectorySha}.msgpack";
            Task14TestData.WriteEvidence(factory, trajectoryKey, trajectoryBytes);
            var trajectory = Artifact.Create(ArtifactType.TrackTrajectory, trajectoryKey, "application/msgpack", trajectoryBytes.Length, trajectorySha, createdAtUtc: CompletedAt);
            track.AttachTrajectoryArtifact(trajectory.Id);
            db.Artifacts.Add(trajectory);
            db.Tracks.Add(track);

            var observations = new List<Observation>();
            var keys = new List<string>();
            for (var rank = 0; rank < spec.Roles.Length; rank++)
            {
                var cropBytes = Enumerable.Range(0, 120 + rank * 7 + spec.Number)
                    .Select(i => (byte)((i * 11 + rank * 5 + spec.Number * 17) % 251))
                    .ToArray();
                var cropSha = Sha256(cropBytes);
                var cropKey = $"evidence/{run.Id:D}/attempt-0001/crops/{spec.Number:D6}-{rank}-{cropSha}.jpg";
                Task14TestData.WriteEvidence(factory, cropKey, cropBytes);
                var crop = Artifact.Create(ArtifactType.EvidenceCrop, cropKey, "image/jpeg", cropBytes.Length, cropSha, createdAtUtc: CompletedAt);
                var observation = Observation.Create(
                    track.Id,
                    spec.Roles[rank],
                    sourceFrameNumber: 25L * spec.Number + 10 * rank,
                    videoOffsetMs: 1_000L * (spec.Number % 10) + 400 * rank,
                    recordingStartUtc: video.RecordingStartUtc,
                    x: 0.1f + 0.01f * rank,
                    y: 0.2f,
                    width: 0.3f,
                    height: 0.25f + 0.05f * (spec.Number % 10),
                    confidence: 0.9 - 0.01 * rank,
                    qualityScore: 0.8 - 0.05 * rank,
                    evidenceRank: rank,
                    selectionScore: 0.75 - 0.05 * rank,
                    createdAtUtc: CompletedAt);
                observation.AttachEvidenceArtifact(crop.Id);
                db.Artifacts.Add(crop);
                observations.Add(observation);
                keys.Add(cropKey);
            }

            tracks.Add((track, observations));
            seeded.Add(new SeededTrack(track.Id, spec.Number, spec.ObjectClass, isVehicle ? spec.Subclass : null, observations.Select(x => x.Id).ToList(), keys));
        }

        await db.SaveChangesAsync();
        foreach (var (_, observations) in tracks)
            db.Observations.AddRange(observations);
        await db.SaveChangesAsync();
        foreach (var (track, observations) in tracks)
            track.AttachRepresentativeObservation(observations[0].Id);
        await db.SaveChangesAsync();

        if (!completeRun && finalizeJob)
        {
            // The finalizer owns the hand-off but has not published: job Finalizing, run Running.
            job.BeginFinalization("worker-01", true, job.AttemptCount, CompletedAt.AddMinutes(-1), new string('d', 64));
            await db.SaveChangesAsync();
        }

        if (completeRun)
        {
            await using var completion = await db.Database.BeginTransactionAsync();
            await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db, CancellationToken.None);
            var sequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, CancellationToken.None);
            run.MarkCompleted(
                framesProcessed: 900,
                tracksCreated: specs.Length,
                durationMs: 30_000,
                detectorName: "rtmdet-m",
                detectorVersion: "1",
                trackerName: "ByteTrack",
                trackerVersion: "2.6.0",
                runtimeProvenanceJson: provenanceJson,
                completedAtUtc: CompletedAt);
            run.AssignCompletionVisibilitySequence(sequence);
            if (completeJob)
                job.Complete("worker-01", true, CompletedAt.AddMinutes(-1));
            await db.SaveChangesAsync();
            await completion.CommitAsync();
        }

        return (run.Id, seeded);
    }

    public string CreateScratch(string prefix)
    {
        var path = Path.Combine(Path.GetTempPath(), $"{prefix}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(path);
        _scratch.Add(path);
        return path;
    }

    public static string Sha256(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));

    public static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "MAVI.sln")))
                return directory.FullName;
            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("MAVI repository root could not be located.");
    }

    public void Dispose()
    {
        Factory.Dispose();
        foreach (var path in _scratch)
        {
            try
            {
                if (Directory.Exists(path))
                    Directory.Delete(path, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }
}
