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

    private static async Task<bool> TableExistsAsync(NpgsqlConnection connection, string tableName)
    {
        await using var command = new NpgsqlCommand(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=$1);",
            connection);
        command.Parameters.AddWithValue(tableName);
        return (bool)(await command.ExecuteScalarAsync() ?? false);
    }
}
