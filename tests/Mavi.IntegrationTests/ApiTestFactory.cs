using Mavi.Infrastructure.Persistence;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Npgsql;

namespace Mavi.IntegrationTests;

public sealed class ApiTestFactory : WebApplicationFactory<Program>
{
    private readonly string _mediaRoot = Path.Combine(Path.GetTempPath(), $"mavi-api-media-{Guid.NewGuid():N}");

    // Configuration
    public ApiTestFactory()
    {
        ConnectionString = Environment.GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION")
            ?? throw new InvalidOperationException(
                "MAVI_TEST_DB_CONNECTION is required for API integration tests; mavi_dev fallback is forbidden.");
        EnsureTestDatabase(ConnectionString);
    }

    public string ConnectionString { get; }

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");
        builder.UseSetting("ConnectionStrings:Mavi", ConnectionString);
        builder.ConfigureAppConfiguration((_, configuration) =>
        {
            configuration.AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["ConnectionStrings:Mavi"] = ConnectionString,
                ["MediaStorage:RootPath"] = _mediaRoot,
                ["MediaProcessing:FfprobePath"] = "ffprobe",
            });
        });
        builder.ConfigureServices(services =>
        {
            services.RemoveAll<DbContextOptions<MaviDbContext>>();
            services.AddDbContext<MaviDbContext>(options =>
                options.UseNpgsql(ConnectionString, npgsql => npgsql.UseVector()));
        });
    }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (disposing && Directory.Exists(_mediaRoot)) Directory.Delete(_mediaRoot, true);
    }

    // Database lifecycle
    public async Task ResetAndMigrateAsync()
    {
        EnsureTestDatabase(ConnectionString);

        await using (var connection = new NpgsqlConnection(ConnectionString))
        {
            await connection.OpenAsync();
            await using var command = new NpgsqlCommand(
                "DROP EXTENSION IF EXISTS vector CASCADE; DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;",
                connection);
            await command.ExecuteNonQueryAsync();
        }

        using var scope = Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        await db.Database.MigrateAsync();
    }

    private static void EnsureTestDatabase(string connectionString)
    {
        var database = new NpgsqlConnectionStringBuilder(connectionString).Database;
        if (!string.Equals(database, "mavi_test", StringComparison.Ordinal))
        {
            throw new InvalidOperationException("API integration tests may use and reset only the mavi_test database.");
        }
    }
}
