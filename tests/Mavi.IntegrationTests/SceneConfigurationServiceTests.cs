using Mavi.Application.Modules.Cameras;
using Mavi.Application.Modules.SceneAnalytics.Configuration;
using Mavi.Domain.Cameras;
using Mavi.Domain.Common;
using Mavi.Domain.Media;
using Mavi.Domain.Scene;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// The reference-frame and camera-state rules, which need a real camera and a real
/// video asset to exercise and so cannot be reached from the pure domain tests.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneConfigurationServiceTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 20, 6, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task ReferenceFrameOnThisCamerasVideoIsAccepted()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db, "CAM-R001");
        var video = await AddVideoAsync(db, camera.Id);

        var revision = await Service(db).SaveAsync(
            new SaveSceneCommand(camera.Id, null, Draft(video.Id, 30_000)),
            default);

        Assert.Equal(video.Id, revision!.ReferenceFrameVideoAssetId);
        Assert.Equal(30_000, revision.ReferenceFrameOffsetMs);
    }

    [Fact]
    public async Task ReferenceFrameFromAnotherCamerasVideoIsRejected()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db, "CAM-R002");
        var other = await AddCameraAsync(db, "CAM-R003");
        var video = await AddVideoAsync(db, other.Id);

        var exception = await Assert.ThrowsAsync<DomainValidationException>(() =>
            Service(db).SaveAsync(new SaveSceneCommand(camera.Id, null, Draft(video.Id, 1_000)), default));

        Assert.Equal(SceneErrorCodes.ReferenceFrameCameraMismatch, exception.Code);
    }

    [Fact]
    public async Task ReferenceFrameOffsetBeyondTheVideoIsRejected()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db, "CAM-R004");
        var video = await AddVideoAsync(db, camera.Id);

        var exception = await Assert.ThrowsAsync<DomainValidationException>(() =>
            Service(db).SaveAsync(
                new SaveSceneCommand(camera.Id, null, Draft(video.Id, video.DurationMs + 1)),
                default));

        Assert.Equal(SceneErrorCodes.ReferenceFrameOffsetInvalid, exception.Code);
    }

    [Fact]
    public async Task ReferenceFrameOffsetAtTheEndOfTheVideoIsAccepted()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db, "CAM-R005");
        var video = await AddVideoAsync(db, camera.Id);

        var revision = await Service(db).SaveAsync(
            new SaveSceneCommand(camera.Id, null, Draft(video.Id, video.DurationMs)),
            default);

        Assert.Equal(video.DurationMs, revision!.ReferenceFrameOffsetMs);
    }

    [Fact]
    public async Task InactiveCameraRefusesSceneChanges()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db, "CAM-R006");
        await SetInactiveAsync(camera.Id);

        var exception = await Assert.ThrowsAsync<DomainValidationException>(() =>
            Service(db).SaveAsync(new SaveSceneCommand(camera.Id, null, Draft(null, null)), default));

        Assert.Equal(SceneErrorCodes.CameraInactive, exception.Code);
    }

    [Fact]
    public async Task ReadingAMissingCamerasSceneReturnsNothing()
    {
        await using var db = await FreshDatabaseAsync();

        Assert.Null(await Service(db).GetAsync(Guid.CreateVersion7(), default));
    }

    [Fact]
    public async Task SavingForAMissingCameraReturnsNothing()
    {
        await using var db = await FreshDatabaseAsync();

        Assert.Null(await Service(db).SaveAsync(
            new SaveSceneCommand(Guid.CreateVersion7(), null, Draft(null, null)),
            default));
    }

    // Test infrastructure
    private static SceneConfigurationService Service(MaviDbContext db) => new(
        new SceneConfigurationRepository(db),
        new CameraRepository(db),
        new VideoCatalog(db),
        TimeProvider.System);

    private async Task<MaviDbContext> FreshDatabaseAsync()
    {
        await fixture.ResetDatabaseAsync();
        var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        return db;
    }

    private async Task SetInactiveAsync(Guid cameraId)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "UPDATE cameras SET is_active = false WHERE id = @id;", connection);
        command.Parameters.AddWithValue("id", cameraId);
        await command.ExecuteNonQueryAsync();
    }

    private static async Task<Camera> AddCameraAsync(MaviDbContext db, string code)
    {
        var camera = Camera.Create(code, code, "UTC", Now);
        db.Cameras.Add(camera);
        await db.SaveChangesAsync();
        return camera;
    }

    private static async Task<VideoAsset> AddVideoAsync(MaviDbContext db, Guid cameraId)
    {
        var artifact = Artifact.Create(
            ArtifactType.SourceVideo,
            $"media/{Guid.CreateVersion7():N}.mp4",
            "video/mp4",
            1_024,
            Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(Guid.NewGuid().ToByteArray())),
            createdAtUtc: Now);
        var video = VideoAsset.Create(
            cameraId,
            artifact.Id,
            "source.mp4",
            Now,
            60_000,
            25,
            1,
            1_920,
            1_080,
            "h264",
            TimestampSource.FilenamePattern,
            1,
            importedAtUtc: Now);
        db.Artifacts.Add(artifact);
        db.VideoAssets.Add(video);
        await db.SaveChangesAsync();
        return video;
    }

    private static SceneRevisionDraft Draft(Guid? videoAssetId, long? offsetMs) => new(
        null,
        videoAssetId,
        offsetMs,
        [
            new SceneZoneDraft(
                null,
                "Gate",
                null,
                true,
                [
                    new ScenePointDraft(0.1, 0.1),
                    new ScenePointDraft(0.4, 0.1),
                    new ScenePointDraft(0.4, 0.4),
                    new ScenePointDraft(0.1, 0.4),
                ],
                null),
        ],
        []);
}
