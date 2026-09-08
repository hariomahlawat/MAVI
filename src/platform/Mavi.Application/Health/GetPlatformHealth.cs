namespace Mavi.Application.Health;

public sealed record PlatformHealth(string Status, string Component, string Version);

public static class GetPlatformHealth
{
    public static PlatformHealth Execute(string version)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(version);
        return new PlatformHealth("ok", "mavi-platform", version);
    }
}
