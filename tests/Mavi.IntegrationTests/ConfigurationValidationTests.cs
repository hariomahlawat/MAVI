using System.Text.Json;
using System.Xml.Linq;
using Mavi.Application.Modules.Media;
using Mavi.Application;
using Mavi.Infrastructure;
using Mavi.Infrastructure.Media;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Mavi.Application.Modules.Intelligence;

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
    [InlineData("VisionProcessing:Pipeline", "")]
    [InlineData("VisionProcessing:PipelineVersion", "")]
    [InlineData("VisionProcessing:MaximumAttempts", "0")]
    [InlineData("VisionProcessing:LeaseSeconds", "0")]
    [InlineData("VisionProcessing:HeartbeatExtensionSeconds", "0")]
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
        });
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
    private static ServiceProvider BuildProvider(Dictionary<string, string?>? overrides = null)
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
        };
        if (overrides is not null)
        {
            foreach (var pair in overrides) values[pair.Key] = pair.Value;
        }

        var configuration = new ConfigurationBuilder().AddInMemoryCollection(values).Build();
        return new ServiceCollection().AddLogging().AddMaviInfrastructure(configuration).BuildServiceProvider();
    }
}
