using Mavi.Application.Modules.SceneAnalytics.Configuration;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Mavi.Domain.Scene;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneConfigurationPersistenceTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 20, 6, 0, 0, TimeSpan.Zero);

    // Round trip
    [Fact]
    public async Task RevisionRoundTripsWithItsGeometryIntact()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        var repository = new SceneConfigurationRepository(db);

        var configuration = SceneConfiguration.Create(camera.Id, Now);
        var revision = configuration.SaveRevision(
            null,
            new SceneRevisionDraft(
                "Initial layout",
                null,
                null,
                [Zone("Gate", loiteringThresholdSeconds: 45)],
                [Line("Kerb")]),
            null,
            SceneRules.UnattributedDevelopmentActor,
            Now);
        await repository.AddAsync(configuration, default);
        await repository.AddRevisionAsync(revision, default);
        await repository.SaveChangesAsync(default);

        await using var reader = fixture.CreateDbContext();
        var stored = await new SceneConfigurationRepository(reader).GetRevisionAsync(revision.Id, default);

        Assert.NotNull(stored);
        Assert.Equal(1, stored.RevisionNumber);
        Assert.Equal("Initial layout", stored.Note);
        Assert.Equal(SceneRules.UnattributedDevelopmentActor, stored.CreatedBy);

        var zone = Assert.Single(stored.Zones);
        Assert.Equal(revision.Zones[0].ZoneId, zone.ZoneId);
        Assert.Equal("Gate", zone.Name);
        Assert.Equal(SceneZoneKind.General, zone.Kind);
        Assert.Equal(45, zone.LoiteringThresholdSeconds);
        Assert.Equal(revision.Zones[0].Vertices, zone.Vertices);

        var line = Assert.Single(stored.TripLines);
        Assert.Equal(revision.TripLines[0].LineId, line.LineId);
        Assert.Equal(revision.TripLines[0].A, line.A);
        Assert.Equal(revision.TripLines[0].B, line.B);
        Assert.Equal("inbound", line.AToBLabel);
    }

    [Fact]
    public async Task VerticesKeepTheirOrderAndPrecision()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        var vertices = new[]
        {
            new ScenePointDraft(0.123456, 0.2),
            new ScenePointDraft(0.9, 0.234567),
            new ScenePointDraft(0.4, 0.812345),
        };

        var revision = await SaveAsync(db, camera.Id, new SceneRevisionDraft(
            null, null, null, [new SceneZoneDraft(null, "Gate", null, true, vertices, null)], []));

        await using var reader = fixture.CreateDbContext();
        var stored = await new SceneConfigurationRepository(reader).GetRevisionAsync(revision.Id, default);

        Assert.Equal(
            [(0.123456, 0.2), (0.9, 0.234567), (0.4, 0.812345)],
            stored!.Zones[0].Vertices.Select(point => (point.X, point.Y)));
    }

    // History
    [Fact]
    public async Task EveryRevisionIsRetainedAndTheLatestIsActive()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);

        var first = await SaveAsync(db, camera.Id, Draft(Zone("Gate")));
        var second = await SaveAsync(db, camera.Id, Draft(Zone("Gate"), Zone("Yard", offset: 0.5)), expected: 1);
        var third = await SaveAsync(db, camera.Id, new SceneRevisionDraft(null, null, null, [], []), expected: 2);

        await using var reader = fixture.CreateDbContext();
        var repository = new SceneConfigurationRepository(reader);
        var configuration = await repository.GetByCameraAsync(camera.Id, default);
        var history = await repository.ListRevisionsAsync(configuration!.Id, default);

        Assert.Equal([1, 2, 3], history.Select(revision => revision.RevisionNumber));
        Assert.Equal(third.Id, configuration.ActiveRevisionId);
        Assert.Single(history[0].Zones);
        Assert.Equal(2, history[1].Zones.Count);
        Assert.Empty(history[2].Zones);
        Assert.False(history[2].AnalyticsEnabled);
        Assert.Equal(first.Id, history[0].Id);
        Assert.Equal(second.Id, history[1].Id);
    }

    [Fact]
    public async Task SavingAgainDoesNotTouchTheStoredEarlierRevision()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        var first = await SaveAsync(db, camera.Id, Draft(Zone("Gate")));
        var zoneId = first.Zones[0].ZoneId;

        await SaveAsync(
            db,
            camera.Id,
            Draft(new SceneZoneDraft(zoneId, "Renamed", "Restricted", false, WiderVertices(), 10)),
            expected: 1);

        await using var reader = fixture.CreateDbContext();
        var stored = await new SceneConfigurationRepository(reader).GetRevisionAsync(first.Id, default);

        Assert.Equal("Gate", stored!.Zones[0].Name);
        Assert.True(stored.Zones[0].Enabled);
        Assert.Equal(SceneZoneKind.General, stored.Zones[0].Kind);
        Assert.Null(stored.Zones[0].LoiteringThresholdSeconds);
    }

    // Constraints
    [Fact]
    public async Task ACameraMayHaveOnlyOneConfiguration()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        await SaveAsync(db, camera.Id, Draft(Zone("Gate")));

        await using var second = fixture.CreateDbContext();
        var duplicate = SceneConfiguration.Create(camera.Id, Now);
        var repository = new SceneConfigurationRepository(second);
        await repository.AddAsync(duplicate, default);
        var revision = duplicate.SaveRevision(
            null, Draft(Zone("Gate")), null, SceneRules.UnattributedDevelopmentActor, Now);
        await repository.AddRevisionAsync(revision, default);

        await Assert.ThrowsAsync<SceneConcurrentSaveException>(() => repository.SaveChangesAsync(default));
    }

    [Fact]
    public async Task ARevisionNumberIsUniqueWithinAConfiguration()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        await SaveAsync(db, camera.Id, Draft(Zone("Gate")));

        await using var second = fixture.CreateDbContext();
        var repository = new SceneConfigurationRepository(second);
        var configuration = await repository.GetByCameraAsync(camera.Id, default);

        // Two requests that both read revision 0 and both try to write revision 1.
        var clash = configuration!.SaveRevision(
            null, Draft(Zone("Gate")), null, SceneRules.UnattributedDevelopmentActor, Now);
        await repository.AddRevisionAsync(clash, default);

        await Assert.ThrowsAsync<SceneConcurrentSaveException>(() => repository.SaveChangesAsync(default));
    }

    [Fact]
    public async Task ActiveRevisionMustBelongToItsOwnConfiguration()
    {
        await using var db = await FreshDatabaseAsync();
        var first = await AddCameraAsync(db);
        var second = await AddCameraAsync(db, "CAM-0002");
        await SaveAsync(db, first.Id, Draft(Zone("Gate")));
        var foreign = await SaveAsync(db, second.Id, Draft(Zone("Gate")));

        // Point the first camera's configuration at the second camera's revision. The
        // deferred composite constraint refuses it when the transaction commits.
        var exception = await Assert.ThrowsAsync<PostgresException>(async () =>
        {
            await using var connection = new NpgsqlConnection(fixture.ConnectionString);
            await connection.OpenAsync();
            await using var command = new NpgsqlCommand(
                "UPDATE scene_configurations SET active_revision_id = @revision WHERE camera_id = @camera;",
                connection);
            command.Parameters.AddWithValue("revision", foreign.Id);
            command.Parameters.AddWithValue("camera", first.Id);
            await command.ExecuteNonQueryAsync();
        });

        Assert.Equal(PostgresErrorCodes.ForeignKeyViolation, exception.SqlState);
    }

    [Fact]
    public async Task ACameraWithASceneCannotBeDeleted()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        await SaveAsync(db, camera.Id, Draft(Zone("Gate")));

        var exception = await Assert.ThrowsAsync<PostgresException>(() =>
            ExecuteAsync("DELETE FROM cameras WHERE id = @id;", camera.Id));

        Assert.Equal(PostgresErrorCodes.ForeignKeyViolation, exception.SqlState);
    }

    [Fact]
    public async Task AConfigurationWithHistoryCannotBeDeleted()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        await SaveAsync(db, camera.Id, Draft(Zone("Gate")));

        var exception = await Assert.ThrowsAsync<PostgresException>(() =>
            ExecuteAsync("DELETE FROM scene_configurations WHERE camera_id = @id;", camera.Id));

        Assert.Equal(PostgresErrorCodes.ForeignKeyViolation, exception.SqlState);
    }

    [Fact]
    public async Task DeletingARevisionTakesItsGeometryWithIt()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        var first = await SaveAsync(db, camera.Id, Draft(Zone("Gate")));
        await SaveAsync(db, camera.Id, Draft(Zone("Gate")), expected: 1);

        await ExecuteAsync("DELETE FROM scene_configuration_revisions WHERE id = @id;", first.Id);

        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "SELECT count(*) FROM scene_zones WHERE revision_id = @id;", connection);
        command.Parameters.AddWithValue("id", first.Id);
        Assert.Equal(0L, await command.ExecuteScalarAsync());
    }

    [Fact]
    public async Task TheDatabaseRefusesAZoneWithTooFewVertices()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        var revision = await SaveAsync(db, camera.Id, Draft(Zone("Gate")));

        var exception = await Assert.ThrowsAsync<PostgresException>(() => ExecuteAsync(
            "UPDATE scene_zones SET vertices = '[[0.1,0.1],[0.2,0.2]]'::jsonb WHERE revision_id = @id;",
            revision.Id));

        Assert.Equal(PostgresErrorCodes.CheckViolation, exception.SqlState);
    }

    [Theory]
    [InlineData("[[1.4,0.1],[0.2,0.2],[0.3,0.3]]")]
    [InlineData("[[-0.5,0.1],[0.2,0.2],[0.3,0.3]]")]
    [InlineData("[[0.1,0.1],[0.2,2.0],[0.3,0.3]]")]
    [InlineData("[[\"0.1\",0.1],[0.2,0.2],[0.3,0.3]]")]
    [InlineData("[[0.1],[0.2,0.2],[0.3,0.3]]")]
    public async Task TheDatabaseRefusesAZoneVertexOutsideTheFrame(string vertices)
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        var revision = await SaveAsync(db, camera.Id, Draft(Zone("Gate")));

        var exception = await Assert.ThrowsAsync<PostgresException>(() => ExecuteAsync(
            $"UPDATE scene_zones SET vertices = '{vertices}'::jsonb WHERE revision_id = @id;",
            revision.Id));

        Assert.Equal(PostgresErrorCodes.CheckViolation, exception.SqlState);
    }

    [Fact]
    public async Task TheDatabaseAcceptsZoneVerticesAtTheEdgesOfTheFrame()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        var revision = await SaveAsync(db, camera.Id, Draft(Zone("Gate")));

        var updated = await ExecuteAsync(
            "UPDATE scene_zones SET vertices = '[[0,0],[1,0],[1,1]]'::jsonb WHERE revision_id = @id;",
            revision.Id);

        Assert.Equal(1, updated);
    }

    [Fact]
    public async Task TheDatabaseRefusesATripLineOutsideTheFrame()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        var revision = await SaveAsync(
            db, camera.Id, new SceneRevisionDraft(null, null, null, [], [Line("Kerb")]));

        var exception = await Assert.ThrowsAsync<PostgresException>(() =>
            ExecuteAsync("UPDATE trip_lines SET ax = 1.4 WHERE revision_id = @id;", revision.Id));

        Assert.Equal(PostgresErrorCodes.CheckViolation, exception.SqlState);
    }

    [Fact]
    public async Task TheDatabaseRefusesHalfAReferenceFrame()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        var revision = await SaveAsync(db, camera.Id, Draft(Zone("Gate")));

        var exception = await Assert.ThrowsAsync<PostgresException>(() => ExecuteAsync(
            "UPDATE scene_configuration_revisions SET reference_frame_offset_ms = 10 WHERE id = @id;",
            revision.Id));

        Assert.Equal(PostgresErrorCodes.CheckViolation, exception.SqlState);
    }

    [Fact]
    public async Task AReferenceFrameKeepsItsVideoAlive()
    {
        await using var db = await FreshDatabaseAsync();
        var camera = await AddCameraAsync(db);
        var video = await AddVideoAsync(db, camera.Id);
        await SaveAsync(
            db,
            camera.Id,
            new SceneRevisionDraft(null, video.Id, 1_000, [Zone("Gate")], []));

        var exception = await Assert.ThrowsAsync<PostgresException>(() =>
            ExecuteAsync("DELETE FROM video_assets WHERE id = @id;", video.Id));

        Assert.Equal(PostgresErrorCodes.ForeignKeyViolation, exception.SqlState);
    }

    // Test infrastructure
    private async Task<MaviDbContext> FreshDatabaseAsync()
    {
        await fixture.ResetDatabaseAsync();
        var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        return db;
    }

    private static async Task<Camera> AddCameraAsync(MaviDbContext db, string code = "CAM-0001")
    {
        var camera = Camera.Create(code, "Test", "UTC", Now);
        db.Cameras.Add(camera);
        await db.SaveChangesAsync();
        return camera;
    }

    private static async Task<VideoAsset> AddVideoAsync(MaviDbContext db, Guid cameraId)
    {
        var artifact = Artifact.Create(
            ArtifactType.SourceVideo,
            "media/source.mp4",
            "video/mp4",
            1_024,
            new string('a', 64),
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

    private static async Task<SceneConfigurationRevision> SaveAsync(
        MaviDbContext db,
        Guid cameraId,
        SceneRevisionDraft draft,
        int? expected = null)
    {
        var repository = new SceneConfigurationRepository(db);
        var configuration = await repository.GetByCameraAsync(cameraId, default);
        var isNew = configuration is null;
        configuration ??= SceneConfiguration.Create(cameraId, Now);
        var active = configuration.ActiveRevisionId is { } id
            ? await repository.GetRevisionAsync(id, default)
            : null;
        var revision = configuration.SaveRevision(
            active, draft, expected, SceneRules.UnattributedDevelopmentActor, Now);
        if (isNew)
        {
            await repository.AddAsync(configuration, default);
        }

        await repository.AddRevisionAsync(revision, default);
        await repository.SaveChangesAsync(default);
        return revision;
    }

    private async Task<int> ExecuteAsync(string sql, Guid id)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue("id", id);
        return await command.ExecuteNonQueryAsync();
    }

    private static SceneRevisionDraft Draft(params SceneZoneDraft[] zones) => new(null, null, null, zones, []);

    private static SceneZoneDraft Zone(
        string name,
        double offset = 0,
        int? loiteringThresholdSeconds = null) =>
        new(
            null,
            name,
            null,
            true,
            [
                new ScenePointDraft(0.1 + offset, 0.1),
                new ScenePointDraft(0.4 + offset, 0.1),
                new ScenePointDraft(0.4 + offset, 0.4),
                new ScenePointDraft(0.1 + offset, 0.4),
            ],
            loiteringThresholdSeconds);

    private static IReadOnlyList<ScenePointDraft> WiderVertices() =>
    [
        new ScenePointDraft(0.05, 0.05),
        new ScenePointDraft(0.45, 0.05),
        new ScenePointDraft(0.45, 0.45),
        new ScenePointDraft(0.05, 0.45),
    ];

    private static TripLineDraft Line(string name) => new(
        null,
        name,
        true,
        new ScenePointDraft(0.1, 0.5),
        new ScenePointDraft(0.9, 0.5),
        true,
        "inbound",
        "outbound");
}
