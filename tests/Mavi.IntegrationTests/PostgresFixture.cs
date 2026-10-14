using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.IntegrationTests;

public sealed class PostgresFixture
{
    // Configuration
    public PostgresFixture()
    {
        // mavi_test, or this run's isolated mavi_test_<id> (TestDatabase): never another run's database.
        ConnectionString = TestDatabase.ConnectionString;
        var builder = new NpgsqlConnectionStringBuilder(ConnectionString);
        if (!TestDatabase.IsTestDatabaseName(builder.Database))
        {
            throw new InvalidOperationException("Integration tests may reset only their own mavi_test database.");
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
