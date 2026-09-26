using System.Text.Json;
using System.Xml.Linq;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Media;
using Mavi.Application;
using Mavi.Contracts.Worker;
using Mavi.Infrastructure;
using Mavi.Infrastructure.Media;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

public sealed class ConfigurationValidationTests
{
    // Valid configuration
    [Fact]
    public void ValidConfigurationResolvesAllOptions()
    {
        using var provider = BuildProvider();

        Assert.NotNull(provider.GetRequiredService<IOptions<MediaStorageOptions>>().Value);
        Assert.NotNull(provider.GetRequiredService<IOptions<MediaProcessingOptions>>().Value);
        Assert.NotNull(provider.GetRequiredService<IOptions<VideoImportOptions>>().Value);
        Assert.Equal("Asia/Kolkata", provider.GetRequiredService<IOptions<LocalizationOptions>>().Value.DefaultDisplayTimeZoneId);
        Assert.Equal(3, provider.GetRequiredService<IOptions<VisionProcessingOptions>>().Value.MaximumAttempts);
    }

    // Invalid configuration
    [Theory]
    [InlineData("MediaStorage:RootPath", "")]
    [InlineData("MediaStorage:EvidenceRootPath", "")]
    [InlineData("MediaProcessing:FfprobePath", " ")]
    [InlineData("MediaProcessing:ProbeTimeoutSeconds", "0")]
    [InlineData("MediaProcessing:ProbeTimeoutSeconds", "301")]
    [InlineData("VideoImport:MaximumFileSizeBytes", "0")]
    [InlineData("VideoImport:MultipartOverheadBytes", "0")]
    [InlineData("Localization:DefaultDisplayTimeZoneId", "Invalid/Mavi")]
    [InlineData("Localization:DefaultDisplayTimeZoneId", "India Standard Time")]
    [InlineData("Localization:DefaultDisplayTimeZoneId", "")]
    [InlineData("Localization:DefaultDisplayTimeZoneId", " Asia/Kolkata ")]
    [InlineData("Localization:DefaultDisplayTimeZoneId", "UTC ")]
    [InlineData("Localization:DefaultDisplayTimeZoneId", " UTC")]
    [InlineData("TrackSearch:CursorSigningKey", "not-base64")]
    [InlineData("TrackSearch:CursorSigningKey", "AAEC")]
    [InlineData("TrackSearch:CursorSigningKey", "")]
    [InlineData("VisionProcessing:Pipeline", "")]
    [InlineData("VisionProcessing:PipelineVersion", "")]
    [InlineData("VisionProcessing:MaximumAttempts", "0")]
    [InlineData("VisionProcessing:LeaseSeconds", "0")]
    [InlineData("VisionProcessing:HeartbeatExtensionSeconds", "0")]
    [InlineData("VisionFinalization:ClaimSeconds", "0")]
    [InlineData("VisionFinalization:ClaimExtensionSeconds", "301")]
    [InlineData("VisionFinalization:MaximumFinalizationDurationSeconds", "299")]
    [InlineData("VisionFinalization:MaxConcurrentFinalizations", "0")]
    public void InvalidConfigurationIsRejected(string key, string value)
    {
        using var provider = BuildProvider(new Dictionary<string, string?> { [key] = value });

        Assert.Throws<OptionsValidationException>(() =>
        {
            _ = provider.GetRequiredService<IOptions<MediaStorageOptions>>().Value;
            _ = provider.GetRequiredService<IOptions<MediaProcessingOptions>>().Value;
            _ = provider.GetRequiredService<IOptions<VideoImportOptions>>().Value;
            _ = provider.GetRequiredService<IOptions<LocalizationOptions>>().Value;
            _ = provider.GetRequiredService<IOptions<VisionProcessingOptions>>().Value;
            _ = provider.GetRequiredService<IOptions<TrackSearchOptions>>().Value;
            _ = provider.GetRequiredService<IOptions<VisionFinalizationOptions>>().Value;
        });
    }

    [Fact]
    public void ADisabledFinalizationSectionIsStillValidated()
    {
        using var provider = BuildProvider(new Dictionary<string, string?>
        {
            ["VisionFinalization:Enabled"] = "false",
            ["VisionFinalization:ClaimSeconds"] = "0",
        });

        Assert.Throws<OptionsValidationException>(() => provider.GetRequiredService<IOptions<VisionFinalizationOptions>>().Value);
    }

