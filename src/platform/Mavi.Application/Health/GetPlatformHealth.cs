using Mavi.Application.Abstractions.Storage;

namespace Mavi.Application.Health;

public sealed record PlatformHealth(
    string Status,
    string Component,
    string Version,
    string Build,
    string Commit,
    PlatformHealthDetails? Details = null);

/// <summary>Operational details of platform background services (additive).</summary>
public sealed record PlatformHealthDetails(StagingJanitorHealth StagingJanitor);

public static class GetPlatformHealth
{
    public static PlatformHealth Execute(
        string version,
        string? build = null,
        string? commit = null,
        PlatformHealthDetails? details = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(version);
        return new PlatformHealth(
            "ok",
            "mavi-platform",
            version,
            string.IsNullOrWhiteSpace(build) ? "unknown-development" : build,
            string.IsNullOrWhiteSpace(commit) ? "unknown-development" : commit,
            details);
    }
}
