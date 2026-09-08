using Mavi.Application.Health;

namespace Mavi.Application.Tests;

public sealed class GetPlatformHealthTests
{
    [Fact]
    public void Execute_ReturnsStablePlatformIdentity()
    {
        var result = GetPlatformHealth.Execute("0.1.0-test");

        Assert.Equal("ok", result.Status);
        Assert.Equal("mavi-platform", result.Component);
        Assert.Equal("0.1.0-test", result.Version);
    }
}
