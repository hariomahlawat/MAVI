using System.Security.Cryptography;
using Mavi.Domain.Cameras;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

internal static class Task14TestData
{
    internal sealed record BaseVideo(
        Guid CameraId,
        Guid VideoId,
        Guid SourceArtifactId,
        DateTimeOffset RecordingStartUtc,
        string SourceStorageKey,
        byte[] SourceBytes);

    internal sealed record CompletedTrack(
        Guid ProcessingRunId,
        Guid TrackId,
        Guid ThumbnailArtifactId,
        Guid TrajectoryArtifactId,
        DateTimeOffset StartTimestampUtc);

    public static async Task<BaseVideo> SeedBaseVideoAsync(
        ApiTestFactory factory,
        string cameraCode = "CAM-T14",
        DateTimeOffset? recordingStartUtc = null)
    {
        var start = (recordingStartUtc ??
            new DateTimeOffset(2026, 9, 13, 6, 0, 0, TimeSpan.Zero)).ToUniversalTime();
        var camera = Camera.Create(cameraCode, "Task 14 Camera", "UTC", start.AddMinutes(-5));
        var cameraSalt = SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(cameraCode));
        var sourceBytes = Enumerable.Range(0, 512)
            .Select(index => (byte)((index + cameraSalt[index % cameraSalt.Length]) % 251))
            .ToArray();
        var sourceKey = $"source/{cameraCode.ToLowerInvariant()}/sample.mp4";
        var sourceSha = Sha256(sourceBytes);
        var source = Artifact.Create(
            ArtifactType.SourceVideo,
            sourceKey,
            "video/mp4",
            sourceBytes.Length,
            sourceSha,
            createdAtUtc: start.AddMinutes(-4));
        var video = VideoAsset.Create(
            Guid.CreateVersion7(),
            camera.Id,
            source.Id,
            "sample.mp4",
            start,
            durationMs: 60_000,
            frameRateNumerator: 25,
            frameRateDenominator: 1,
            width: 1920,
            height: 1080,
            codec: "h264",
            timestampSource: TimestampSource.Manual,
            timestampConfidence: 1.0,
            recordingTimeZoneId: "UTC",
            recordingUtcOffsetMinutes: 0,
            importedAtUtc: start.AddMinutes(-3));

        var physicalSource = Path.Combine(
            factory.MediaRoot,
            sourceKey.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(physicalSource)!);
        await File.WriteAllBytesAsync(physicalSource, sourceBytes);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        db.Cameras.Add(camera);
        db.Artifacts.Add(source);
        db.VideoAssets.Add(video);
        await db.SaveChangesAsync();

