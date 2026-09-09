using System.Buffers.Text;
using System.Security.Cryptography;
using Mavi.Application.Abstractions.Security;

namespace Mavi.Infrastructure.Security;

public sealed class LeaseCapabilityService : ILeaseCapabilityService
{
    // Capability creation
    public LeaseCapability Create()
    {
        var bytes = RandomNumberGenerator.GetBytes(32);
        return new LeaseCapability(Base64Url.EncodeToString(bytes), SHA256.HashData(bytes));
    }

    // Constant-time verification
    public bool Matches(string token, byte[] expectedHash)
    {
        if (expectedHash is not { Length: 32 } || token is not { Length: 43 }) return false;
        Span<byte> bytes = stackalloc byte[32];
        if (!Base64Url.TryDecodeFromChars(token, bytes, out var bytesWritten) || bytesWritten != 32) return false;
        Span<byte> actualHash = stackalloc byte[32];
        SHA256.HashData(bytes, actualHash);
        return CryptographicOperations.FixedTimeEquals(actualHash, expectedHash);
    }
}
