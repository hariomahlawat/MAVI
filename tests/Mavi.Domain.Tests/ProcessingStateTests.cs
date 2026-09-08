using Mavi.Domain.Processing;

namespace Mavi.Domain.Tests;

public sealed class ProcessingStateTests
{
    [Fact]
    public void LeaseTransitionsQueuedJobToLeased()
    {
        var now = new DateTimeOffset(2026, 9, 8, 9, 0, 0, TimeSpan.Zero);
        var job = VisionJob.Create(Guid.CreateVersion7(), "phase1-detection-tracking", now);

        job.Lease("worker-01", now, TimeSpan.FromSeconds(120));

        Assert.Equal(VisionJobStatus.Leased, job.Status);
        Assert.Equal("worker-01", job.LeaseOwner);
        Assert.Equal(1, job.AttemptCount);
        Assert.Equal(now.AddSeconds(120), job.LeaseExpiresAtUtc);
    }

    [Fact]
    public void CompleteRejectsWrongLeaseOwner()
    {
        var now = DateTimeOffset.UtcNow;
        var job = VisionJob.Create(Guid.CreateVersion7(), "phase1-detection-tracking", now);
        job.Lease("worker-01", now, TimeSpan.FromSeconds(120));

        Assert.ThrowsAny<Exception>(() => job.Complete("worker-02", now.AddSeconds(10)));
    }
}
