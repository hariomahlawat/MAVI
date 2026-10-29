using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// The PoC S4 embedding schema (ADR-021 §4): migration <c>AddTrackEmbeddings</c> is purely additive — no existing
/// table's column changes — and round-trips down and up.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class EmbeddingPersistenceTests(PostgresFixture fixture)
{
    private const string Preceding = "20261029103926_AddAuditEntries";
    private const string Migration = "20261029114149_AddTrackEmbeddings";

    private static readonly string[] EmbeddingTables =
        ["embedding_analyses", "embedding_identity_activations", "track_embeddings", "appearance_query_embeddings"];

    [Fact]
    public async Task TheMigrationIsAdditiveAndRoundTrips()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        var migrator = db.GetService<IMigrator>();
        await migrator.MigrateAsync(Preceding);
        var before = await ColumnSignatureAsync();
        Assert.DoesNotContain(before, item => EmbeddingTables.Contains(item.Split('.')[0]));

        await migrator.MigrateAsync(Migration);
        var after = await ColumnSignatureAsync();
        Assert.All(EmbeddingTables, table => Assert.Contains(after, item => item.StartsWith(table + ".", StringComparison.Ordinal)));
        Assert.Equal(before, after.Where(item => !EmbeddingTables.Contains(item.Split('.')[0])).ToList());
        Assert.Contains("track_embeddings.embedding:USER-DEFINED:YES:", after);

        await migrator.MigrateAsync(Preceding);
        Assert.Equal(before, await ColumnSignatureAsync());
        await migrator.MigrateAsync(Migration);
        Assert.Equal(after, await ColumnSignatureAsync());
    }

    private async Task<List<string>> ColumnSignatureAsync()
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("""
            SELECT table_name || '.' || column_name || ':' || data_type || ':' || is_nullable || ':' || coalesce(column_default, '')
            FROM information_schema.columns WHERE table_schema = 'public' ORDER BY table_name, column_name
            """, connection);
        await using var reader = await command.ExecuteReaderAsync();
        var columns = new List<string>();
        while (await reader.ReadAsync()) columns.Add(reader.GetString(0));
        return columns;
    }
}
