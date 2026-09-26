using System.Security.Cryptography;
using System.Text.Json;
using Mavi.Infrastructure.Media;

namespace Mavi.IntegrationTests.Qualification;

public sealed class QualificationMediaToolsTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"mavi-qual-media-{Guid.NewGuid():N}");

    public QualificationMediaToolsTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, recursive: true);
    }

    [Fact]
    public void ResolvesOnlyTheRepositoryBundledFfmpeg()
    {
        var expected = StageBundle(validHash: true, runtimeId: MediaToolPathResolver.CurrentRuntimeId());

        var resolved = QualificationMediaTools.ResolveBundledFfmpeg(_root);

        Assert.True(string.Equals(expected, resolved, OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal), $"{resolved} != {expected}");
        Assert.DoesNotContain("__mavi_qualification_path_fallback_forbidden__", resolved, StringComparison.Ordinal);
    }

    [Fact]
    public void MissingBundleIsRefusedRatherThanFallingBackToPath()
    {
        var exception = Assert.Throws<InvalidOperationException>(() => QualificationMediaTools.ResolveBundledFfmpeg(_root));
        Assert.Contains("manifest is missing", exception.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void ManifestHashMismatchIsRefused()
    {
        StageBundle(validHash: false, runtimeId: MediaToolPathResolver.CurrentRuntimeId());

        var exception = Assert.Throws<InvalidOperationException>(() => QualificationMediaTools.ResolveBundledFfmpeg(_root));

        Assert.Contains("failed SHA-256 verification", exception.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void WrongRuntimeManifestIsRefused()
    {
        StageBundle(validHash: true, runtimeId: "wrong-runtime");

        var exception = Assert.Throws<InvalidOperationException>(() => QualificationMediaTools.ResolveBundledFfmpeg(_root));

        Assert.Contains("runtime does not match", exception.Message, StringComparison.Ordinal);
    }

    private string StageBundle(bool validHash, string runtimeId)
    {
        var bundle = Path.Combine(_root, "vendor", "ffmpeg");
        var runtime = Path.Combine(bundle, MediaToolPathResolver.CurrentRuntimeId());
        Directory.CreateDirectory(runtime);
        var executable = Path.Combine(runtime, OperatingSystem.IsWindows() ? "ffmpeg.exe" : "ffmpeg");
        var bytes = "qualification-ffmpeg"u8.ToArray();
        File.WriteAllBytes(executable, bytes);
        var sha = Convert.ToHexStringLower(SHA256.HashData(bytes));
        if (!validHash) sha = new string('0', 64);

        var manifest = new
        {
            schemaVersion = "1.0",
            runtimeId,
            version = "test",
            artifacts = new[] { new { fileName = Path.GetFileName(executable), sha256 = sha } },
        };
        File.WriteAllText(Path.Combine(bundle, "manifest.json"), JsonSerializer.Serialize(manifest));
        return Path.GetFullPath(executable);
    }
}
