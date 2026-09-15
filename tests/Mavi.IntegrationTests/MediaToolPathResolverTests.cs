using Mavi.Infrastructure.Media;

namespace Mavi.IntegrationTests;

public sealed class MediaToolPathResolverTests
{
    [Fact]
    public void ConfiguredPathIsUsedWhenBundleIsAbsent()
    {
        var configured = Path.GetFullPath(
            Path.Combine(
                Path.GetTempPath(),
                $"mavi-ffprobe-{Guid.NewGuid():N}",
                OperatingSystem.IsWindows() ? "ffprobe.exe" : "ffprobe"));
        var options = new MediaProcessingOptions
        {
            FfprobePath = configured,
            BundledRootPath = Path.Combine(
                "tools",
                $"missing-{Guid.NewGuid():N}"),
        };

        var resolved = MediaToolPathResolver.ResolveFfprobePath(options);

        Assert.Equal(configured, resolved);
    }

    [Fact]
    public void BundledExecutablePathUsesCurrentRuntime()
    {
        var options = new MediaProcessingOptions
        {
            BundledRootPath = "tools/ffmpeg",
        };

        var path = MediaToolPathResolver.BundledExecutablePath(
            options,
            "ffprobe");

        Assert.Contains(
            MediaToolPathResolver.CurrentRuntimeId(),
            path,
            StringComparison.Ordinal);
        Assert.EndsWith(
            OperatingSystem.IsWindows() ? "ffprobe.exe" : "ffprobe",
            path,
            StringComparison.OrdinalIgnoreCase);
    }
}
