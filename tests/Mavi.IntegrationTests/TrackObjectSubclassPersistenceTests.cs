using Mavi.Domain.Cameras;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// Stage 3 (ADR-016): <c>AddTrackObjectSubclass</c>. The four subclass states persist,
/// every other combination is refused by the database itself, and the migration
/// reverses cleanly.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class TrackObjectSubclassPersistenceTests(PostgresFixture fixture)
{
    private const string BeforeSubclass = "20260928035552_AddVisualAttributeLifecycle";
    private const string Source = "detector-native:4444444444444444444444444444444444444444444444444444444444444444";

    [Fact]
    public async Task TheFourSubclassStatesRoundTrip()
    {
        var ids = await SeedAsync();
        await using var db = fixture.CreateDbContext();
        var tracks = await db.Set<Track>().AsNoTracking().ToDictionaryAsync(track => track.Id);

        AssertState(tracks[ids.Person], null, null, null);
        AssertState(tracks[ids.Historical], null, null, null);
        AssertState(tracks[ids.Abstained], null, VehicleSubclass.VocabularyV1, Source);
        AssertState(tracks[ids.Resolved], "truck", VehicleSubclass.VocabularyV1, Source);
    }

    [Theory]
    [InlineData("person", "UPDATE tracks SET object_subclass = 'car', object_subclass_vocabulary = 'mavi-vehicle-subclass-v1', object_subclass_source = 'detector-native:x' WHERE id = $1", "ck_tracks_object_subclass_state")]
    [InlineData("person", "UPDATE tracks SET object_subclass_vocabulary = 'mavi-vehicle-subclass-v1', object_subclass_source = 'detector-native:x' WHERE id = $1", "ck_tracks_object_subclass_state")]
    [InlineData("resolved", "UPDATE tracks SET object_subclass_vocabulary = NULL WHERE id = $1", "ck_tracks_object_subclass_state")]
    [InlineData("resolved", "UPDATE tracks SET object_subclass_source = NULL WHERE id = $1", "ck_tracks_object_subclass_state")]
    [InlineData("historical", "UPDATE tracks SET object_subclass = 'car' WHERE id = $1", "ck_tracks_object_subclass_state")]
    [InlineData("resolved", "UPDATE tracks SET object_subclass = 'bicycle' WHERE id = $1", "ck_tracks_object_subclass_value")]
    [InlineData("resolved", "UPDATE tracks SET object_subclass_vocabulary = 'mavi-vehicle-subclass-v2' WHERE id = $1", "ck_tracks_object_subclass_value")]
    [InlineData("abstained", "UPDATE tracks SET object_subclass_vocabulary = 'anything' WHERE id = $1", "ck_tracks_object_subclass_identity")]
    [InlineData("abstained", "UPDATE tracks SET object_subclass_source = 'classifier:x' WHERE id = $1", "ck_tracks_object_subclass_identity")]
    [InlineData("resolved", "UPDATE tracks SET object_subclass_source = 'detector-native:4444' WHERE id = $1", "ck_tracks_object_subclass_identity")]
    public async Task EveryOtherCombinationIsRefusedByTheDatabase(string row, string sql, string constraint)
    {
        var ids = await SeedAsync();
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue(row switch
        {
            "person" => ids.Person,
            "historical" => ids.Historical,
            "abstained" => ids.Abstained,
            "resolved" => ids.Resolved,
            _ => throw new ArgumentOutOfRangeException(nameof(row)),
        });

        var error = await Assert.ThrowsAsync<PostgresException>(() => command.ExecuteNonQueryAsync());
        Assert.Equal(constraint, error.ConstraintName);
    }

    [Fact]
    public async Task TheMigrationAddsTheColumnsAndReverses()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        var migrator = db.GetService<IMigrator>();
        await migrator.MigrateAsync(BeforeSubclass);
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        Assert.False(await ColumnExistsAsync(connection, "object_subclass"));

        await db.Database.MigrateAsync();
        foreach (var column in new[] { "object_subclass", "object_subclass_vocabulary", "object_subclass_source" })
            Assert.True(await ColumnExistsAsync(connection, column), column);

        await migrator.MigrateAsync(BeforeSubclass);
        foreach (var column in new[] { "object_subclass", "object_subclass_vocabulary", "object_subclass_source" })
            Assert.False(await ColumnExistsAsync(connection, column), column);
        await db.Database.MigrateAsync();
    }

    private static void AssertState(Track track, string? subclass, string? vocabulary, string? source)
    {
        Assert.Equal(subclass, track.ObjectSubclass);
        Assert.Equal(vocabulary, track.ObjectSubclassVocabulary);
        Assert.Equal(source, track.ObjectSubclassSource);
    }

    private static async Task<bool> ColumnExistsAsync(NpgsqlConnection connection, string column)
    {
        await using var command = new NpgsqlCommand(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tracks' AND column_name = $1)", connection);
        command.Parameters.AddWithValue(column);
        return (bool)(await command.ExecuteScalarAsync())!;
    }

    private sealed record Ids(Guid Person, Guid Historical, Guid Abstained, Guid Resolved);

    private async Task<Ids> SeedAsync()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var start = new DateTimeOffset(2026, 10, 2, 6, 0, 0, TimeSpan.Zero);
        var camera = Camera.Create("CAM-SUB", "Subclass Camera", "UTC", start.AddMinutes(-5));
        var sourceVideo = Artifact.Create(ArtifactType.SourceVideo, "source/sub.mp4", "video/mp4", 1, new string('a', 64),
            createdAtUtc: start.AddMinutes(-4));
        var video = VideoAsset.Create(Guid.CreateVersion7(), camera.Id, sourceVideo.Id, "sub.mp4", start, durationMs: 60_000,
            frameRateNumerator: 25, frameRateDenominator: 1, width: 1920, height: 1080, codec: "h264",
            timestampSource: TimestampSource.Manual, timestampConfidence: 1.0, recordingTimeZoneId: "UTC",
            recordingUtcOffsetMinutes: 0, importedAtUtc: start.AddMinutes(-3));
        var run = ProcessingRun.Create(video.Id, "phase1-detection-tracking-v1", "{}", start);

        Track Make(int number, ObjectClass objectClass, string? subclass, string? vocabulary, string? source) =>
            Track.Create(run.Id, video.Id, number, objectClass, 0, 2_000, start, detectionCount: 8,
                meanConfidence: 0.8, maxConfidence: 0.9, createdAtUtc: start,
                objectSubclass: subclass, objectSubclassVocabulary: vocabulary, objectSubclassSource: source);

        var person = Make(1, ObjectClass.Person, null, null, null);
        var historical = Make(2, ObjectClass.Vehicle, null, null, null);
        var abstained = Make(3, ObjectClass.Vehicle, null, VehicleSubclass.VocabularyV1, Source);
        var resolved = Make(4, ObjectClass.Vehicle, "truck", VehicleSubclass.VocabularyV1, Source);
        db.AddRange(camera, sourceVideo, video, run, person, historical, abstained, resolved);
        await db.SaveChangesAsync();
        return new Ids(person.Id, historical.Id, abstained.Id, resolved.Id);
    }
}
