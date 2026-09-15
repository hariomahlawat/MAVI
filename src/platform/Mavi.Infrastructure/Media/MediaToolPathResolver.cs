using System.Runtime.InteropServices;
namespace Mavi.Infrastructure.Media;

public static class MediaToolPathResolver
{
    public static string ResolveFfprobePath(MediaProcessingOptions options) =>
        Resolve(options, options.FfprobePath, "ffprobe");

    public static string ResolveFfmpegPath(MediaProcessingOptions options) =>
        Resolve(options, options.FfmpegPath, "ffmpeg");

    public static string CurrentRuntimeId()
    {
        var architecture = RuntimeInformation.OSArchitecture switch
        {
            Architecture.X64 => "x64",
            _ => throw new PlatformNotSupportedException(
                $"Unsupported MAVI native-tool architecture: {RuntimeInformation.OSArchitecture}."),
        };

        if (OperatingSystem.IsWindows())
            return $"win-{architecture}";
        if (OperatingSystem.IsLinux())
            return $"linux-{architecture}";

        throw new PlatformNotSupportedException(
            "MAVI media tooling is supported only on Windows and Linux.");
    }

    public static string BundledExecutablePath(
        MediaProcessingOptions options,
        string toolName)
    {
        ArgumentNullException.ThrowIfNull(options);
        if (string.IsNullOrWhiteSpace(toolName))
            throw new ArgumentException("Tool name is required.", nameof(toolName));

        var executable = OperatingSystem.IsWindows()
            ? $"{toolName}.exe"
            : toolName;
        return Path.GetFullPath(
            Path.Combine(
                AppContext.BaseDirectory,
                options.BundledRootPath,
                CurrentRuntimeId(),
                executable));
    }

    private static string Resolve(
        MediaProcessingOptions options,
        string configuredPath,
        string toolName)
    {
        var bundled = BundledExecutablePath(options, toolName);
        if (File.Exists(bundled))
            return bundled;

        if (string.IsNullOrWhiteSpace(configuredPath))
            throw new InvalidOperationException(
                $"MediaProcessing path for '{toolName}' is not configured.");

        if (Path.IsPathRooted(configuredPath))
            return configuredPath;

        if (configuredPath.Contains(Path.DirectorySeparatorChar) ||
            configuredPath.Contains(Path.AltDirectorySeparatorChar))
        {
            return Path.GetFullPath(
                Path.Combine(AppContext.BaseDirectory, configuredPath));
        }

        return configuredPath;
    }
}
