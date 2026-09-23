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
/// S1.2a: <c>AddTrackEvidenceSet</c> backfill, legacy-type guard, preceding-binary
/// insert compatibility (deviation D1), constraints and the restrictive crop FK.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class TrackEvidenceSetMigrationTests(PostgresFixture fixture)
{
    private const string BeforeEvidenceSet = "20260921004943_AddSceneAnalytics";
    private const string EvidenceSet = "20260923160000_AddTrackEvidenceSet";

    [Fact]
    public void ModelHasNoChangesPendingAgainstTheSnapshot()
    {
        // The snapshot is maintained by hand; this is its drift guard.
        using var db = fixture.CreateDbContext();
        Assert.False(db.Database.HasPendingModelChanges());
    }

    [Fact]
    public async Task HistoricalRepresentativesBackfillToRankZeroWithQualityAsSelectionScore()
    {
        var seed = await SeedAtPrecedingSchemaAsync();
        await using var connection = await OpenAsync();
        await ExecuteAsync(connection, "UPDATE observations SET quality_score = 0.61 WHERE id = $1", seed.ObservationId);

        await using var db = fixture.CreateDbContext();
        await db.GetService<IMigrator>().MigrateAsync(EvidenceSet);

        await using var command = new NpgsqlCommand(
            "SELECT observation_type, evidence_rank, selection_score, thumbnail_artifact_id FROM observations WHERE id = $1", connection);
        command.Parameters.AddWithValue(seed.ObservationId);
        await using var reader = await command.ExecuteReaderAsync();
        Assert.True(await reader.ReadAsync());
        Assert.Equal("Representative", reader.GetString(0));
        Assert.Equal(0, reader.GetInt32(1));
        Assert.Equal(0.61, reader.GetDouble(2), 12);
        Assert.Equal(seed.CropArtifactId, reader.GetGuid(3));
    }

    [Theory]
    [InlineData("TrackStart")]
    [InlineData("BestQuality")]
    [InlineData("TrackEnd")]
    public async Task MigrationRefusesARetiredLegacyObservationType(string legacyType)
    {
        var seed = await SeedAtPrecedingSchemaAsync();
        await using var connection = await OpenAsync();
        await ExecuteAsync(connection, $"UPDATE observations SET observation_type = '{legacyType}' WHERE id = $1", seed.ObservationId);

        await using var db = fixture.CreateDbContext();
        var exception = await Assert.ThrowsAsync<PostgresException>(() => db.GetService<IMigrator>().MigrateAsync(EvidenceSet));

        Assert.Contains("observations_legacy_type_present", exception.MessageText, StringComparison.Ordinal);
        Assert.DoesNotContain(EvidenceSet, await db.Database.GetAppliedMigrationsAsync());
        Assert.False(await ColumnExistsAsync(connection, "evidence_rank"));
    }

    [Fact]
    public async Task PrecedingBinaryInsertOmittingEvidenceColumnsStillSucceeds()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var seed = await SeedAsync(db, withObservation: false);
        await using var connection = await OpenAsync();

        // The exact column list a completion 2.0 binary writes (no evidence_rank, no selection_score).
        var observationId = Guid.CreateVersion7();
        await using (var insert = new NpgsqlCommand("""
            INSERT INTO observations(id,track_id,observation_type,source_frame_number,video_offset_ms,timestamp_utc,
                bounding_box_x,bounding_box_y,bounding_box_width,bounding_box_height,confidence,quality_score,
                thumbnail_artifact_id,created_at_utc)
            VALUES ($1,$2,'Representative',25,1000,$3,0.1,0.2,0.3,0.4,0.85,0.72,$4,$3)
            """, connection))
        {
            insert.Parameters.AddWithValue(observationId);
            insert.Parameters.AddWithValue(seed.TrackId);
            insert.Parameters.AddWithValue(new DateTimeOffset(2026, 9, 23, 6, 0, 1, TimeSpan.Zero));
            insert.Parameters.AddWithValue(seed.CropArtifactId);
            Assert.Equal(1, await insert.ExecuteNonQueryAsync());
        }

        await using var command = new NpgsqlCommand("SELECT evidence_rank, selection_score FROM observations WHERE id = $1", connection);
        command.Parameters.AddWithValue(observationId);
        await using var reader = await command.ExecuteReaderAsync();
        Assert.True(await reader.ReadAsync());
        Assert.Equal(0, reader.GetInt32(0));
        Assert.Equal(0.72, reader.GetDouble(1), 12);
    }

    [Fact]
    public async Task ExplicitSelectionScoreIsNeverOverriddenByTheCompatibilityTrigger()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var seed = await SeedAsync(db, withObservation: true, qualityScore: 0.9, selectionScore: 0.4);

        await using var connection = await OpenAsync();
        await using var command = new NpgsqlCommand("SELECT selection_score FROM observations WHERE id = $1", connection);
        command.Parameters.AddWithValue(seed.ObservationId);
        Assert.Equal(0.4, (double)(await command.ExecuteScalarAsync())!, 12);
    }

    [Fact]
    public async Task EvidenceSetConstraintsIndexesAndRestrictiveCropForeignKeyExist()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        await using var connection = await OpenAsync();

        await using (var constraints = new NpgsqlCommand("""
            SELECT count(*) FROM pg_constraint
            WHERE conname IN ('ck_observations_type','ck_observations_rank','ck_observations_role_rank','ck_observations_selection_score');
            """, connection))
            Assert.Equal(4L, await constraints.ExecuteScalarAsync());

        foreach (var index in new[] { "ux_observations_track_rank", "ux_observations_track_role", "ux_observations_track_frame" })
        {
            await using var command = new NpgsqlCommand("SELECT indexdef FROM pg_indexes WHERE indexname = $1", connection);
            command.Parameters.AddWithValue(index);
            var definition = Assert.IsType<string>(await command.ExecuteScalarAsync());
            Assert.Contains("UNIQUE", definition, StringComparison.OrdinalIgnoreCase);
        }

        await using (var fk = new NpgsqlCommand(
            "SELECT confdeltype FROM pg_constraint WHERE conname = 'FK_observations_artifacts_thumbnail_artifact_id'", connection))
            Assert.Equal('r', (char)(await fk.ExecuteScalarAsync())!);
    }

    [Fact]
    public async Task DatabaseRejectsRoleRankMismatchDuplicateFrameAndArtifactDeletion()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var seed = await SeedAsync(db, withObservation: true);
        await using var connection = await OpenAsync();

        var mismatch = await Assert.ThrowsAsync<PostgresException>(() => InsertRawAsync(connection, seed, "NearView", rank: 0, frame: 40));
        Assert.Equal(PostgresErrorCodes.CheckViolation, mismatch.SqlState);
        Assert.Equal("ck_observations_role_rank", mismatch.ConstraintName);

        var legacy = await Assert.ThrowsAsync<PostgresException>(() => InsertRawAsync(connection, seed, "BestQuality", rank: 1, frame: 41));
        Assert.Equal("ck_observations_type", legacy.ConstraintName);

        var frame = await Assert.ThrowsAsync<PostgresException>(() => InsertRawAsync(connection, seed, "NearView", rank: 1, frame: 25));
        Assert.Equal(PostgresErrorCodes.UniqueViolation, frame.SqlState);
        Assert.Equal("ux_observations_track_frame", frame.ConstraintName);

        await InsertRawAsync(connection, seed, "NearView", rank: 1, frame: 42);
        var role = await Assert.ThrowsAsync<PostgresException>(() => InsertRawAsync(connection, seed, "NearView", rank: 2, frame: 43));
        Assert.Equal("ux_observations_track_role", role.ConstraintName);

        var delete = await Assert.ThrowsAsync<PostgresException>(() => ExecuteAsync(connection, "DELETE FROM artifacts WHERE id = $1", seed.CropArtifactId));
        Assert.Equal(PostgresErrorCodes.ForeignKeyViolation, delete.SqlState);
    }

    [Fact]
    public async Task DownMigrationRefusesEvidenceSetRowsAndRestoresThePrecedingSchemaOtherwise()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var seed = await SeedAsync(db, withObservation: true);
        await using var connection = await OpenAsync();
        await InsertRawAsync(connection, seed, "LateDiverse", rank: 1, frame: 50);
        var migrator = db.GetService<IMigrator>();

        var refused = await Assert.ThrowsAsync<PostgresException>(() => migrator.MigrateAsync(BeforeEvidenceSet));
        Assert.Contains("observations_evidence_set_rows_present", refused.MessageText, StringComparison.Ordinal);
        Assert.True(await ColumnExistsAsync(connection, "evidence_rank"));

        await ExecuteAsync(connection, "DELETE FROM observations WHERE observation_type <> 'Representative' AND track_id = $1", seed.TrackId);
        await migrator.MigrateAsync(BeforeEvidenceSet);
        Assert.False(await ColumnExistsAsync(connection, "evidence_rank"));
        Assert.False(await ColumnExistsAsync(connection, "selection_score"));
        await using var survivors = new NpgsqlCommand("SELECT count(*) FROM observations", connection);
        Assert.Equal(1L, await survivors.ExecuteScalarAsync());
    }

    // Seeding
    private sealed record Seed(Guid TrackId, Guid ObservationId, Guid CropArtifactId);

    private async Task<Seed> SeedAtPrecedingSchemaAsync()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var seed = await SeedAsync(db, withObservation: true);
        await db.GetService<IMigrator>().MigrateAsync(BeforeEvidenceSet);
        return seed;
    }

    private static async Task<Seed> SeedAsync(
        Mavi.Infrastructure.Persistence.MaviDbContext db,
        bool withObservation,
        double qualityScore = 0.9,
        double selectionScore = 0.9)
    {
        var start = new DateTimeOffset(2026, 9, 23, 6, 0, 0, TimeSpan.Zero);
        var camera = Camera.Create("CAM-EVID", "Evidence Camera", "UTC", start.AddMinutes(-5));
        var source = Artifact.Create(ArtifactType.SourceVideo, "source/evid.mp4", "video/mp4", 1, new string('a', 64),
            createdAtUtc: start.AddMinutes(-4));
        var video = VideoAsset.Create(Guid.CreateVersion7(), camera.Id, source.Id, "evid.mp4", start, durationMs: 60_000,
            frameRateNumerator: 25, frameRateDenominator: 1, width: 1920, height: 1080, codec: "h264",
            timestampSource: TimestampSource.Manual, timestampConfidence: 1.0, recordingTimeZoneId: "UTC",
            recordingUtcOffsetMinutes: 0, importedAtUtc: start.AddMinutes(-3));
        var run = ProcessingRun.Create(video.Id, "phase1-detection-tracking-v1", "{}", start);
        var track = Track.Create(run.Id, video.Id, 1, ObjectClass.Person, 0, 2_000, start, detectionCount: 8,
            meanConfidence: 0.8, maxConfidence: 0.9, createdAtUtc: start);
        var crop = Artifact.Create(ArtifactType.Thumbnail, $"evidence/{run.Id:D}/attempt-0001/thumbnails/person-000001-{new string('b', 64)}.jpg",
            "image/jpeg", 160, new string('b', 64), createdAtUtc: start);
        db.AddRange(camera, source, video, run, track, crop);
        await db.SaveChangesAsync();

        var observationId = Guid.Empty;
        if (withObservation)
        {
            var observation = Observation.Create(track.Id, ObservationType.Representative, sourceFrameNumber: 25,
                videoOffsetMs: 1_000, recordingStartUtc: start, x: 0.1f, y: 0.2f, width: 0.3f, height: 0.4f,
                confidence: 0.85, qualityScore: qualityScore, evidenceRank: 0, selectionScore: selectionScore, createdAtUtc: start);
            observation.AttachEvidenceArtifact(crop.Id);
            db.Observations.Add(observation);
            await db.SaveChangesAsync();
            observationId = observation.Id;
        }

        return new Seed(track.Id, observationId, crop.Id);
    }

    private static async Task InsertRawAsync(NpgsqlConnection connection, Seed seed, string role, int rank, long frame)
    {
        await using var insert = new NpgsqlCommand("""
            INSERT INTO observations(id,track_id,observation_type,evidence_rank,source_frame_number,video_offset_ms,timestamp_utc,
                bounding_box_x,bounding_box_y,bounding_box_width,bounding_box_height,confidence,quality_score,selection_score,
                thumbnail_artifact_id,created_at_utc)
            VALUES ($1,$2,$3,$4,$5,$5 * 40,$6,0.1,0.2,0.3,0.4,0.8,0.7,0.6,NULL,$6)
            """, connection);
        insert.Parameters.AddWithValue(Guid.CreateVersion7());
        insert.Parameters.AddWithValue(seed.TrackId);
        insert.Parameters.AddWithValue(role);
        insert.Parameters.AddWithValue(rank);
        insert.Parameters.AddWithValue(frame);
        insert.Parameters.AddWithValue(new DateTimeOffset(2026, 9, 23, 6, 0, 2, TimeSpan.Zero));
        await insert.ExecuteNonQueryAsync();
    }

    private async Task<NpgsqlConnection> OpenAsync()
    {
        var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        return connection;
    }

    private static async Task ExecuteAsync(NpgsqlConnection connection, string sql, Guid id)
    {
        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue(id);
        await command.ExecuteNonQueryAsync();
    }

    private static async Task<bool> ColumnExistsAsync(NpgsqlConnection connection, string column)
    {
        await using var command = new NpgsqlCommand(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'observations' AND column_name = $1)", connection);
        command.Parameters.AddWithValue(column);
        return (bool)(await command.ExecuteScalarAsync())!;
    }
}
