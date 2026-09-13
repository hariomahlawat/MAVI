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
        var sourceBytes = Enumerable.Range(0, 512).Select(index => (byte)(index % 251)).ToArray();
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
            TimestampSource.Manual,
            1.0,
            "UTC",
            0,
            start.AddMinutes(-3));

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
            meanConfidence,
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
            video.RecordingStartUtc,
            x: 0.1f,
            y: 0.2f,
            width: 0.3f,
            height: 0.4f,
            confidence: Math.Min(1.0, meanConfidence + 0.05),
            qualityScore: 0.90,
            createdAtUtc: completedAtUtc);
        observation.AttachThumbnailArtifact(thumbnail.Id);
        db.Observations.Add(observation);
        await db.SaveChangesAsync();

        track.AttachRepresentativeObservation(observation.Id);
        run.MarkCompleted(
            framesProcessed: 100,
            tracksCreated: 1,
            durationMs: 2_000,
            completedAtUtc);
        await db.SaveChangesAsync();

        return new CompletedTrack(
            run.Id,
            track.Id,
            thumbnail.Id,
            trajectory.Id,
            track.StartTimestampUtc);
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
