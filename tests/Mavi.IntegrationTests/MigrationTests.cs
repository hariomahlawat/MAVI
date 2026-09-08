using Mavi.Infrastructure.Persistence;
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

    private static async Task<bool> TableExistsAsync(NpgsqlConnection connection, string tableName)
    {
        await using var command = new NpgsqlCommand(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=$1);",
            connection);
        command.Parameters.AddWithValue(tableName);
        return (bool)(await command.ExecuteScalarAsync() ?? false);
    }
}
