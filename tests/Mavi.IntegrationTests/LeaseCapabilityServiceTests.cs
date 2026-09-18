using Mavi.Infrastructure.Security;
using Mavi.Contracts.Worker;

namespace Mavi.IntegrationTests;

public sealed class LeaseCapabilityServiceTests
{
    [Fact]
    public void CreatesAndValidatesCanonicalIndependentCapabilities()
    {
        var service = new LeaseCapabilityService();
        var first = service.Create();
        var second = service.Create();

        Assert.Equal(43, first.Token.Length);
        Assert.DoesNotContain('=', first.Token);
        Assert.Equal(32, first.Hash.Length);
        Assert.True(service.Matches(first.Token, first.Hash));
        Assert.False(service.Matches(first.Token, Enumerable.Repeat((byte)0x44, 32).ToArray()));
        Assert.False(service.Matches("not-a-valid-token", first.Hash));
        Assert.NotEqual(first.Token, second.Token);
        Assert.NotEqual(first.Hash, second.Hash);
    }

    [Fact]
    public void MalformedTrailingBitsAreRejectedWithoutThrowing()
    {
        var malformed = new string('A', 42) + "B";
        Assert.False(WorkerContractRules.IsCanonicalLeaseToken(malformed));
        Assert.False(new LeaseCapabilityService().Matches(malformed, new byte[32]));
    }
}
