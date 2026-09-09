using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using Mavi.Application.Modules.Media;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Media;

internal sealed class FfprobeVideoMetadataReader(
    ILocalMediaPathResolver pathResolver,
    IOptions<MediaProcessingOptions> options,
    ILogger<FfprobeVideoMetadataReader> logger) : IVideoMetadataReader
{
    private static readonly Action<ILogger, int, string, Exception?> LogProbeFailure =
        LoggerMessage.Define<int, string>(
            LogLevel.Warning,
            new EventId(1, nameof(LogProbeFailure)),
            "ffprobe exited with code {ExitCode}: {Diagnostic}");

    // Metadata extraction
    public async Task<VideoMetadata> ReadAsync(string storageKey, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var localPath = pathResolver.ResolveLocalPath(storageKey);
        if (!File.Exists(localPath))
        {
            throw new FileNotFoundException("Managed media was not found for the supplied storage key.");
        }

        using var process = new Process { StartInfo = CreateStartInfo(options.Value.FfprobePath, localPath) };
        try
        {
            if (!process.Start()) throw new VideoMetadataException("ffprobe could not be started.");
        }
        catch (Exception exception) when (exception is not VideoMetadataException)
        {
            throw new VideoMetadataException("ffprobe could not be started.", exception);
        }

        var standardOutput = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var standardError = process.StandardError.ReadToEndAsync(cancellationToken);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(options.Value.ProbeTimeoutSeconds));
        using var linkedCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeout.Token);
        try
        {
            await process.WaitForExitAsync(linkedCancellation.Token);
        }
        catch (OperationCanceledException) when (timeout.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
        {
            KillProcess(process);
            await ObserveOutputAsync(standardOutput, standardError);
            throw new VideoMetadataException("ffprobe exceeded the configured metadata timeout.");
        }
        catch (OperationCanceledException)
        {
            KillProcess(process);
            await ObserveOutputAsync(standardOutput, standardError);
            throw;
        }

        var output = await standardOutput;
        var error = await standardError;
        if (process.ExitCode != 0)
        {
            LogProbeFailure(logger, process.ExitCode, error, null);
            throw new VideoMetadataException("ffprobe rejected the managed media.");
        }

        return ParseMetadata(output);
    }

    // Process management
    private static ProcessStartInfo CreateStartInfo(string executable, string localPath)
    {
        if (string.IsNullOrWhiteSpace(executable))
        {
            throw new VideoMetadataException("MediaProcessing:FfprobePath is required.");
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        foreach (var argument in new[] { "-v", "error", "-print_format", "json", "-show_streams", "-show_format", localPath })
        {
            startInfo.ArgumentList.Add(argument);
        }

        return startInfo;
    }

    private static void KillProcess(Process process)
    {
        if (!process.HasExited) process.Kill(entireProcessTree: true);
    }

    private static async Task ObserveOutputAsync(Task<string> output, Task<string> error)
    {
        try { await Task.WhenAll(output, error); }
        catch (OperationCanceledException) { }
    }

    // JSON validation
    private static VideoMetadata ParseMetadata(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            if (!document.RootElement.TryGetProperty("streams", out var streams) ||
                streams.ValueKind != JsonValueKind.Array)
            {
                throw InvalidMetadata("ffprobe output did not contain a video stream.");
            }

            JsonElement? video = streams.EnumerateArray().FirstOrDefault(stream =>
                stream.TryGetProperty("codec_type", out var type) && type.GetString() == "video");
            if (video is null || video.Value.ValueKind == JsonValueKind.Undefined)
            {
                throw InvalidMetadata("ffprobe output did not contain a video stream.");
            }

            var stream = video.Value;
            var width = ReadPositiveInt(stream, "width");
            var height = ReadPositiveInt(stream, "height");
            var codec = ReadRequiredString(stream, "codec_name");
            var frameRate = ReadFrameRate(stream);
            var durationMs = ReadDurationMs(document.RootElement, stream);
            if (!document.RootElement.TryGetProperty("format", out var format))
                throw InvalidMetadata("ffprobe output did not contain format information.");
            var formatName = ReadRequiredString(format, "format_name");
            string? majorBrand = null;
            if (format.TryGetProperty("tags", out var tags) && tags.TryGetProperty("major_brand", out var brand))
                majorBrand = brand.GetString();
            return new VideoMetadata(durationMs, width, height, frameRate.Numerator, frameRate.Denominator, codec, formatName, majorBrand);
        }
        catch (JsonException exception)
        {
            throw new VideoMetadataException("ffprobe returned malformed JSON.", exception);
        }
        catch (OverflowException exception)
        {
            throw new VideoMetadataException("ffprobe returned metadata outside supported ranges.", exception);
        }
    }

    private static int ReadPositiveInt(JsonElement element, string propertyName)
    {
        if (!element.TryGetProperty(propertyName, out var property) ||
            !property.TryGetInt32(out var value) || value <= 0)
        {
            throw InvalidMetadata($"ffprobe returned an invalid {propertyName}.");
        }

        return value;
    }

    private static string ReadRequiredString(JsonElement element, string propertyName)
    {
        if (!element.TryGetProperty(propertyName, out var property) || string.IsNullOrWhiteSpace(property.GetString()))
        {
            throw InvalidMetadata($"ffprobe returned an invalid {propertyName}.");
        }

        return property.GetString()!;
    }

    private static (int Numerator, int Denominator) ReadFrameRate(JsonElement stream)
    {
        foreach (var propertyName in new[] { "avg_frame_rate", "r_frame_rate" })
        {
            if (stream.TryGetProperty(propertyName, out var property) &&
                TryParseRational(property.GetString(), out var rational))
            {
                return rational;
            }
        }

        throw InvalidMetadata("ffprobe returned no usable video frame rate.");
    }

    private static bool TryParseRational(string? value, out (int Numerator, int Denominator) rational)
    {
        rational = default;
        var parts = value?.Split('/');
        if (parts is not { Length: 2 } ||
            !int.TryParse(parts[0], NumberStyles.None, CultureInfo.InvariantCulture, out var numerator) ||
            !int.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out var denominator) ||
            numerator <= 0 || denominator <= 0)
        {
            return false;
        }

        var divisor = GreatestCommonDivisor(numerator, denominator);
        rational = (numerator / divisor, denominator / divisor);
        return true;
    }

    private static int GreatestCommonDivisor(int left, int right)
    {
        while (right != 0)
        {
            (left, right) = (right, left % right);
        }

        return left;
    }

    private static long ReadDurationMs(JsonElement root, JsonElement stream)
    {
        if (root.TryGetProperty("format", out var format) && format.TryGetProperty("duration", out var formatDuration))
        {
            if (TryReadDurationMs(formatDuration.GetString(), out var formatMilliseconds))
            {
                return formatMilliseconds;
            }
        }

        if (stream.TryGetProperty("duration", out var streamDuration) &&
            TryReadDurationMs(streamDuration.GetString(), out var streamMilliseconds))
        {
            return streamMilliseconds;
        }

        throw InvalidMetadata("ffprobe returned a non-positive duration.");
    }

    private static bool TryReadDurationMs(string? value, out long milliseconds)
    {
        milliseconds = 0;
        if (!decimal.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var seconds) || seconds <= 0)
        {
            return false;
        }

        milliseconds = checked((long)decimal.Round(seconds * 1000m, MidpointRounding.AwayFromZero));
        return milliseconds > 0;
    }

    private static VideoMetadataException InvalidMetadata(string message) => new(message);
}
