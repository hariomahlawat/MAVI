namespace Mavi.Application.Abstractions.Security;

public sealed record LeaseCapability(string Token, byte[] Hash);

public interface ILeaseCapabilityService
{
    LeaseCapability Create();
    bool Matches(string token, byte[] expectedHash);
}
