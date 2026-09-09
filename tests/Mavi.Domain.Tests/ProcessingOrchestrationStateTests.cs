using Mavi.Domain.Common;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;

namespace Mavi.Domain.Tests;

public sealed class ProcessingOrchestrationStateTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 9, 2, 30, 0, TimeSpan.Zero);

    // Video state machine
    [Theory]
    [InlineData(VideoProcessingStatus.NotQueued)]
    [InlineData(VideoProcessingStatus.Failed)]
    [InlineData(VideoProcessingStatus.Processed)]
    public void TerminalOrInitialVideoCanQueue(VideoProcessingStatus initial)
    {
        var video = Video();
        if (initial != VideoProcessingStatus.NotQueued) SetVideoStatus(video, initial);
        video.QueueProcessing();
        Assert.Equal(VideoProcessingStatus.Queued, video.ProcessingStatus);
    }

    [Theory]
    [InlineData(VideoProcessingStatus.Queued)]
    [InlineData(VideoProcessingStatus.Processing)]
    public void ActiveVideoCannotQueue(VideoProcessingStatus initial)
    {
        var video = Video(); video.QueueProcessing(); if (initial == VideoProcessingStatus.Processing) video.MarkProcessing();
        Assert.Equal("processing_already_active", Assert.Throws<DomainValidationException>(video.QueueProcessing).Code);
    }

    // Run assignment
    [Fact]
    public void ReassignmentPreservesStartAndChangesWorker()
    {
        var run = ProcessingRun.Create(Video().Id, "phase1-v1", "{}", Now);
        run.AssignLease("worker-a", Now); run.AssignLease("worker-b", Now.AddMinutes(3));
        Assert.Equal("worker-b", run.WorkerId); Assert.Equal(Now, run.StartedAtUtc);
    }

    // Job lease and heartbeat
    [Fact]
    public void ExactExpiryCanReclaimAndIncrementsAttempt()
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "pipeline", Now);
        job.Lease("worker-a", Hash(1), Now, TimeSpan.FromSeconds(10), 2);
        Assert.True(job.CanLease(Now.AddSeconds(10), 2));
        job.Lease("worker-b", Hash(2), Now.AddSeconds(10), TimeSpan.FromSeconds(10), 2);
        Assert.Equal(2, job.AttemptCount); Assert.False(job.CanLease(Now.AddSeconds(20), 2));
    }

    [Fact]
    public void HeartbeatIsMonotonicAndExtendsFromCurrentTime()
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "pipeline", Now);
        job.Lease("worker-a", Hash(1), Now, TimeSpan.FromSeconds(120), 3);
        job.Heartbeat("worker-a", true, 60, Now.AddSeconds(30), TimeSpan.FromSeconds(120));
        Assert.Equal(Now.AddSeconds(150), job.LeaseExpiresAtUtc);
        var error = Assert.Throws<DomainValidationException>(() =>
            job.Heartbeat("worker-a", true, 25, Now.AddSeconds(31), TimeSpan.FromSeconds(120)));
        Assert.Equal("vision_job_progress_regression", error.Code);
    }

    [Fact]
    public void ExactExpiryAndWrongOwnerCannotHeartbeatOrFail()
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "pipeline", Now);
        job.Lease("worker-a", Hash(1), Now, TimeSpan.FromSeconds(10), 3);
        Assert.Throws<DomainValidationException>(() => job.Heartbeat("worker-a", true, 1, Now.AddSeconds(10), TimeSpan.FromSeconds(10)));
        Assert.Throws<DomainValidationException>(() => job.Fail("worker-b", true, "failed", null, Now.AddSeconds(1)));
    }

    [Fact]
    public void ReclaimRotatesHashAndResetsAttemptLocalState()
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "pipeline", Now);
        job.Lease("worker-a", Hash(1), Now, TimeSpan.FromSeconds(10), 3);
        job.Heartbeat("worker-a", true, 70, Now.AddSeconds(1), TimeSpan.FromSeconds(9));
        job.Lease("worker-b", Hash(2), Now.AddSeconds(10), TimeSpan.FromSeconds(10), 3);

        Assert.Equal(2, job.AttemptCount);
        Assert.Equal(0, job.ProgressPercent);
        Assert.Null(job.LastHeartbeatUtc);
        Assert.Equal(Hash(2), job.LeaseTokenHash);
        Assert.Throws<DomainValidationException>(() =>
            job.Heartbeat("worker-b", false, 10, Now.AddSeconds(11), TimeSpan.FromSeconds(10)));
    }

    private static byte[] Hash(byte value) => Enumerable.Repeat(value, 32).ToArray();

    private static VideoAsset Video() => VideoAsset.Create(Guid.CreateVersion7(), Guid.CreateVersion7(), "v.mp4", Now,
        1000, 25, 1, 160, 90, "h264", TimestampSource.Manual, 1, importedAtUtc: Now);

    private static void SetVideoStatus(VideoAsset video, VideoProcessingStatus status)
    {
        video.QueueProcessing(); video.MarkProcessing(); video.MarkProcessingFailed();
        if (status == VideoProcessingStatus.Processed)
            typeof(VideoAsset).GetProperty(nameof(VideoAsset.ProcessingStatus))!.SetValue(video, status);
    }
}
