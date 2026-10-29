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
        // MAVI_TEST_DB_CONNECTION is required (a mavi_dev fallback is forbidden); TestDatabase resolves this
        // run's database from it.
        ConnectionString = TestDatabase.ConnectionString;
        EnsureTestDatabase(ConnectionString);
    }

    public string ConnectionString { get; }
    public string MediaRoot => MediaRootOverride ?? _mediaRoot;
    public string EvidenceRoot => EvidenceRootOverride ?? _evidenceRoot;
    public TimeProvider Clock { get; init; } = TimeProvider.System;
    public Action<DbContextOptionsBuilder>? ConfigureDbContext { get; init; }
    public Action<IServiceCollection>? OverrideServices { get; init; }

    /// <summary>Configuration applied over the defaults above (for example a lease policy).</summary>
    public IReadOnlyDictionary<string, string?>? AdditionalConfiguration { get; init; }
    public string? StaticWebRoot { get; init; }
    public bool EnableStartupMigrations { get; init; }

    /// <summary>
    /// Whether the analytics background host runs. Off by default, and deliberately so:
    /// a loop that queues and analyses units on its own schedule would mutate the
    /// database underneath every other API test. The tests that are about the host turn
    /// it on and drive one cycle themselves.
    /// </summary>
    public bool EnableSceneAnalyticsHost { get; init; }

    /// <summary>The analytic-event sweep (ADR-025); off by default so tests derive deliberately.</summary>
    public bool EnableAnalyticEventsHost { get; init; }

    /// <summary>
    /// Off by default: a background janitor reclaiming staging while a test inspects it would
    /// make unrelated tests timing-dependent. Janitor tests drive cycles explicitly.
    /// </summary>
    public bool EnableStagingJanitorHost { get; init; }

    /// <summary>
    /// The S1.4 B3 activation gate (<c>VisionFinalization:Enabled</c>). Off by default, as in
    /// a deployment of F2 alone: completion 2.0/3.0 synchronous, 3.1 refused. The F2 hand-off
    /// suites turn it on to exercise the path the F3 release activates.
    /// </summary>
    public bool EnableAsynchronousFinalization { get; init; }

    /// <summary>
    /// Whether the hosted finalizer's loop runs. Off by default: a loop claiming and
    /// publishing Finalizing jobs on its own schedule would race every finalizer test that
    /// drives the lifecycle by hand. Host tests turn it on and drive one cycle themselves.
    /// </summary>
    public bool EnableVisionFinalizationHost { get; init; }

    /// <summary>
    /// Whether the plate authority loop runs on its own schedule. Off by default for the same reason: plate tests drive
    /// <c>PlateHostedService.RunCycleAsync</c> themselves. <c>Plates:Enabled</c> is a separate thing — it gates only new
    /// activation and queueing — and is on in tests.
    /// </summary>
    public bool EnablePlateHostedLoop { get; init; }

    /// <summary>The re-analysis operator key whose SHA-256 the test platform is configured with (PoC S3, C4.2).</summary>
    public const string TestReanalysisOperatorKey = "mavi-test-reanalysis-operator-key-not-a-secret";

    public static readonly string TestReanalysisOperatorKeySha256 = Convert.ToHexStringLower(
        System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(TestReanalysisOperatorKey)));

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

    /// <summary>
    /// The attribute release overlay (S2b): a Component Binding with an <c>attributes</c> role
    /// and its pipeline profile. Unset, the platform reads no attribute release.
    /// </summary>
    public string? VisualAttributeComponentBindingPath { get; init; }

    /// <summary>The host environment; "Testing" unless a test is about another one.</summary>
    public string EnvironmentName { get; init; } = "Testing";
    public string? VisualAttributePipelineProfilePath { get; init; }

    /// <summary>The plate release (Stage 4 PR-3): a Component Binding with a <c>plates</c> role and its profile.</summary>
    public string? PlateComponentBindingPath { get; init; }
    public string? PlatePipelineProfilePath { get; init; }

    public int StartupMigrationLockTimeoutSeconds { get; init; } = 30;
    public int StartupMigrationCommandTimeoutSeconds { get; init; } = 120;

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment(EnvironmentName);
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
                ["AnalyticEvents:Enabled"] = EnableAnalyticEventsHost ? "true" : "false",
                ["StagingJanitor:Enabled"] = EnableStagingJanitorHost ? "true" : "false",
                ["VisionFinalization:Enabled"] = EnableAsynchronousFinalization ? "true" : "false",
                ["TrackSearch:CursorSigningKey"] = CursorSigningKey,
                // The loop stays off: attribute tests drive RunCycleAsync themselves.
                ["VisualAttributes:Enabled"] = "false",
                ["VisualAttributes:ComponentBindingPath"] = VisualAttributeComponentBindingPath ?? string.Empty,
                ["VisualAttributes:PipelineProfilePath"] = VisualAttributePipelineProfilePath ?? string.Empty,
                // Plate analysis is on; its hosted loop is removed below unless a test opts in, so plate tests drive
                // RunCycleAsync themselves.
                ["Plates:Enabled"] = "true",
                ["Plates:ReanalysisOperatorKeySha256"] = TestReanalysisOperatorKeySha256,
                ["Plates:ComponentBindingPath"] = PlateComponentBindingPath ?? string.Empty,
                ["Plates:PipelineProfilePath"] = PlatePipelineProfilePath ?? string.Empty,
                ["DatabaseMigrations:LockTimeoutSeconds"] =
                    StartupMigrationLockTimeoutSeconds.ToString(System.Globalization.CultureInfo.InvariantCulture),
                ["DatabaseMigrations:CommandTimeoutSeconds"] =
                    StartupMigrationCommandTimeoutSeconds.ToString(System.Globalization.CultureInfo.InvariantCulture),
            });
            if (AdditionalConfiguration is not null)
                configuration.AddInMemoryCollection(AdditionalConfiguration);
        });
        builder.ConfigureServices(services =>
        {
            services.RemoveAll<TimeProvider>();
            services.AddSingleton(Clock);
            if (!EnableVisionFinalizationHost)
            {
                // The loop would claim and publish Finalizing jobs underneath every finalizer
                // test that drives the lifecycle by hand; host tests opt in and drive cycles.
                foreach (var descriptor in services.Where(x => x.ImplementationType == typeof(Mavi.Api.Finalization.VisionFinalizationHostedService)).ToList())
                    services.Remove(descriptor);
            }
            if (!EnablePlateHostedLoop)
            {
                // Registered through a factory that resolves the PlateHostedService singleton, which tests still use.
                foreach (var descriptor in services.Where(x => x.ServiceType == typeof(Microsoft.Extensions.Hosting.IHostedService) &&
                             x.ImplementationFactory?.Method.ReturnType == typeof(Mavi.Api.Plates.PlateHostedService)).ToList())
                    services.Remove(descriptor);
            }
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
        if (!TestDatabase.IsTestDatabaseName(database))
        {
            throw new InvalidOperationException("API integration tests may use and reset only their own mavi_test database.");
        }
    }
}
