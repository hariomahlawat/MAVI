using System.Text.Json;
using Mavi.Infrastructure;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

public sealed class AcceptedEvidenceConfigurationTests
{
    [Fact]
    public void DevelopmentConfigurationDeclaresDisjointEvidenceRoot()
    {
        var repositoryRoot = Path.GetFullPath(Path.Combine(
            AppContext.BaseDirectory,
            "..", "..", "..", "..", ".."));
        var path = Path.Combine(
            repositoryRoot,
            "src",
            "platform",
            "Mavi.Api",
            "appsettings.Development.json");

        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var media = document.RootElement.GetProperty("MediaStorage");
        var root = media.GetProperty("RootPath").GetString();
        var evidenceRoot = media.GetProperty("EvidenceRootPath").GetString();

        Assert.False(string.IsNullOrWhiteSpace(root));
        Assert.False(string.IsNullOrWhiteSpace(evidenceRoot));
        Assert.NotEqual(
            Path.GetFullPath(root!),
            Path.GetFullPath(evidenceRoot!));
    }

    [Fact]
    public void SymlinkedEvidenceRootIntoWorkerWritableMediaRootIsRejected()
    {
        var testRoot = Path.Combine(
            Path.GetTempPath(),
            $"mavi-root-isolation-{Guid.NewGuid():N}");
        var mediaRoot = Path.Combine(testRoot, "media");
        var workerWritableTarget = Path.Combine(mediaRoot, "accepted-via-link");
        var evidenceLink = Path.Combine(testRoot, "evidence-link");

        Directory.CreateDirectory(workerWritableTarget);
        try
        {
            try
            {
                Directory.CreateSymbolicLink(evidenceLink, workerWritableTarget);
            }
            catch (Exception exception) when (
                OperatingSystem.IsWindows() &&
                exception is UnauthorizedAccessException or IOException)
            {
                return;
            }

            var configuration = BuildConfiguration(mediaRoot, evidenceLink);
            using var provider = new ServiceCollection()
                .AddLogging()
                .AddMaviInfrastructure(configuration)
                .BuildServiceProvider();

            Assert.Throws<OptionsValidationException>(() =>
                _ = provider.GetRequiredService<IOptions<MediaStorageOptions>>().Value);
        }
        finally
        {
            if (Directory.Exists(evidenceLink)) Directory.Delete(evidenceLink);
            if (Directory.Exists(testRoot)) Directory.Delete(testRoot, true);
        }
    }

    [Fact]
    public void AcceptedEvidenceStoreRejectsLinkedEvidenceRootEvenWithoutOptionsPipeline()
    {
        var testRoot = Path.Combine(
            Path.GetTempPath(),
            $"mavi-store-root-isolation-{Guid.NewGuid():N}");
        var mediaRoot = Path.Combine(testRoot, "media");
        var workerWritableTarget = Path.Combine(mediaRoot, "accepted-via-link");
        var evidenceLink = Path.Combine(testRoot, "evidence-link");

        Directory.CreateDirectory(workerWritableTarget);
        try
        {
            try
            {
                Directory.CreateSymbolicLink(evidenceLink, workerWritableTarget);
            }
            catch (Exception exception) when (
                OperatingSystem.IsWindows() &&
                exception is UnauthorizedAccessException or IOException)
            {
                return;
            }

            var options = Options.Create(new MediaStorageOptions
            {
                RootPath = mediaRoot,
                EvidenceRootPath = evidenceLink,
            });
            var mediaStore = new LocalMediaStore(options);

            Assert.Throws<InvalidOperationException>(() =>
                new AcceptedEvidenceStore(mediaStore, options));
        }
        finally
        {
            if (Directory.Exists(evidenceLink)) Directory.Delete(evidenceLink);
            if (Directory.Exists(testRoot)) Directory.Delete(testRoot, true);
        }
    }

    private static IConfiguration BuildConfiguration(
        string mediaRoot,
        string evidenceRoot) =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["ConnectionStrings:Mavi"] =
                    "Host=localhost;Database=mavi_test;Username=postgres",
                ["MediaStorage:RootPath"] = mediaRoot,
                ["MediaStorage:EvidenceRootPath"] = evidenceRoot,
                ["MediaProcessing:FfprobePath"] = "ffprobe",
                ["MediaProcessing:FfmpegPath"] = "ffmpeg",
                ["MediaProcessing:ProbeTimeoutSeconds"] = "30",
                ["VideoImport:MaximumFileSizeBytes"] = "10737418240",
                ["VideoImport:MultipartOverheadBytes"] = "1048576",
                ["VideoImport:AllowedExtensions:0"] = ".mp4",
                ["Localization:DefaultDisplayTimeZoneId"] = "Asia/Kolkata",
                ["VisionProcessing:Pipeline"] = "phase1-detection-tracking",
                ["VisionProcessing:PipelineVersion"] = "phase1-v1",
                ["VisionProcessing:MaximumAttempts"] = "3",
                ["VisionProcessing:LeaseSeconds"] = "120",
                ["VisionProcessing:HeartbeatExtensionSeconds"] = "120",
            })
            .Build();
}