        return new BaseVideo(
            camera.Id,
            video.Id,
            source.Id,
            start,
            sourceKey,
            sourceBytes);
    }

    public static async Task<CompletedTrack> AddCompletedTrackAsync(
        ApiTestFactory factory,
        BaseVideo video,
        DateTimeOffset completedAtUtc,
        long startOffsetMs,
        ObjectClass objectClass = ObjectClass.Person,
        double meanConfidence = 0.80,
        int localTrackNumber = 1)
    {
        var run = ProcessingRun.Create(
            video.VideoId,
            "phase1-detection-tracking-v1",
            "{}",
            completedAtUtc.AddMinutes(-2));
        run.MarkRunning("worker-01", completedAtUtc.AddMinutes(-1));

        var track = Track.Create(
            run.Id,
            video.VideoId,
            localTrackNumber,
            objectClass,
            startOffsetMs,
            startOffsetMs + 2_000,
            video.RecordingStartUtc,
            detectionCount: 8,
            meanConfidence: meanConfidence,
            maxConfidence: Math.Min(1.0, meanConfidence + 0.10),
            createdAtUtc: completedAtUtc);

        var thumbnailBytes = Enumerable.Range(0, 160)
            .Select(index => (byte)((index + localTrackNumber) % 239))
            .ToArray();
        var trajectoryBytes = Enumerable.Range(0, 240)
            .Select(index => (byte)((index + localTrackNumber * 3) % 241))
            .ToArray();
        var thumbnailSha = Sha256(thumbnailBytes);
        var trajectorySha = Sha256(trajectoryBytes);
        var thumbnailKey =
            $"evidence/{run.Id:D}/attempt-0001/thumbnails/person-{localTrackNumber:D6}-{thumbnailSha}.jpg";
        var trajectoryKey =
            $"evidence/{run.Id:D}/attempt-0001/trajectories/person-{localTrackNumber:D6}-{trajectorySha}.msgpack";

        var thumbnail = Artifact.Create(
            ArtifactType.Thumbnail,
            thumbnailKey,
            "image/jpeg",
            thumbnailBytes.Length,
            thumbnailSha,
            createdAtUtc: completedAtUtc);
        var trajectory = Artifact.Create(
            ArtifactType.TrackTrajectory,
            trajectoryKey,
            "application/msgpack",
            trajectoryBytes.Length,
            trajectorySha,
            createdAtUtc: completedAtUtc);
        track.AttachTrajectoryArtifact(trajectory.Id);

        WriteEvidence(factory, thumbnailKey, thumbnailBytes);
        WriteEvidence(factory, trajectoryKey, trajectoryBytes);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        db.ProcessingRuns.Add(run);
        db.Artifacts.AddRange(thumbnail, trajectory);
        db.Tracks.Add(track);
        await db.SaveChangesAsync();

        var observation = Observation.Create(
            track.Id,
            ObservationType.Representative,
            sourceFrameNumber: 25,
            videoOffsetMs: startOffsetMs + 1_000,
            recordingStartUtc: video.RecordingStartUtc,
            x: 0.1f,
            y: 0.2f,
            width: 0.3f,
            height: 0.4f,
            confidence: Math.Min(1.0, meanConfidence + 0.05),
            qualityScore: 0.90,
            evidenceRank: 0,
            selectionScore: 0.90,
            createdAtUtc: completedAtUtc);
        observation.AttachEvidenceArtifact(thumbnail.Id);
        db.Observations.Add(observation);
        await db.SaveChangesAsync();

        track.AttachRepresentativeObservation(observation.Id);

        await using var completionTransaction =
            await db.Database.BeginTransactionAsync();
        await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(
            db,
            CancellationToken.None);
        var visibilitySequence =
            await ProcessingVisibilityBarrier.AllocateSequenceAsync(
                db,
                CancellationToken.None);
        run.MarkCompleted(
            framesProcessed: 100,
            tracksCreated: 1,
            durationMs: 2_000,
            completedAtUtc: completedAtUtc);
        run.AssignCompletionVisibilitySequence(visibilitySequence);
        await db.SaveChangesAsync();
        await completionTransaction.CommitAsync();

        return new CompletedTrack(
            run.Id,
            track.Id,
            thumbnail.Id,
            trajectory.Id,
            track.StartTimestampUtc);
    }

    /// <summary>What a seeded Track's <c>RepresentativeObservationId</c> should name.</summary>
    internal abstract record RepresentativePointer
    {
        private RepresentativePointer() { }

        /// <summary>This Track's rank-0 Observation, as the write path does.</summary>
        public sealed record RankZero : RepresentativePointer;

        /// <summary>No pointer at all.</summary>
        public sealed record None : RepresentativePointer;

        /// <summary>This Track's Observation at the given position of the seeded list.</summary>
        public sealed record Position(int Index) : RepresentativePointer;

        /// <summary>An Observation that is not this Track's.</summary>
        public sealed record External(Guid ObservationId) : RepresentativePointer;
    }

    internal sealed record SeededEvidence(
        Guid ProcessingRunId,
        Guid TrackId,
        IReadOnlyList<Guid> ObservationIds,
        IReadOnlyList<Guid> CropArtifactIds);

    /// <summary>
    /// A completed Track with exactly the given persisted Evidence Set: v3
    /// <c>EvidenceCrop</c> artifacts with real bytes, one per Observation, and the given
    /// pointer.
    /// </summary>
    /// <remarks>
    /// This goes through the Domain factories and the database's own constraints, not
    /// through completion validation. That lets a test persist the shapes the completion
    /// validator refuses but the schema admits (a rank gap, roles out of order, a pointer
    /// to the wrong Observation), so the read seam is exercised against genuinely
    /// malformed persisted state rather than a fake.
    /// </remarks>
    public static async Task<SeededEvidence> AddTrackWithEvidenceSetAsync(
        ApiTestFactory factory,
        BaseVideo video,
        DateTimeOffset completedAtUtc,
        IReadOnlyList<(ObservationType Role, int Rank)> observations,
        RepresentativePointer pointer,
        int localTrackNumber = 1)
    {
        var run = ProcessingRun.Create(
            video.VideoId,
            "phase1-detection-tracking-v1",
            "{}",
            completedAtUtc.AddMinutes(-2));
        run.MarkRunning("worker-01", completedAtUtc.AddMinutes(-1));
        var track = Track.Create(
            run.Id,
            video.VideoId,
            localTrackNumber,
            ObjectClass.Person,
            1_000,
            9_000,
            video.RecordingStartUtc,
            detectionCount: 8,
            meanConfidence: 0.80,
            maxConfidence: 0.95,
            createdAtUtc: completedAtUtc);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        db.ProcessingRuns.Add(run);
        db.Tracks.Add(track);
        await db.SaveChangesAsync();

        var observationIds = new List<Guid>();
        var cropIds = new List<Guid>();
        for (var index = 0; index < observations.Count; index++)
        {
            var (role, rank) = observations[index];
            var bytes = Enumerable.Range(0, 96 + index)
                .Select(value => (byte)((value * 7 + index + localTrackNumber) % 251))
                .ToArray();
            var sha = Sha256(bytes);
            var key = $"evidence/{run.Id:D}/attempt-0001/crops/person-{localTrackNumber:D6}-{index}-{sha}.jpg";
            WriteEvidence(factory, key, bytes);
            var crop = Artifact.Create(
                ArtifactType.EvidenceCrop,
                key,
                "image/jpeg",
                bytes.Length,
                sha,
                createdAtUtc: completedAtUtc);
            var observation = Observation.Create(
                track.Id,
                role,
                sourceFrameNumber: 30 + index * 10,
                videoOffsetMs: 1_200 + index * 1_000,
                recordingStartUtc: video.RecordingStartUtc,
                x: 0.1f + index * 0.01f,
                y: 0.2f,
                width: 0.3f,
                height: 0.4f,
                confidence: 0.90 - index * 0.01,
                qualityScore: 0.80 - index * 0.05,
                evidenceRank: rank,
                selectionScore: 0.70 - index * 0.05,
                createdAtUtc: completedAtUtc);
            observation.AttachEvidenceArtifact(crop.Id);
            db.Artifacts.Add(crop);
            db.Observations.Add(observation);
            observationIds.Add(observation.Id);
            cropIds.Add(crop.Id);
        }

        await db.SaveChangesAsync();

        switch (pointer)
        {
            case RepresentativePointer.RankZero:
                var rankZero = observations.Select((spec, index) => (spec, index)).Single(x => x.spec.Rank == 0).index;
                track.AttachRepresentativeObservation(observationIds[rankZero]);
                break;
            case RepresentativePointer.Position position:
                track.AttachRepresentativeObservation(observationIds[position.Index]);
                break;
            case RepresentativePointer.External external:
                track.AttachRepresentativeObservation(external.ObservationId);
                break;
            case RepresentativePointer.None:
                break;
        }

        await using var completionTransaction = await db.Database.BeginTransactionAsync();
        await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db, CancellationToken.None);
        var visibilitySequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, CancellationToken.None);
        run.MarkCompleted(
            framesProcessed: 300,
            tracksCreated: 1,
            durationMs: 12_000,
            completedAtUtc: completedAtUtc);
        run.AssignCompletionVisibilitySequence(visibilitySequence);
        await db.SaveChangesAsync();
        await completionTransaction.CommitAsync();

        return new SeededEvidence(run.Id, track.Id, observationIds, cropIds);
    }

    public static async Task<Guid> AddFailedRunAsync(
        ApiTestFactory factory,
        BaseVideo video,
        DateTimeOffset failedAtUtc)
    {
        var run = ProcessingRun.Create(
            video.VideoId,
            "phase1-detection-tracking-v1",
            "{}",
            failedAtUtc.AddMinutes(-2));
        run.MarkRunning("worker-02", failedAtUtc.AddMinutes(-1));
        run.MarkFailed("test_failure", null, failedAtUtc);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        db.ProcessingRuns.Add(run);
        await db.SaveChangesAsync();
        return run.Id;
    }

    public static void WriteEvidence(
        ApiTestFactory factory,
        string storageKey,
        byte[] bytes)
    {
        const string prefix = "evidence/";
        if (!storageKey.StartsWith(prefix, StringComparison.Ordinal))
            throw new ArgumentException("Expected accepted evidence key.", nameof(storageKey));

        var relative = storageKey[prefix.Length..]
            .Replace('/', Path.DirectorySeparatorChar);
        var path = Path.Combine(factory.EvidenceRoot, relative);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllBytes(path, bytes);
    }

    private static string Sha256(byte[] bytes) =>
        Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
}