    // Shipped finalizer configuration (S1.4 F4-C; docs/qualification/stage2-s1/f4-configuration-freeze.md).
    // These read the real appsettings.json, not a test host: the checker binds M2 to that file.
    private static readonly (string Key, JsonValueKind Kind, int Number)[] FrozenVisionFinalization =
    [
        ("Enabled", JsonValueKind.True, 0),
        ("MaxConcurrentFinalizations", JsonValueKind.Number, 1),
        ("PollIntervalSeconds", JsonValueKind.Number, 5),
        ("ClaimSeconds", JsonValueKind.Number, 480),
        ("ClaimExtensionSeconds", JsonValueKind.Number, 300),
        ("MaximumFinalizationAttempts", JsonValueKind.Number, 3),
        ("MaximumFinalizationDurationSeconds", JsonValueKind.Number, 21_600),
        ("SealingBatchSize", JsonValueKind.Number, 200),
        ("PayloadCleanupGraceSeconds", JsonValueKind.Number, 0),
    ];

    [Fact]
    public void ShippedVisionFinalizationSectionIsTheF4Freeze()
    {
        var apiRoot = Path.Combine(FindRepositoryRoot(), "src", "platform", "Mavi.Api");
        using var shipped = JsonDocument.Parse(File.ReadAllText(Path.Combine(apiRoot, "appsettings.json")));
        var section = shipped.RootElement.GetProperty("VisionFinalization");

        // Exactly the nine keys, each with its frozen value.
        Assert.Equal(
            FrozenVisionFinalization.Select(x => x.Key).Order(StringComparer.Ordinal),
            section.EnumerateObject().Select(x => x.Name).Order(StringComparer.Ordinal));
        foreach (var (key, kind, number) in FrozenVisionFinalization)
        {
            var value = section.GetProperty(key);
            Assert.True(value.ValueKind == kind, $"{key} is {value.ValueKind}, expected {kind}");
            if (kind == JsonValueKind.Number)
                Assert.True(value.GetInt32() == number, $"{key} = {value.GetInt32()}, expected {number}");
        }

        var claim = section.GetProperty("ClaimSeconds").GetInt32();
        var extension = section.GetProperty("ClaimExtensionSeconds").GetInt32();
        var maximum = section.GetProperty("MaximumFinalizationDurationSeconds").GetInt32();
        var poll = section.GetProperty("PollIntervalSeconds").GetInt32();
        Assert.True(extension <= claim && claim <= maximum, "ClaimExtensionSeconds <= ClaimSeconds <= MaximumFinalizationDurationSeconds");
        Assert.Equal(22_085, maximum + claim + poll);

        // No environment file carries its own finalizer section, and no committed
        // connection string overrides the 30 s runtime command timeout.
        foreach (var name in new[] { "appsettings.json", "appsettings.Development.json", "appsettings.Production.json" })
        {
            using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(apiRoot, name)));
            if (name != "appsettings.json")
                Assert.False(document.RootElement.TryGetProperty("VisionFinalization", out _), $"{name} overrides VisionFinalization");
            if (document.RootElement.TryGetProperty("ConnectionStrings", out var connections))
            {
                foreach (var connection in connections.EnumerateObject())
                    Assert.DoesNotMatch("(?i)command\\s*timeout", connection.Value.GetString() ?? string.Empty);
            }
        }
    }

    [Fact]
    public void ShippedVisionFinalizationSectionBindsValidatesAndActivatesTheContract()
    {
        using var provider = BuildProvider(baseFile: ShippedAppsettingsPath());

        var options = provider.GetRequiredService<IOptions<VisionFinalizationOptions>>().Value;

        Assert.Empty(options.Validate());
        Assert.True(options.Enabled);
        var policy = options.ToPolicy();
        Assert.Equal(TimeSpan.FromSeconds(480), policy.ClaimDuration);
        Assert.Equal(TimeSpan.FromSeconds(300), policy.ClaimExtension);
        Assert.Equal(3, policy.MaximumAttempts);
        Assert.Equal(TimeSpan.FromSeconds(21_600), policy.MaximumDuration);
        Assert.Equal(200, policy.SealingBatchSize);
        Assert.Equal(1, options.MaxConcurrentFinalizations);
        Assert.Equal(5, options.PollIntervalSeconds);
        Assert.Equal(0, options.PayloadCleanupGraceSeconds);
        Assert.Equal(TimeSpan.FromSeconds(21_600 + 480), options.EffectiveMaximumFinalizationBound);

        Assert.Equal(["2.0", "3.1"], WorkerContractRules.CompletionSchemaVersions(options.Enabled));
        Assert.False(WorkerContractRules.IsAcceptedCompletionSchemaVersion("3.0", options.Enabled));
        Assert.True(WorkerContractRules.IsAcceptedCompletionSchemaVersion("2.0", options.Enabled));
        Assert.True(WorkerContractRules.IsAcceptedCompletionSchemaVersion("3.1", options.Enabled));
    }

    [Fact]
    public void AMachineOverrideHoldsTheShippedGateOff()
    {
        // Activation step 1 and rollback: a machine file or VisionFinalization__Enabled=false,
        // layered after appsettings.json, changes the gate and nothing else.
        using var provider = BuildProvider(
            new Dictionary<string, string?> { ["VisionFinalization:Enabled"] = "false" },
            baseFile: ShippedAppsettingsPath());

        var options = provider.GetRequiredService<IOptions<VisionFinalizationOptions>>().Value;

        Assert.False(options.Enabled);
        Assert.Equal(["2.0", "3.0"], WorkerContractRules.CompletionSchemaVersions(options.Enabled));
        Assert.False(WorkerContractRules.IsAcceptedCompletionSchemaVersion("3.1", options.Enabled));
        Assert.True(WorkerContractRules.IsAcceptedCompletionSchemaVersion("3.0", options.Enabled));
        Assert.Equal(480, options.ClaimSeconds);
        Assert.Equal(300, options.ClaimExtensionSeconds);
        Assert.Equal(3, options.MaximumFinalizationAttempts);
        Assert.Equal(21_600, options.MaximumFinalizationDurationSeconds);
        Assert.Equal(200, options.SealingBatchSize);
        Assert.Equal(5, options.PollIntervalSeconds);
        Assert.Equal(1, options.MaxConcurrentFinalizations);
        Assert.Equal(0, options.PayloadCleanupGraceSeconds);
    }

    private static string ShippedAppsettingsPath() =>
        Path.Combine(FindRepositoryRoot(), "src", "platform", "Mavi.Api", "appsettings.json");

    [Fact]
    public void AConfiguredCursorSigningKeyResolvesOnceAndIsNotEphemeral()
    {
        using var provider = BuildProvider();

        var key = provider.GetRequiredService<TrackCursorSigningKey>();

        Assert.False(key.IsEphemeral);
        Assert.Same(key, provider.GetRequiredService<TrackCursorSigningKey>());
    }

    [Fact]
    public void NoCursorSigningKeyIsRejectedUnlessEphemeralIsAllowed()
    {
        using var strict = BuildProvider(new Dictionary<string, string?> { ["TrackSearch:CursorSigningKey"] = null });
        Assert.Throws<OptionsValidationException>(() =>
            _ = strict.GetRequiredService<IOptions<TrackSearchOptions>>().Value);

        using var lenient = BuildProvider(new Dictionary<string, string?>
        {
            ["TrackSearch:CursorSigningKey"] = null,
            ["TrackSearch:AllowEphemeralCursorSigningKey"] = "true",
        });
        Assert.True(lenient.GetRequiredService<TrackCursorSigningKey>().IsEphemeral);
    }

    [Fact]
    public void OverlappingMediaAndEvidenceRootsAreRejected()
    {
        var sharedRoot = Path.Combine(Path.GetTempPath(), "mavi-config-overlap");
        using var provider = BuildProvider(new Dictionary<string, string?>
        {
            ["MediaStorage:RootPath"] = sharedRoot,
            ["MediaStorage:EvidenceRootPath"] = Path.Combine(sharedRoot, "evidence"),
        });

        Assert.Throws<OptionsValidationException>(() =>
            _ = provider.GetRequiredService<IOptions<MediaStorageOptions>>().Value);
    }

    [Fact]
    public void LinkedEvidenceRootIsRejected()
    {
        var root = Path.Combine(Path.GetTempPath(), $"mavi-config-link-root-{Guid.NewGuid():N}");
        var link = Path.Combine(Path.GetTempPath(), $"mavi-config-link-evidence-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            try
            {
                Directory.CreateSymbolicLink(link, root);
            }
            catch (Exception exception) when (
                exception is PlatformNotSupportedException or UnauthorizedAccessException)
            {
                return;
            }

            using var provider = BuildProvider(new Dictionary<string, string?>
            {
                ["MediaStorage:RootPath"] = root,
                ["MediaStorage:EvidenceRootPath"] = link,
            });

            Assert.Throws<OptionsValidationException>(() =>
                _ = provider.GetRequiredService<IOptions<MediaStorageOptions>>().Value);
        }
        finally
        {
            if (Directory.Exists(link))
                Directory.Delete(link);
            if (Directory.Exists(root))
                Directory.Delete(root, true);
        }
    }

    [Fact]
    public void ApplicationContractsDoNotExposePhysicalRootPath()
    {
        var applicationAssembly = typeof(VideoMetadata).Assembly;

        Assert.DoesNotContain(applicationAssembly.GetExportedTypes(), type =>
            type.GetProperties().Any(property => property.Name == "RootPath"));
    }

    [Fact]
    public void Task15UploadLimitsAreAlignedAcrossApplicationAndIis()
    {
        var repositoryRoot = FindRepositoryRoot();
        var appsettingsPath = Path.Combine(repositoryRoot, "src", "platform", "Mavi.Api", "appsettings.json");
        var webConfigPath = Path.Combine(repositoryRoot, "src", "platform", "Mavi.Api", "web.config");

        using var appsettings = JsonDocument.Parse(File.ReadAllText(appsettingsPath));
        var videoImport = appsettings.RootElement.GetProperty("VideoImport");
        var maximumFileSizeBytes = videoImport.GetProperty("MaximumFileSizeBytes").GetInt64();
        var multipartOverheadBytes = videoImport.GetProperty("MultipartOverheadBytes").GetInt64();
        var maximumRequestBytes = checked(maximumFileSizeBytes + multipartOverheadBytes);

        var document = XDocument.Load(webConfigPath);
        var requestLimits = document.Descendants("requestLimits").Single();
        var maxAllowedContentLength = long.Parse(
            requestLimits.Attribute("maxAllowedContentLength")?.Value
                ?? throw new InvalidOperationException("IIS maxAllowedContentLength is required."),
            System.Globalization.CultureInfo.InvariantCulture);

        Assert.Equal(3L * 1024 * 1024 * 1024, maximumFileSizeBytes);
        Assert.Equal(1024L * 1024, multipartOverheadBytes);
        Assert.True(maxAllowedContentLength >= maximumRequestBytes,
            $"IIS limit {maxAllowedContentLength} is smaller than application request limit {maximumRequestBytes}.");
        Assert.True(maxAllowedContentLength <= uint.MaxValue,
            "IIS maxAllowedContentLength cannot exceed its unsigned 32-bit ceiling.");
    }

    [Fact]
    public void MissingDatabaseConnectionFailsClearly()
    {
        var configuration = new ConfigurationBuilder().AddInMemoryCollection().Build();
        var exception = Assert.Throws<InvalidOperationException>(() =>
            new ServiceCollection().AddMaviInfrastructure(configuration));
        Assert.Contains("Connection string 'Mavi' is required", exception.Message, StringComparison.Ordinal);
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "MAVI.sln")))
                return directory.FullName;

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("MAVI repository root could not be located.");
    }

    // Test host
    private static ServiceProvider BuildProvider(Dictionary<string, string?>? overrides = null, string? baseFile = null)
    {
        var values = new Dictionary<string, string?>
        {
            ["ConnectionStrings:Mavi"] = "Host=localhost;Database=mavi_test;Username=postgres",
            ["MediaStorage:RootPath"] = Path.Combine(Path.GetTempPath(), "mavi-config-media"),
            ["MediaStorage:EvidenceRootPath"] = Path.Combine(Path.GetTempPath(), "mavi-config-evidence"),
            ["MediaProcessing:FfprobePath"] = "ffprobe",
            ["MediaProcessing:FfmpegPath"] = "ffmpeg",
            ["MediaProcessing:ProbeTimeoutSeconds"] = "30",
            ["VideoImport:MaximumFileSizeBytes"] = "3221225472",
            ["VideoImport:MultipartOverheadBytes"] = "1048576",
            ["VideoImport:AllowedExtensions:0"] = ".mp4",
            ["Localization:DefaultDisplayTimeZoneId"] = "Asia/Kolkata",
            ["VisionProcessing:Pipeline"] = "phase1-detection-tracking",
            ["VisionProcessing:PipelineVersion"] = "phase1-v1",
            ["VisionProcessing:MaximumAttempts"] = "3",
            ["VisionProcessing:LeaseSeconds"] = "120",
            ["VisionProcessing:HeartbeatExtensionSeconds"] = "120",
            ["TrackSearch:CursorSigningKey"] = ApiTestFactory.DefaultCursorSigningKey,
        };
        if (overrides is not null)
        {
            foreach (var pair in overrides) values[pair.Key] = pair.Value;
        }

        // The optional base file is layered first, as appsettings.json is in the host; these
        // values carry no VisionFinalization key, so the file's section stands unless overridden.
        var builder = new ConfigurationBuilder();
        if (baseFile is not null) builder.AddJsonFile(baseFile, optional: false, reloadOnChange: false);
        var configuration = builder.AddInMemoryCollection(values).Build();
        return new ServiceCollection().AddLogging().AddMaviInfrastructure(configuration).BuildServiceProvider();
    }
}
