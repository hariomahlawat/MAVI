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

    [Theory]
    [InlineData(" worker-a ")]
    [InlineData("worker-a ")]
    [InlineData(" worker-a")]
    [InlineData("-worker")]
    [InlineData("_worker")]
    [InlineData(".worker")]
    [InlineData("worker name")]
    [InlineData("worker/name")]
    [InlineData("worker:name")]
    [InlineData("worker\\name")]
    [InlineData("worker\nname")]
    [InlineData("worker\tname")]
    [InlineData("gpu-sdd-01\n")]
    [InlineData("gpu-sdd-01\r")]
    [InlineData("gpu-sdd-01\r\n")]
    [InlineData("воркер")]
    public void ProcessingRunRejectsNonCanonicalWorkerIds(string workerId)
    {
        var assignRun = ProcessingRun.Create(Video().Id, "phase1-v1", "{}", Now);
        Assert.Throws<DomainValidationException>(() => assignRun.AssignLease(workerId, Now));

        var runningRun = ProcessingRun.Create(Video().Id, "phase1-v1", "{}", Now);
        Assert.Throws<DomainValidationException>(() => runningRun.MarkRunning(workerId, Now));
    }

    [Theory]
    [InlineData("gpu-sdd-01")]
    [InlineData("gpu.sdd.01")]
    [InlineData("gpu_sdd_01")]
    [InlineData("A1")]
    public void ProcessingRunStoresCanonicalWorkerIdExactly(string workerId)
    {
        var run = ProcessingRun.Create(Video().Id, "phase1-v1", "{}", Now);
        run.AssignLease(workerId, Now);
        Assert.Equal(workerId, run.WorkerId);
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

    [Theory]
    [InlineData(" worker-a ")]
    [InlineData("worker-a ")]
    [InlineData(" worker-a")]
    [InlineData("-worker")]
    [InlineData("_worker")]
    [InlineData(".worker")]
    [InlineData("worker name")]
    [InlineData("worker/name")]
    [InlineData("worker:name")]
    [InlineData("worker\\name")]
    [InlineData("worker\nname")]
    [InlineData("worker\tname")]
    [InlineData("gpu-sdd-01\n")]
    [InlineData("gpu-sdd-01\r")]
    [InlineData("gpu-sdd-01\r\n")]
    [InlineData("воркер")]
    public void VisionJobRejectsNonCanonicalWorkerIds(string workerId)
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "pipeline", Now);
        Assert.Throws<DomainValidationException>(() =>
            job.Lease(workerId, Hash(1), Now, TimeSpan.FromSeconds(10), 3));

        job.Lease("worker-a", Hash(1), Now, TimeSpan.FromSeconds(10), 3);
        Assert.Throws<DomainValidationException>(() =>
            job.Heartbeat(workerId, true, 10, Now.AddSeconds(1), TimeSpan.FromSeconds(10)));
        Assert.Throws<DomainValidationException>(() => job.Complete(workerId, true, Now.AddSeconds(1)));
        Assert.Throws<DomainValidationException>(() => job.Fail(workerId, true, "failed", null, Now.AddSeconds(1)));
    }

    [Theory]
    [InlineData("gpu-sdd-01")]
    [InlineData("gpu.sdd.01")]
    [InlineData("gpu_sdd_01")]
    [InlineData("A1")]
    public void VisionJobStoresCanonicalWorkerIdExactly(string workerId)
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "pipeline", Now);
        job.Lease(workerId, Hash(1), Now, TimeSpan.FromSeconds(10), 3);
        Assert.Equal(workerId, job.LeaseOwner);
    }

    [Fact]
    public void DomainRejectsWorkerIdsLongerThan128Characters()
    {
        var workerId = new string('a', 129);
        var run = ProcessingRun.Create(Video().Id, "phase1-v1", "{}", Now);
        var job = VisionJob.Create(Guid.CreateVersion7(), "pipeline", Now);

        Assert.Throws<DomainValidationException>(() => run.AssignLease(workerId, Now));
        Assert.Throws<DomainValidationException>(() => job.Lease(workerId, Hash(1), Now, TimeSpan.FromSeconds(10), 3));
    }

    [Fact]
    public void DomainRejects128LegalWorkerIdCharactersFollowedByLineFeed()
    {
        var workerId = new string('a', 128) + "\n";
        var run = ProcessingRun.Create(Video().Id, "phase1-v1", "{}", Now);
        var job = VisionJob.Create(Guid.CreateVersion7(), "pipeline", Now);

        Assert.Throws<DomainValidationException>(() => run.AssignLease(workerId, Now));
        Assert.Throws<DomainValidationException>(() => job.Lease(workerId, Hash(1), Now, TimeSpan.FromSeconds(10), 3));
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

    [Fact]
    public void CompletionRequiresMatchingCapability()
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "pipeline", Now);
        job.Lease("worker-a", Hash(1), Now, TimeSpan.FromSeconds(10), 3);

        Assert.Throws<DomainValidationException>(() => job.Complete("worker-a", false, Now.AddSeconds(1)));
        job.Complete("worker-a", true, Now.AddSeconds(1));
        Assert.Equal(VisionJobStatus.Completed, job.Status);
    }

    [Fact]
    public void AttemptExhaustionRevokesActiveCapability()
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "pipeline", Now);
        job.Lease("worker-a", Hash(1), Now, TimeSpan.FromSeconds(10), 1);
        job.Exhaust(Now.AddSeconds(10));

        Assert.Equal(1, job.AttemptCount);
        Assert.Null(job.LeaseOwner);
        Assert.Null(job.LeaseTokenHash);
        Assert.Null(job.LeaseExpiresAtUtc);
        Assert.Null(job.LastHeartbeatUtc);
        Assert.Throws<DomainValidationException>(() =>
            job.Fail("worker-a", true, "vision_job_attempts_exhausted", null, Now.AddSeconds(11)));
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
