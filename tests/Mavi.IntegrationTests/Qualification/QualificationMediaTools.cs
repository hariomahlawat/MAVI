using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Infrastructure.Media;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// Resolves the approved repository-local FFmpeg pack for qualification harnesses.
/// PATH fallback is deliberately forbidden so a qualification run cannot succeed
/// because of ambient machine configuration.
/// </summary>
internal static class QualificationMediaTools
{
    public static string ResolveBundledFfmpeg(string repositoryRoot)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(repositoryRoot);

        var bundleRoot = Path.GetFullPath(Path.Combine(repositoryRoot, "vendor", "ffmpeg"));
        var manifestPath = Path.Combine(bundleRoot, "manifest.json");
        if (!File.Exists(manifestPath))
            throw new InvalidOperationException($"Approved FFmpeg manifest is missing: {manifestPath}");

        var options = new MediaProcessingOptions
        {
            // A sentinel makes any resolver fallback observable and therefore fatal.
            FfmpegPath = "__mavi_qualification_path_fallback_forbidden__",
            BundledRootPath = bundleRoot,
        };
        var expected = MediaToolPathResolver.BundledExecutablePath(options, "ffmpeg");
        var resolved = MediaToolPathResolver.ResolveFfmpegPath(options);
        if (!string.Equals(resolved, expected, StringComparison.OrdinalIgnoreCase) || !File.Exists(expected))
            throw new InvalidOperationException($"Approved bundled FFmpeg executable is missing: {expected}");

        VerifyManifest(manifestPath, expected);
        return expected;
    }

    private static void VerifyManifest(string manifestPath, string executablePath)
    {
        // Windows PowerShell 5.1 writes UTF-8 files with a BOM. Read as text so the BOM is decoded rather than presented to Utf8JsonReader as payload bytes.
        var manifestText = File.ReadAllText(manifestPath, Encoding.UTF8);
        using var document = JsonDocument.Parse(manifestText);
        var root = document.RootElement;
        if (root.GetProperty("schemaVersion").GetString() != "1.0")
            throw new InvalidOperationException("Approved FFmpeg manifest schema is invalid.");
        if (root.GetProperty("runtimeId").GetString() != MediaToolPathResolver.CurrentRuntimeId())
            throw new InvalidOperationException("Approved FFmpeg manifest runtime does not match this host.");

        var fileName = Path.GetFileName(executablePath);
        JsonElement? artifact = null;
        foreach (var candidate in root.GetProperty("artifacts").EnumerateArray())
        {
            if (string.Equals(candidate.GetProperty("fileName").GetString(), fileName, StringComparison.OrdinalIgnoreCase))
            {
                artifact = candidate;
                break;
            }
        }

        if (artifact is null)
            throw new InvalidOperationException($"Approved FFmpeg manifest does not declare {fileName}.");

        var expectedSha = artifact.Value.GetProperty("sha256").GetString();
        if (string.IsNullOrWhiteSpace(expectedSha) || expectedSha.Length != 64 ||
            expectedSha.Any(c => c is not (>= '0' and <= '9') and not (>= 'a' and <= 'f')))
            throw new InvalidOperationException($"Approved FFmpeg manifest SHA-256 for {fileName} is invalid.");

        using var stream = File.OpenRead(executablePath);
        var actualSha = Convert.ToHexStringLower(SHA256.HashData(stream));
        if (!string.Equals(actualSha, expectedSha, StringComparison.Ordinal))
            throw new InvalidOperationException($"Approved FFmpeg executable {fileName} failed SHA-256 verification.");
    }
}
