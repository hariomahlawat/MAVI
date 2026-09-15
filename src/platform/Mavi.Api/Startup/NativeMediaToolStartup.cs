using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using Mavi.Infrastructure.Media;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Startup;

public static class NativeMediaToolStartup
{
    private static readonly JsonSerializerOptions ManifestJsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    private static readonly Action<ILogger, string, string, Exception?> LogBundledToolVerified =
        LoggerMessage.Define<string, string>(
            LogLevel.Information,
            new EventId(1700, "BundledMediaToolVerified"),
            "Verified bundled media tool {ToolName} at {ToolPath}.");

    private static readonly Action<ILogger, string, Exception?> LogDevelopmentFallback =
        LoggerMessage.Define<string>(
            LogLevel.Warning,
            new EventId(1701, "MediaToolDevelopmentFallback"),
            "Bundled media tools are unavailable; Development is using PATH fallback '{ToolPath}'. This fallback is not accepted for production qualification.");

    public static async Task VerifyNativeMediaToolsAsync(
        this WebApplication app,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(app);

        await using var scope = app.Services.CreateAsyncScope();
        var options = scope.ServiceProvider
            .GetRequiredService<IOptions<MediaProcessingOptions>>()
            .Value;
        if (!options.VerifyOnStartup)
            return;

        var logger = scope.ServiceProvider
            .GetRequiredService<ILoggerFactory>()
            .CreateLogger("Mavi.NativeMediaTools");

        var ffprobe = MediaToolPathResolver.ResolveFfprobePath(options);
        var ffmpeg = MediaToolPathResolver.ResolveFfmpegPath(options);

        var bundledFfprobe = MediaToolPathResolver.BundledExecutablePath(
            options,
            "ffprobe");
        var bundledFfmpeg = MediaToolPathResolver.BundledExecutablePath(
            options,
            "ffmpeg");
        var usingBundle =
            string.Equals(ffprobe, bundledFfprobe, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(ffmpeg, bundledFfmpeg, StringComparison.OrdinalIgnoreCase);

        MediaToolManifest? manifest = null;
        if (usingBundle)
        {
            manifest = await VerifyManifestAsync(
                options,
                ffprobe,
                ffmpeg,
                cancellationToken);
            LogBundledToolVerified(logger, "ffprobe", ffprobe, null);
            LogBundledToolVerified(logger, "ffmpeg", ffmpeg, null);
        }
        else
        {
            if (!app.Environment.IsDevelopment() ||
                !options.AllowPathFallbackInDevelopment)
            {
                throw new InvalidOperationException(
                    "MAVI requires bundled FFmpeg/ffprobe tools outside Development.");
            }

            LogDevelopmentFallback(logger, ffprobe, null);
        }

        var ffprobeVersion = await VerifyExecutableAsync(
            ffprobe,
            cancellationToken);
        var ffmpegVersion = await VerifyExecutableAsync(
            ffmpeg,
            cancellationToken);

        if (manifest is not null)
        {
            VerifyDeclaredVersion(manifest.Version, "ffprobe", ffprobeVersion);
            VerifyDeclaredVersion(manifest.Version, "ffmpeg", ffmpegVersion);
        }
    }

    private static async Task<MediaToolManifest> VerifyManifestAsync(
        MediaProcessingOptions options,
        string ffprobePath,
        string ffmpegPath,
        CancellationToken cancellationToken)
    {
        var manifestPath = Path.GetFullPath(
            Path.Combine(
                AppContext.BaseDirectory,
                options.BundledManifestPath));
        if (!File.Exists(manifestPath))
        {
            throw new InvalidOperationException(
                $"Bundled media-tool manifest was not found at '{manifestPath}'.");
        }

        await using var stream = File.OpenRead(manifestPath);
        var manifest = await JsonSerializer.DeserializeAsync<MediaToolManifest>(
            stream,
            ManifestJsonOptions,
            cancellationToken)
            ?? throw new InvalidOperationException(
                "Bundled media-tool manifest is invalid.");

        if (!string.Equals(manifest.SchemaVersion, "1.0", StringComparison.Ordinal) ||
            string.IsNullOrWhiteSpace(manifest.Version) ||
            manifest.Artifacts is not { Length: > 0 })
        {
            throw new InvalidOperationException(
                "Bundled media-tool manifest has an unsupported schema or missing required data.");
        }

        if (!string.Equals(
                manifest.RuntimeId,
                MediaToolPathResolver.CurrentRuntimeId(),
                StringComparison.Ordinal))
        {
            throw new InvalidOperationException(
                "Bundled media-tool manifest runtime does not match this host.");
        }

        VerifyArtifact(manifest, ffprobePath);
        VerifyArtifact(manifest, ffmpegPath);
        return manifest;
    }

    private static void VerifyDeclaredVersion(
        string declaredVersion,
        string toolName,
        string versionOutput)
    {
        if (versionOutput.IndexOf(
                declaredVersion,
                StringComparison.OrdinalIgnoreCase) < 0)
        {
            throw new InvalidOperationException(
                $"Bundled media tool '{toolName}' does not report declared version '{declaredVersion}'.");
        }
    }

    private static void VerifyArtifact(
        MediaToolManifest manifest,
        string executablePath)
    {
        var name = Path.GetFileName(executablePath);
        var artifact = manifest.Artifacts.SingleOrDefault(
            value => string.Equals(
                value.FileName,
                name,
                StringComparison.OrdinalIgnoreCase));
        if (artifact is null ||
            string.IsNullOrWhiteSpace(artifact.Sha256) ||
            artifact.Sha256.Length != 64 ||
            artifact.Sha256.Any(character =>
                character is not (>= '0' and <= '9') and
                not (>= 'a' and <= 'f')))
        {
            throw new InvalidOperationException(
                $"Bundled media-tool manifest has no valid lowercase SHA-256 for '{name}'.");
        }

        using var file = File.OpenRead(executablePath);
        var actual = Convert.ToHexString(SHA256.HashData(file))
            .ToLowerInvariant();
        if (!string.Equals(actual, artifact.Sha256, StringComparison.Ordinal))
        {
            throw new InvalidOperationException(
                $"Bundled media tool '{name}' failed SHA-256 verification.");
        }
    }

    private static async Task<string> VerifyExecutableAsync(
        string executable,
        CancellationToken cancellationToken)
    {
        using var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = executable,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            },
        };
        process.StartInfo.ArgumentList.Add("-version");

