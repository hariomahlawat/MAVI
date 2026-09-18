namespace Mavi.Application.Health;

public sealed record PlatformHealth(
    string Status,
    string Component,
    string Version,
    string Build,
    string Commit);

public static class GetPlatformHealth
{
    public static PlatformHealth Execute(
        string version,
        string? build = null,
        string? commit = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(version);
        return new PlatformHealth(
            "ok",
            "mavi-platform",
            version,
            string.IsNullOrWhiteSpace(build) ? "unknown-development" : build,
            string.IsNullOrWhiteSpace(commit) ? "unknown-development" : commit);
    }
}
