using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.IntegrationTests;

public sealed class PostgresFixture
{
    // Configuration
    public PostgresFixture()
    {
        ConnectionString = Environment.GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION")
            ?? throw new InvalidOperationException("MAVI_TEST_DB_CONNECTION is required for PostgreSQL integration tests.");
        var builder = new NpgsqlConnectionStringBuilder(ConnectionString);
        if (!string.Equals(builder.Database, "mavi_test", StringComparison.Ordinal))
        {
            throw new InvalidOperationException("Integration tests may reset only the mavi_test database.");
        }
    }

    public string ConnectionString { get; }

    // Database lifecycle
    public MaviDbContext CreateDbContext()
    {
        var options = new DbContextOptionsBuilder<MaviDbContext>()
            .UseNpgsql(ConnectionString, options => options.UseVector())
            .Options;
        return new MaviDbContext(options);
    }

    public async Task ResetDatabaseAsync()
    {
        await using var connection = new NpgsqlConnection(ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "DROP EXTENSION IF EXISTS vector CASCADE; DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;",
            connection);
        await command.ExecuteNonQueryAsync();
    }
}
