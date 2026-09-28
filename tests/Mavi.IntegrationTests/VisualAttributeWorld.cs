using System.Security.Cryptography;
using Mavi.Domain.Cameras;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

internal sealed record SeededObservation(
    Guid ObservationId,
    Guid ArtifactId,
    string StorageKey,
    byte[] Bytes,
    string Sha256,
    ObservationType Role,
    int Rank);

internal sealed record SeededTrack(Guid TrackId, ObjectClass ObjectClass, IReadOnlyList<SeededObservation> Observations);

internal sealed record SeededRun(Guid RunId, DateTimeOffset CompletedAtUtc, IReadOnlyList<SeededTrack> Tracks)
{
    public SeededTrack Track(int index) => Tracks[index];
}

/// <summary>
/// A migrated database with completed, visible ProcessingRuns whose Tracks carry accepted
/// EvidenceCrop Observations sealed into a real evidence root (S2b test world).
/// </summary>
internal sealed class VisualAttributeWorld : IDisposable
{
    private static readonly ObservationType[] Roles =
        [ObservationType.Representative, ObservationType.NearView, ObservationType.EarlyDiverse, ObservationType.LateDiverse];

    private VisualAttributeWorld() { }

    public required PostgresFixture Fixture { get; init; }
    public required MutableTimeProvider Clock { get; init; }
    public required string MediaRoot { get; init; }
    public required string EvidenceRoot { get; init; }
    public Guid CameraId { get; private set; }

    public static async Task<VisualAttributeWorld> CreateAsync(PostgresFixture fixture, DateTimeOffset nowUtc)
    {
        await fixture.ResetDatabaseAsync();
        await using (var db = fixture.CreateDbContext())
            await db.Database.MigrateAsync();

        var world = new VisualAttributeWorld
        {
            Fixture = fixture,
            Clock = new MutableTimeProvider(nowUtc),
            MediaRoot = CreateRoot("media"),
            EvidenceRoot = CreateRoot("evidence"),
        };
        var camera = Camera.Create("CAM-VA-01", "Visual attribute test camera", "UTC");
        await using (var db = fixture.CreateDbContext())
        {
            db.Cameras.Add(camera);
            await db.SaveChangesAsync();
        }

        world.CameraId = camera.Id;
        return world;
    }

    public MaviDbContext Read() => Fixture.CreateDbContext();

    /// <summary>
    /// A completed run with <paramref name="persons"/> person and <paramref name="vehicles"/>
    /// vehicle Tracks, each with <paramref name="observationsPerTrack"/> accepted crops.
    /// </summary>
    public async Task<SeededRun> SeedRunAsync(
        int persons,
        int vehicles,
        int observationsPerTrack = 1,
        bool visible = true,
        bool writeFiles = true,
        DateTimeOffset? completedAtUtc = null)
    {
        ArgumentOutOfRangeException.ThrowIfGreaterThan(observationsPerTrack, 4);
        var now = Clock.GetUtcNow();
        var completedAt = completedAtUtc ?? now.AddMinutes(-1);
        var source = Artifact.Create(ArtifactType.SourceVideo, $"source/CAM-VA-01/{Guid.CreateVersion7()}.mp4", "video/mp4", 1,
            Convert.ToHexStringLower(SHA256.HashData(Guid.NewGuid().ToByteArray())));
        var video = VideoAsset.Create(CameraId, source.Id, "attributes.mp4", now.AddHours(-1), 60_000, 25, 1, 640, 360, "h264",
            TimestampSource.Manual, 1.0);
        var run = ProcessingRun.Create(video.Id, "phase1-detection-tracking-v1", "{}", completedAt.AddMinutes(-5));
        run.MarkRunning("vision-01", completedAt.AddMinutes(-4));
        run.MarkCompleted(100, persons + vehicles, 1_000, completedAt);

        var tracks = new List<SeededTrack>();
        var entities = new List<object> { source, video, run };
        var number = 0;
        foreach (var objectClass in Enumerable.Repeat(ObjectClass.Person, persons).Concat(Enumerable.Repeat(ObjectClass.Vehicle, vehicles)))
        {
            number++;
            var track = Track.Create(run.Id, video.Id, number, objectClass, 0, 4_000, now.AddHours(-1), 4, 0.8, 0.9, completedAt);
            entities.Add(track);
            var observations = new List<SeededObservation>();
            for (var rank = 0; rank < observationsPerTrack; rank++)
            {
                var bytes = FakeJpeg(track.Id, rank);
                var sha256 = Convert.ToHexStringLower(SHA256.HashData(bytes));
                var storageKey = $"evidence/{run.Id:D}/attempt-0001/crops/{track.Id:N}-{rank}-{sha256}.jpg";
                var artifact = Artifact.Create(ArtifactType.EvidenceCrop, storageKey, "image/jpeg", bytes.Length, sha256);
                var observation = Observation.Create(track.Id, Roles[rank], rank * 10, rank * 400, now.AddHours(-1),
                    0.1f, 0.1f, 0.2f, 0.2f, 0.8, 0.7, rank, 0.7);
                observation.AttachEvidenceArtifact(artifact.Id);
                entities.Add(artifact);
                entities.Add(observation);
                observations.Add(new SeededObservation(observation.Id, artifact.Id, storageKey, bytes, sha256, Roles[rank], rank));
                if (writeFiles)
                    await WriteEvidenceAsync(storageKey, bytes);
            }

            tracks.Add(new SeededTrack(track.Id, objectClass, observations));
        }

        await using (var db = Read())
        {
            db.AddRange(entities);
            await db.SaveChangesAsync();
            if (visible)
            {
                var sequence = await NextSequenceAsync(db);
                await db.Database.ExecuteSqlInterpolatedAsync(
                    $"UPDATE processing_runs SET visibility_sequence = {sequence} WHERE id = {run.Id}");
            }
        }

        return new SeededRun(run.Id, completedAt, tracks);
    }

    public async Task WriteEvidenceAsync(string storageKey, byte[] bytes)
    {
        var path = EvidencePath(storageKey);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await File.WriteAllBytesAsync(path, bytes);
    }

    public string EvidencePath(string storageKey) =>
        Path.Combine(EvidenceRoot, storageKey["evidence/".Length..].Replace('/', Path.DirectorySeparatorChar));

    /// <summary>A structurally valid JPEG envelope with deterministic, Track-specific content.</summary>
    public static byte[] FakeJpeg(Guid trackId, int rank)
    {
        var body = SHA256.HashData([.. trackId.ToByteArray(), (byte)rank]);
        return [0xFF, 0xD8, 0xFF, 0xE0, .. body, .. body, 0xFF, 0xD9];
    }

    private static async Task<long> NextSequenceAsync(MaviDbContext db)
    {
        var connection = db.Database.GetDbConnection();
        if (connection.State != System.Data.ConnectionState.Open) await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT nextval('processing_visibility_sequence')";
        return Convert.ToInt64(await command.ExecuteScalarAsync(), System.Globalization.CultureInfo.InvariantCulture);
    }

    private static string CreateRoot(string name)
    {
        var path = Path.Combine(Path.GetTempPath(), $"mavi-va-{name}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(path);
        return path;
    }

    public void Dispose()
    {
        foreach (var root in new[] { MediaRoot, EvidenceRoot })
        {
            if (!Directory.Exists(root)) continue;
            foreach (var file in Directory.GetFiles(root, "*", SearchOption.AllDirectories))
                File.SetAttributes(file, FileAttributes.Normal);
            Directory.Delete(root, recursive: true);
        }
    }
}
