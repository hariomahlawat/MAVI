using Mavi.Application.Health;

namespace Mavi.Application.Tests;

public sealed class GetPlatformHealthTests
{
    [Fact]
    public void ExecuteReturnsPlatformHealth()
    {
        var result = GetPlatformHealth.Execute("1.2.3", "build-17", new string('a', 40));

        Assert.Equal("ok", result.Status);
        Assert.Equal("mavi-platform", result.Component);
        Assert.Equal("1.2.3", result.Version);
        Assert.Equal("build-17", result.Build);
        Assert.Equal(new string('a', 40), result.Commit);
    }

    [Fact]
    public void ExecuteUsesExplicitDevelopmentIdentityWhenNotConfigured()
    {
        var result = GetPlatformHealth.Execute("1.2.3");

        Assert.Equal("unknown-development", result.Build);
        Assert.Equal("unknown-development", result.Commit);
    }
}
