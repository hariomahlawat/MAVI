using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VideoAssetDatabaseConstraintTests(PostgresFixture fixture)
{
    [Fact]
    public async Task DatabaseRejectsRecordingEndInconsistentWithDuration()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var video = await PersistVideoAssetAsync(db);

        var exception = await Assert.ThrowsAsync<PostgresException>(() =>
            db.Database.ExecuteSqlInterpolatedAsync(
                $"UPDATE video_assets SET recording_end_utc = recording_end_utc + INTERVAL '1 second' WHERE id = {video.Id}"));

        Assert.Equal(PostgresErrorCodes.CheckViolation, exception.SqlState);
        Assert.Equal("ck_video_assets_recording_end", exception.ConstraintName);
    }

    [Fact]
    public async Task NormalVideoAssetPathPersistsAfterMigration()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();

        var video = await PersistVideoAssetAsync(db);

        Assert.NotNull(await db.VideoAssets.FindAsync(video.Id));
    }

    // Test data
    private static async Task<VideoAsset> PersistVideoAssetAsync(MaviDbContext db)
    {
        var camera = Camera.Create("CAM-DB-01", "Database Test Camera", "UTC");
        var artifact = Artifact.Create(
            ArtifactType.SourceVideo,
            $"source/CAM-DB-01/{Guid.CreateVersion7()}.mp4",
            "video/mp4",
            1,
            new string('a', 64));
        var video = VideoAsset.Create(
            camera.Id,
            artifact.Id,
            "constraint.mp4",
            new DateTimeOffset(2026, 9, 8, 12, 0, 0, TimeSpan.Zero),
            2_000,
            25,
            1,
            640,
            360,
            "h264",
            TimestampSource.Manual,
            1.0);

        db.AddRange(camera, artifact, video);
        await db.SaveChangesAsync();
        return video;
    }
}
