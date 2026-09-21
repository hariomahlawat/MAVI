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
    private readonly string _evidenceRoot = Path.Combine(Path.GetTempPath(), $"mavi-api-evidence-{Guid.NewGuid():N}");

    // Configuration
    public ApiTestFactory()
    {
        ConnectionString = Environment.GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION")
            ?? throw new InvalidOperationException(
                "MAVI_TEST_DB_CONNECTION is required for API integration tests; mavi_dev fallback is forbidden.");
        EnsureTestDatabase(ConnectionString);
    }

    public string ConnectionString { get; }
    public string MediaRoot => MediaRootOverride ?? _mediaRoot;
    public string EvidenceRoot => EvidenceRootOverride ?? _evidenceRoot;
    public TimeProvider Clock { get; init; } = TimeProvider.System;
    public Action<DbContextOptionsBuilder>? ConfigureDbContext { get; init; }
    public Action<IServiceCollection>? OverrideServices { get; init; }
    public string? StaticWebRoot { get; init; }
    public bool EnableStartupMigrations { get; init; }

    /// <summary>
    /// Whether the analytics background host runs. Off by default, and deliberately so:
    /// a loop that queues and analyses units on its own schedule would mutate the
    /// database underneath every other API test. The tests that are about the host turn
    /// it on and drive one cycle themselves.
    /// </summary>
    public bool EnableSceneAnalyticsHost { get; init; }

    /// <summary>Use an existing media root instead of a fresh temporary one.</summary>
    public string? MediaRootOverride { get; init; }

    /// <summary>
    /// Use an existing evidence root, so a test can seal artefacts before the host reads
    /// them.
    /// </summary>
    public string? EvidenceRootOverride { get; init; }
    /// <summary>
    /// The analytic cursor signing key, base64 of 32 bytes. Fixed rather than ephemeral
    /// so that two factories can share a key — or deliberately not, to prove rotation.
    /// </summary>
    public string CursorSigningKey { get; init; } = DefaultCursorSigningKey;

    public const string DefaultCursorSigningKey = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=";

    public int StartupMigrationLockTimeoutSeconds { get; init; } = 30;
    public int StartupMigrationCommandTimeoutSeconds { get; init; } = 120;

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");
        if (!string.IsNullOrWhiteSpace(StaticWebRoot))
            builder.UseWebRoot(StaticWebRoot);
        builder.UseSetting("ConnectionStrings:Mavi", ConnectionString);
        builder.ConfigureAppConfiguration((_, configuration) =>
        {
            configuration.AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["ConnectionStrings:Mavi"] = ConnectionString,
                ["MediaStorage:RootPath"] = MediaRoot,
                ["MediaStorage:EvidenceRootPath"] = EvidenceRoot,
                ["MediaProcessing:FfprobePath"] = "ffprobe",
                ["MediaProcessing:FfmpegPath"] = "ffmpeg",
                ["MediaProcessing:ProbeTimeoutSeconds"] = "30",
                ["VideoImport:MaximumFileSizeBytes"] = "3221225472",
                ["VideoImport:MultipartOverheadBytes"] = "1048576",
                ["VideoImport:AllowedExtensions:0"] = ".mp4",
                ["DatabaseMigrations:Enabled"] = EnableStartupMigrations ? "true" : "false",
                ["MediaProcessing:VerifyOnStartup"] = "false",
                ["SceneAnalytics:Enabled"] = EnableSceneAnalyticsHost ? "true" : "false",
                ["TrackSearch:CursorSigningKey"] = CursorSigningKey,
                ["DatabaseMigrations:LockTimeoutSeconds"] =
                    StartupMigrationLockTimeoutSeconds.ToString(System.Globalization.CultureInfo.InvariantCulture),
                ["DatabaseMigrations:CommandTimeoutSeconds"] =
                    StartupMigrationCommandTimeoutSeconds.ToString(System.Globalization.CultureInfo.InvariantCulture),
            });
        });
        builder.ConfigureServices(services =>
        {
            services.RemoveAll<TimeProvider>();
            services.AddSingleton(Clock);
            services.RemoveAll<DbContextOptions<MaviDbContext>>();
            services.AddDbContext<MaviDbContext>(options =>
            {
                options.UseNpgsql(ConnectionString, npgsql => npgsql.UseVector());
                ConfigureDbContext?.Invoke(options);
            });
            OverrideServices?.Invoke(services);
        });
    }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (disposing && MediaRootOverride is null && Directory.Exists(_mediaRoot))
            Directory.Delete(_mediaRoot, true);
        if (disposing && EvidenceRootOverride is null && Directory.Exists(_evidenceRoot))
        {
            foreach (var file in Directory.GetFiles(_evidenceRoot, "*", SearchOption.AllDirectories))
                File.SetAttributes(file, FileAttributes.Normal);
            Directory.Delete(_evidenceRoot, true);
        }
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