        try
        {
            if (!process.Start())
                throw new InvalidOperationException(
                    $"Media tool '{executable}' could not be started.");
        }
        catch (Exception exception) when (
            exception is not InvalidOperationException)
        {
            throw new InvalidOperationException(
                $"MAVI media prerequisite '{executable}' is unavailable.",
                exception);
        }

        var standardOutput = process.StandardOutput.ReadToEndAsync(
            cancellationToken);
        var standardError = process.StandardError.ReadToEndAsync(
            cancellationToken);

        using var timeout = CancellationTokenSource
            .CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(10));

        try
        {
            await process.WaitForExitAsync(timeout.Token);
        }
        catch (OperationCanceledException) when (
            !cancellationToken.IsCancellationRequested)
        {
            if (!process.HasExited)
                process.Kill(entireProcessTree: true);
            throw new InvalidOperationException(
                $"MAVI media prerequisite '{executable}' did not respond to a version check.");
        }

        var output = await standardOutput;
        var error = await standardError;
        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException(
                $"MAVI media prerequisite '{executable}' failed its version check.");
        }

        var versionOutput = string.IsNullOrWhiteSpace(output)
            ? error
            : output;
        if (string.IsNullOrWhiteSpace(versionOutput))
        {
            throw new InvalidOperationException(
                $"MAVI media prerequisite '{executable}' returned no version identity.");
        }

        return versionOutput;
    }

    private sealed record MediaToolManifest(
        string SchemaVersion,
        string RuntimeId,
        string Version,
        MediaToolArtifact[] Artifacts);

    private sealed record MediaToolArtifact(
        string FileName,
        string Sha256);
}
