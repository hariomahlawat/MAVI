using System.Diagnostics;
using Mavi.Application.Modules.Media;
using Mavi.Infrastructure.Media;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

public sealed class FfprobeVideoMetadataReaderTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"mavi-ffprobe-{Guid.NewGuid():N}");

    // Real executable integration
    [Fact]
    public async Task GeneratedVideoReturnsAuthoritativeMetadata()
    {
        Directory.CreateDirectory(_root);
        var videoPath = Path.Combine(_root, "test.mp4");
        await GenerateVideoAsync(videoPath);
        var reader = CreateReader();

        var metadata = await reader.ReadAsync("test.mp4", CancellationToken.None);

        Assert.InRange(metadata.DurationMs, 900, 1_100);
        Assert.Equal(160, metadata.Width);
        Assert.Equal(90, metadata.Height);
        Assert.Equal(25, metadata.FrameRateNumerator);
        Assert.Equal(1, metadata.FrameRateDenominator);
        Assert.False(string.IsNullOrWhiteSpace(metadata.CodecName));
    }

    [Fact]
    public async Task MalformedInputIsRejected()
    {
        Directory.CreateDirectory(_root);
        await File.WriteAllTextAsync(Path.Combine(_root, "not-video.mp4"), "not video");
        var reader = CreateReader();

        await Assert.ThrowsAsync<VideoMetadataException>(() =>
            reader.ReadAsync("not-video.mp4", CancellationToken.None));
    }

    [Fact]
    public async Task MissingStorageKeyIsRejected()
    {
        var reader = CreateReader();

        await Assert.ThrowsAsync<FileNotFoundException>(() =>
            reader.ReadAsync("missing.mp4", CancellationToken.None));
    }

    [Fact]
    public async Task InvalidExecutableProducesControlledFailure()
    {
        Directory.CreateDirectory(_root);
        await File.WriteAllTextAsync(Path.Combine(_root, "video.mp4"), "content");
        var reader = CreateReader("ffprobe-does-not-exist-mavi");

        await Assert.ThrowsAsync<VideoMetadataException>(() =>
            reader.ReadAsync("video.mp4", CancellationToken.None));
    }

    [Fact]
    public async Task PreCancelledRequestDoesNotStartProbe()
    {
        Directory.CreateDirectory(_root);
        await File.WriteAllTextAsync(Path.Combine(_root, "video.mp4"), "content");
        var reader = CreateReader();
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            reader.ReadAsync("video.mp4", cancellation.Token));
    }

    // Test infrastructure
    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, true);
        GC.SuppressFinalize(this);
    }

    private FfprobeVideoMetadataReader CreateReader(string executable = "ffprobe")
    {
        var store = new LocalMediaStore(Options.Create(new MediaStorageOptions { RootPath = _root }));
        return new FfprobeVideoMetadataReader(
            store,
            Options.Create(new MediaProcessingOptions { FfprobePath = executable }),
            NullLogger<FfprobeVideoMetadataReader>.Instance);
    }

    private static async Task GenerateVideoAsync(string outputPath)
    {
        using var process = Process.Start(new ProcessStartInfo
        {
            FileName = "ffmpeg",
            UseShellExecute = false,
            RedirectStandardError = true,
        }.AddArguments("-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25", "-t", "1", "-pix_fmt", "yuv420p", outputPath))!;
        var error = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        Assert.True(process.ExitCode == 0, error);
    }
}

internal static class ProcessStartInfoTestExtensions
{
    public static ProcessStartInfo AddArguments(this ProcessStartInfo startInfo, params string[] arguments)
    {
        foreach (var argument in arguments) startInfo.ArgumentList.Add(argument);
        return startInfo;
    }
}
