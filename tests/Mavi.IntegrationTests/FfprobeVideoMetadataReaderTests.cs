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
        Assert.Contains("mp4", metadata.FormatName.Split(','), StringComparer.OrdinalIgnoreCase);
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

    [Fact]
    public async Task InvalidFormatDurationFallsBackToVideoStreamDuration()
    {
        Directory.CreateDirectory(_root);
        await File.WriteAllTextAsync(Path.Combine(_root, "video.mp4"), "content");
        var executable = await CreateExecutableAsync(
            "printf '%s' '{\"streams\":[{\"codec_type\":\"video\",\"codec_name\":\"h264\",\"width\":160,\"height\":90,\"avg_frame_rate\":\"25/1\",\"duration\":\"2.5\"}],\"format\":{\"duration\":\"N/A\",\"format_name\":\"mp4\"}}'");
        var reader = CreateReader(executable);

        var metadata = await reader.ReadAsync("video.mp4", CancellationToken.None);

        Assert.Equal(2_500, metadata.DurationMs);
    }

    [Fact]
    public async Task ConfiguredProbeTimeoutIsApplied()
    {
        Directory.CreateDirectory(_root);
        await File.WriteAllTextAsync(Path.Combine(_root, "video.mp4"), "content");
        var executable = await CreateExecutableAsync("sleep 5");
        var reader = CreateReader(executable, timeoutSeconds: 1);

        var exception = await Assert.ThrowsAsync<VideoMetadataException>(() =>
            reader.ReadAsync("video.mp4", CancellationToken.None));

        Assert.Contains("configured metadata timeout", exception.Message, StringComparison.Ordinal);
    }

    // Test infrastructure
    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, true);
        GC.SuppressFinalize(this);
    }

    private FfprobeVideoMetadataReader CreateReader(string executable = "ffprobe", int timeoutSeconds = 30)
    {
        var store = new LocalMediaStore(Options.Create(new MediaStorageOptions { RootPath = _root }));
        return new FfprobeVideoMetadataReader(
            store,
            Options.Create(new MediaProcessingOptions { FfprobePath = executable, ProbeTimeoutSeconds = timeoutSeconds }),
            NullLogger<FfprobeVideoMetadataReader>.Instance);
    }

    private async Task<string> CreateExecutableAsync(string body)
    {
        if (OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException("Synthetic ffprobe scripts are used only on Unix test hosts.");
        }

        var executable = Path.Combine(_root, $"probe-{Guid.NewGuid():N}.sh");
        await File.WriteAllTextAsync(executable, $"#!/bin/sh\n{body}\n");
        File.SetUnixFileMode(executable, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        return executable;
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
