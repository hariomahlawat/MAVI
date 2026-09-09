using Mavi.Infrastructure.Persistence;
using Mavi.Domain.Media;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class MigrationTests(PostgresFixture fixture)
{
    private const string BeforeProvenance = "20260909022831_AddSourceVideoShaUniqueness";
    private const string Provenance = "20260909033942_PreserveRecordingTimeProvenance";

    [Fact]
    public async Task InitialMigrationCreatesVectorExtensionAndCoreTables()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();

        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("SELECT extname FROM pg_extension WHERE extname='vector';", connection);
        Assert.Equal("vector", await command.ExecuteScalarAsync());

        Assert.True(await TableExistsAsync(connection, "cameras"));
        Assert.True(await TableExistsAsync(connection, "video_assets"));
        Assert.True(await TableExistsAsync(connection, "tracks"));
    }

    [Fact]
    public async Task RecordingTimeInvariantMigrationUpgradesInitialSchema()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        var migrator = db.GetService<IMigrator>();

        await migrator.MigrateAsync("20260908153824_InitialVisualMemory");
        await db.Database.MigrateAsync();

        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_video_assets_recording_end');",
            connection);
        Assert.True((bool)(await command.ExecuteScalarAsync() ?? false));
    }

    [Fact]
    public async Task SourceVideoShaGuardrailIsPartialAndUnique()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'ux_artifacts_source_video_sha256';", connection);

        var definition = (string?)await command.ExecuteScalarAsync();

        Assert.Contains("UNIQUE INDEX", definition, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("artifact_type", definition, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("SourceVideo", definition, StringComparison.Ordinal);
    }

    [Fact]
    public async Task DatabaseRejectsDuplicateSourceVideoShaButAllowsOtherArtifactTypes()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        var sha = new string('b', 64);
        db.Artifacts.Add(Artifact.Create(ArtifactType.SourceVideo, "source/one.mp4", "video/mp4", 1, sha));
        await db.SaveChangesAsync();
        db.Artifacts.Add(Artifact.Create(ArtifactType.SourceVideo, "source/two.mp4", "video/mp4", 1, sha));

        var exception = await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync());

        var postgres = Assert.IsType<PostgresException>(exception.InnerException);
        Assert.Equal(PostgresErrorCodes.UniqueViolation, postgres.SqlState);
        Assert.Equal("ux_artifacts_source_video_sha256", postgres.ConstraintName);
        db.ChangeTracker.Clear();
        db.Artifacts.Add(Artifact.Create(ArtifactType.Thumbnail, "thumbs/one.jpg", "image/jpeg", 1, sha));
        db.Artifacts.Add(Artifact.Create(ArtifactType.Thumbnail, "thumbs/two.jpg", "image/jpeg", 1, sha));
        await db.SaveChangesAsync();
    }

    [Fact]
    public async Task ProvenanceMigrationCanonicalizesLegacyWindowsZonesAndBackfillsHistoricalOffsets()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        var migrator = db.GetService<IMigrator>();
        await migrator.MigrateAsync(BeforeProvenance);
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();

        await InsertLegacyVideoAsync(connection, "IND", "India Standard Time", new DateTimeOffset(2026, 1, 15, 0, 0, 0, TimeSpan.Zero));
        await InsertLegacyVideoAsync(connection, "EST", "Eastern Standard Time", new DateTimeOffset(2026, 7, 15, 12, 0, 0, TimeSpan.Zero));
        await InsertLegacyVideoAsync(connection, "UTC", "UTC", new DateTimeOffset(2026, 1, 15, 0, 0, 0, TimeSpan.Zero));
        await migrator.MigrateAsync(Provenance);

        await using var command = new NpgsqlCommand("""
            SELECT c.code, c.time_zone_id, v.recording_time_zone_id, v.recording_utc_offset_minutes
            FROM cameras c JOIN video_assets v ON v.camera_id = c.id ORDER BY c.code;
            """, connection);
        await using var reader = await command.ExecuteReaderAsync();
        var actual = new List<(string Code, string CameraZone, string RecordingZone, int Offset)>();
        while (await reader.ReadAsync()) actual.Add((reader.GetString(0), reader.GetString(1), reader.GetString(2), reader.GetInt32(3)));
        Assert.Equal([
            ("EST", "America/New_York", "America/New_York", -240),
            ("IND", "Asia/Kolkata", "Asia/Kolkata", 330),
            ("UTC", "UTC", "UTC", 0)], actual);
    }

    [Fact]
    public async Task ProvenanceMigrationFailsActionablyForUnknownLegacyZone()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        var migrator = db.GetService<IMigrator>();
        await migrator.MigrateAsync(BeforeProvenance);
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await InsertLegacyVideoAsync(connection, "BAD", "Legacy Unknown Zone", new DateTimeOffset(2026, 1, 15, 0, 0, 0, TimeSpan.Zero));

        var exception = await Assert.ThrowsAsync<PostgresException>(() => migrator.MigrateAsync(Provenance));
        Assert.Contains("Legacy camera timezone canonicalization is required", exception.MessageText, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ProcessingOrchestrationMigrationUsesConfiguredAttemptPolicyAndActiveRunIndex()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        await using var connection = new NpgsqlConnection(fixture.ConnectionString); await connection.OpenAsync();
        await using var command = new NpgsqlCommand("""
            SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_vision_jobs_attempts';
            """, connection);
        var constraint = (string?)await command.ExecuteScalarAsync();
        Assert.Contains("attempt_count >= 0", constraint, StringComparison.Ordinal);
        Assert.DoesNotContain("<= 3", constraint, StringComparison.Ordinal);
        await using var index = new NpgsqlCommand("SELECT indexdef FROM pg_indexes WHERE indexname='ux_processing_runs_active_video';", connection);
        var definition = (string?)await index.ExecuteScalarAsync();
        Assert.Contains("UNIQUE", definition, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("Queued", definition, StringComparison.Ordinal);
        Assert.Contains("Running", definition, StringComparison.Ordinal);
    }

    private static async Task InsertLegacyVideoAsync(NpgsqlConnection connection, string code, string zone, DateTimeOffset startUtc)
    {
        var cameraId = Guid.CreateVersion7();
        var artifactId = Guid.CreateVersion7();
        var videoId = Guid.CreateVersion7();
        await using var batch = new NpgsqlBatch(connection);
        var camera = new NpgsqlBatchCommand("""
            INSERT INTO cameras(id,code,name,time_zone_id,is_active,created_at_utc,updated_at_utc)
            VALUES ($1,$2,$2,$3,true,$4,$4)
            """);
        camera.Parameters.AddWithValue(cameraId); camera.Parameters.AddWithValue(code);
        camera.Parameters.AddWithValue(zone); camera.Parameters.AddWithValue(new DateTimeOffset(2026, 9, 9, 0, 0, 0, TimeSpan.Zero));
        var artifact = new NpgsqlBatchCommand("""
            INSERT INTO artifacts(id,artifact_type,storage_key,mime_type,size_bytes,sha256,created_at_utc)
            VALUES ($1,'SourceVideo',$2,'video/mp4',1,$3,$4)
            """);
        artifact.Parameters.AddWithValue(artifactId); artifact.Parameters.AddWithValue($"source/{code.ToLowerInvariant()}.mp4");
        artifact.Parameters.AddWithValue(new string(char.ToLowerInvariant(code[0]), 64));
        artifact.Parameters.AddWithValue(new DateTimeOffset(2026, 9, 9, 0, 0, 0, TimeSpan.Zero));
        var video = new NpgsqlBatchCommand("""
            INSERT INTO video_assets(id,camera_id,source_artifact_id,original_file_name,source_type,
                recording_start_utc,recording_end_utc,duration_ms,frame_rate_numerator,frame_rate_denominator,
                width,height,codec,timestamp_source,timestamp_confidence,processing_status,imported_at_utc)
            VALUES ($1,$2,$3,'legacy.mp4','UploadedFile',$4,$4 + interval '1 second',1000,25,1,160,90,
                'h264','Manual',1,'NotQueued',$5)
            """);
        video.Parameters.AddWithValue(videoId); video.Parameters.AddWithValue(cameraId);
        video.Parameters.AddWithValue(artifactId); video.Parameters.AddWithValue(startUtc);
        video.Parameters.AddWithValue(new DateTimeOffset(2026, 9, 9, 0, 0, 0, TimeSpan.Zero));
        batch.BatchCommands.Add(camera); batch.BatchCommands.Add(artifact); batch.BatchCommands.Add(video);
        await batch.ExecuteNonQueryAsync();
    }

    private static async Task<bool> TableExistsAsync(NpgsqlConnection connection, string tableName)
    {
        await using var command = new NpgsqlCommand(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=$1);",
            connection);
        command.Parameters.AddWithValue(tableName);
        return (bool)(await command.ExecuteScalarAsync() ?? false);
    }
}
