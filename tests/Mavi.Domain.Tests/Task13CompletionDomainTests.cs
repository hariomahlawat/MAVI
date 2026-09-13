using Mavi.Domain.Common;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;

namespace Mavi.Domain.Tests;

public sealed class Task13CompletionDomainTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 13, 8, 0, 0, TimeSpan.Zero);

    [Fact]
    public void VisionJobCompletionStoresCanonicalDigest()
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "phase1", Now);
        job.Lease("worker-a", new byte[32], Now, TimeSpan.FromMinutes(1), 3);

        job.Complete("worker-a", true, Now.AddSeconds(1), new string('a', 64));

        Assert.Equal(VisionJobStatus.Completed, job.Status);
        Assert.Equal(new string('a', 64), job.CompletionDigest);
        Assert.Equal(100, job.ProgressPercent);
    }

    [Fact]
    public void VisionJobCompletionRejectsMalformedDigest()
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "phase1", Now);
        job.Lease("worker-a", new byte[32], Now, TimeSpan.FromMinutes(1), 3);

        var error = Assert.Throws<DomainValidationException>(() =>
            job.Complete("worker-a", true, Now.AddSeconds(1), "ABC"));

        Assert.Equal("vision_job_completion_digest_invalid", error.Code);
    }

    [Fact]
    public void CompletedRunStoresRuntimeIdentityAndProvenance()
    {
        var run = ProcessingRun.Create(Guid.CreateVersion7(), "v1", "{}", Now);
        run.AssignLease("worker-a", Now);

        run.MarkCompleted(
            20, 2, 900,
            "mmdetection", "rtmdet-m-v1", "ByteTrack", "2.6.0",
            """{"verificationStatus":"verified"}""",
            Now.AddSeconds(1));

        Assert.Equal(ProcessingRunStatus.Completed, run.Status);
        Assert.Equal("mmdetection", run.DetectorName);
        Assert.Equal("rtmdet-m-v1", run.DetectorVersion);
        Assert.Equal("ByteTrack", run.TrackerName);
        Assert.Equal("2.6.0", run.TrackerVersion);
        Assert.Contains("verified", run.RuntimeProvenanceJson);
    }

    [Fact]
    public void CompletedRunAcceptsOnePositiveVisibilitySequence()
    {
        var run = ProcessingRun.Create(Guid.CreateVersion7(), "v1", "{}", Now);
        run.AssignLease("worker-a", Now);
        run.MarkCompleted(20, 2, 900, Now.AddSeconds(1));

        run.AssignCompletionVisibilitySequence(42);

        Assert.Equal(42, run.VisibilitySequence);
        Assert.Equal(
            "processing_visibility_sequence_invalid",
            Assert.Throws<DomainValidationException>(
                () => run.AssignCompletionVisibilitySequence(43)).Code);
    }

    [Fact]
    public void EvidenceRelationshipsAreOneTimeAndIdempotentForSameId()
    {
        var track = Track.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), 1, ObjectClass.Person,
            0, 10, Now, 2, .8, .9, Now);
        var observation = Observation.Create(
            track.Id, ObservationType.Representative, 1, 10, Now,
            .1f, .1f, .2f, .3f, .9, .8, Now);
        var trajectory = Guid.CreateVersion7();
        var thumbnail = Guid.CreateVersion7();

        track.AttachTrajectoryArtifact(trajectory);
        track.AttachTrajectoryArtifact(trajectory);
        observation.AttachThumbnailArtifact(thumbnail);
        observation.AttachThumbnailArtifact(thumbnail);
        track.AttachRepresentativeObservation(observation.Id);
        track.AttachRepresentativeObservation(observation.Id);

        Assert.Equal(trajectory, track.TrajectoryArtifactId);
        Assert.Equal(thumbnail, observation.ThumbnailArtifactId);
        Assert.Equal(observation.Id, track.RepresentativeObservationId);
        Assert.Throws<DomainValidationException>(() => track.AttachTrajectoryArtifact(Guid.CreateVersion7()));
        Assert.Throws<DomainValidationException>(() => observation.AttachThumbnailArtifact(Guid.CreateVersion7()));
    }

    [Fact]
    public void VideoCanReachSuccessfulTerminalStateOnlyFromProcessing()
    {
        var video = VideoAsset.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), "v.mp4", Now,
            1000, 25, 1, 160, 90, "h264", TimestampSource.Manual, 1, importedAtUtc: Now);

        Assert.Throws<DomainValidationException>(video.MarkProcessed);
        video.QueueProcessing();
        video.MarkProcessing();
        video.MarkProcessed();

        Assert.Equal(VideoProcessingStatus.Processed, video.ProcessingStatus);
    }
}
