using Mavi.Application.Modules.Intelligence;

namespace Mavi.Application.Tests;

public sealed class ProcessingOrchestratorContractTests
{
    // Heartbeat result variants
    [Fact]
    public void HeartbeatSuccessCarriesRequiredProgressAndExpiry()
    {
        var expiresAtUtc = new DateTimeOffset(2026, 9, 9, 3, 0, 0, TimeSpan.Zero);
        HeartbeatResult result = new HeartbeatResult.Success(50, expiresAtUtc);

        var success = Assert.IsType<HeartbeatResult.Success>(result);
        Assert.Equal(50, success.ProgressPercent);
        Assert.Equal(expiresAtUtc, success.LeaseExpiresAtUtc);
    }

    [Fact]
    public void HeartbeatFailureCarriesStableErrorCode()
    {
        HeartbeatResult result = new HeartbeatResult.Failure("vision_job_lease_invalid");

        var failure = Assert.IsType<HeartbeatResult.Failure>(result);
        Assert.Equal("vision_job_lease_invalid", failure.ErrorCode);
    }
}
