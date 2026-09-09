using Mavi.Application.Modules.Media;
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
    }

    // Invalid configuration
    [Theory]
    [InlineData("MediaStorage:RootPath", "")]
    [InlineData("MediaProcessing:FfprobePath", " ")]
    [InlineData("MediaProcessing:ProbeTimeoutSeconds", "0")]
    [InlineData("MediaProcessing:ProbeTimeoutSeconds", "301")]
    [InlineData("VideoImport:MaximumFileSizeBytes", "0")]
    public void InvalidConfigurationIsRejected(string key, string value)
    {
        using var provider = BuildProvider(new Dictionary<string, string?> { [key] = value });

        Assert.Throws<OptionsValidationException>(() =>
        {
            _ = provider.GetRequiredService<IOptions<MediaStorageOptions>>().Value;
            _ = provider.GetRequiredService<IOptions<MediaProcessingOptions>>().Value;
            _ = provider.GetRequiredService<IOptions<VideoImportOptions>>().Value;
        });
    }

    [Fact]
    public void ApplicationContractsDoNotExposePhysicalRootPath()
    {
        var applicationAssembly = typeof(VideoMetadata).Assembly;

        Assert.DoesNotContain(applicationAssembly.GetExportedTypes(), type =>
            type.GetProperties().Any(property => property.Name == "RootPath"));
    }

    // Test host
    private static ServiceProvider BuildProvider(Dictionary<string, string?>? overrides = null)
    {
        var values = new Dictionary<string, string?>
        {
            ["ConnectionStrings:Mavi"] = "Host=localhost;Database=mavi_test;Username=postgres",
            ["MediaStorage:RootPath"] = Path.GetTempPath(),
            ["MediaProcessing:FfprobePath"] = "ffprobe",
            ["MediaProcessing:FfmpegPath"] = "ffmpeg",
            ["MediaProcessing:ProbeTimeoutSeconds"] = "30",
            ["VideoImport:MaximumFileSizeBytes"] = "10737418240",
            ["VideoImport:AllowedExtensions:0"] = ".mp4",
        };
        if (overrides is not null)
        {
            foreach (var pair in overrides) values[pair.Key] = pair.Value;
        }

        var configuration = new ConfigurationBuilder().AddInMemoryCollection(values).Build();
        return new ServiceCollection().AddLogging().AddMaviInfrastructure(configuration).BuildServiceProvider();
    }
}
