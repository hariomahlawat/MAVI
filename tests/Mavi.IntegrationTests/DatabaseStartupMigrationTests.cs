using System.Net;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class DatabaseStartupMigrationTests
{
    private const int AdvisoryLockNamespace = 1296127561;
    private const int AdvisoryLockPurpose = 1397248845;

    [Fact]
    public async Task BlankDatabaseIsMigratedBeforeApplicationServesRequests()
    {
        var connectionString = GetTestConnectionString();
        await ResetSchemaAsync(connectionString);

        using (var factory = new ApiTestFactory
        {
            EnableStartupMigrations = true,
        })
        using (var client = factory.CreateClient())
        {
            using var response = await client.GetAsync("/api/health");
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);

            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<Mavi.Infrastructure.Persistence.MaviDbContext>();
            Assert.Empty(await db.Database.GetPendingMigrationsAsync());
            Assert.NotEmpty(await db.Database.GetAppliedMigrationsAsync());
        }
    }

    [Fact]
    public async Task CurrentDatabaseStartsWithoutChangingMigrationHistory()
    {
        var connectionString = GetTestConnectionString();
        await ResetSchemaAsync(connectionString);

        int initialCount;
        using (var firstFactory = new ApiTestFactory
        {
            EnableStartupMigrations = true,
        })
        using (var firstClient = firstFactory.CreateClient())
        {
            using var response = await firstClient.GetAsync("/api/health");
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            initialCount = await MigrationHistoryCountAsync(connectionString);
            Assert.True(initialCount > 0);
        }

        using (var secondFactory = new ApiTestFactory
        {
            EnableStartupMigrations = true,
        })
        using (var secondClient = secondFactory.CreateClient())
        {
            using var response = await secondClient.GetAsync("/api/health");
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        }

        Assert.Equal(initialCount, await MigrationHistoryCountAsync(connectionString));
    }

    [Fact]
    public async Task MigrationLockTimeoutPreventsApplicationStartup()
    {
        var connectionString = GetTestConnectionString();
        await ResetSchemaAsync(connectionString);

        await using var lockConnection = new NpgsqlConnection(connectionString);
        await lockConnection.OpenAsync();
        await using (var lockCommand = new NpgsqlCommand(
            "select pg_advisory_lock(@namespace, @purpose);",
            lockConnection))
        {
            lockCommand.Parameters.AddWithValue("namespace", AdvisoryLockNamespace);
            lockCommand.Parameters.AddWithValue("purpose", AdvisoryLockPurpose);
            await lockCommand.ExecuteScalarAsync();
        }

        try
        {
            using var factory = new ApiTestFactory
            {
                EnableStartupMigrations = true,
                StartupMigrationLockTimeoutSeconds = 1,
            };

            var exception = await Assert.ThrowsAnyAsync<Exception>(async () =>
            {
                using var client = factory.CreateClient();
                await client.GetAsync("/api/health");
            });

            Assert.Contains(
                "database migration lock",
                exception.ToString(),
                StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            await using var unlockCommand = new NpgsqlCommand(
                "select pg_advisory_unlock(@namespace, @purpose);",
                lockConnection);
            unlockCommand.Parameters.AddWithValue("namespace", AdvisoryLockNamespace);
            unlockCommand.Parameters.AddWithValue("purpose", AdvisoryLockPurpose);
            await unlockCommand.ExecuteScalarAsync();
        }
    }

    private static string GetTestConnectionString()
    {
        var value = Environment.GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION")
            ?? throw new InvalidOperationException(
                "MAVI_TEST_DB_CONNECTION is required for database startup migration tests.");
        var database = new NpgsqlConnectionStringBuilder(value).Database;
        if (!string.Equals(database, "mavi_test", StringComparison.Ordinal))
            throw new InvalidOperationException(
                "Database startup migration tests may use only mavi_test.");
        return value;
    }

    private static async Task ResetSchemaAsync(string connectionString)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "DROP EXTENSION IF EXISTS vector CASCADE; " +
            "DROP SCHEMA IF EXISTS public CASCADE; " +
            "CREATE SCHEMA public;",
            connection);
        await command.ExecuteNonQueryAsync();
    }

    private static async Task<int> MigrationHistoryCountAsync(string connectionString)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "select count(*)::int from \"__EFMigrationsHistory\";",
            connection);
        return Convert.ToInt32(
            await command.ExecuteScalarAsync(),
            System.Globalization.CultureInfo.InvariantCulture);
    }
}
