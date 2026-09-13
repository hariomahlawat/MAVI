using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;

namespace Mavi.Application.Tests;

public sealed class VisionResultValidatorTests
{
    private static readonly Guid JobId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761");

    [Fact]
    public void ValidResultIsNormalizedSortedAndDigestedDeterministically()
    {
        var validator = new VisionResultValidator();
        var request = Request(
            Track("vehicle-000002", "vehicle"),
            Track("person-000001", "person"));

        var first = validator.Validate(JobId, request, 10_000);
        var second = validator.Validate(JobId, request, 10_000);

        Assert.Equal(["person-000001", "vehicle-000002"], first.Tracks.Select(x => x.TrackId));
        Assert.Equal(64, first.CompletionDigest.Length);
        Assert.Equal(first.CompletionDigest, second.CompletionDigest);
        Assert.Equal("rtmdet-m", first.DetectorName);
        Assert.Equal("2.6.0", first.TrackerVersion);
    }

    [Fact]
    public void TrackOrderDoesNotChangeCompletionDigest()
    {
        var validator = new VisionResultValidator();

        var first = validator.Validate(JobId, Request(
            Track("vehicle-000002", "vehicle"),
            Track("person-000001", "person")), 10_000);
        var second = validator.Validate(JobId, Request(
            Track("person-000001", "person"),
            Track("vehicle-000002", "vehicle")), 10_000);

        Assert.Equal(first.CompletionDigest, second.CompletionDigest);
    }

    [Theory]
    [InlineData("wrong-job")]
    [InlineData("wrong-attempt-artifact")]
    [InlineData("offset-beyond-video")]
    [InlineData("duplicate-track")]
    [InlineData("mean-above-max")]
    [InlineData("negative-offset")]
    [InlineData("invalid-object-class")]
    [InlineData("non-finite-score")]
    [InlineData("representative-outside-track")]
    [InlineData("tracks-with-zero-frames")]
    [InlineData("malformed-artifact-sha")]
    [InlineData("wrong-track-filename")]
    [InlineData("invalid-normalized-box")]
    [InlineData("verified-without-qualification")]
    [InlineData("overlong-model-id")]
    [InlineData("overlong-tracker-version")]
    [InlineData("overlong-platform-detail")]
    [InlineData("padded-runtime-variant")]
    public void InvalidResultIsRejectedWithoutRepair(string mutation)
    {
        var validator = new VisionResultValidator();
        var track = Track("person-000001", "person");
        var request = Request(track);
        var routeJobId = JobId;
        var duration = 10_000L;

        request = mutation switch
        {
            "wrong-job" => request with { JobId = Guid.CreateVersion7() },
            "wrong-attempt-artifact" => request with
            {
                Tracks = [track with
                {
                    Representative = track.Representative! with
                    {
                        Thumbnail = track.Representative.Thumbnail! with
                        {
                            StorageKey = track.Representative.Thumbnail.StorageKey!.Replace("attempt-0001", "attempt-0002")
                        }
                    }
                }]
            },
            "offset-beyond-video" => request with { Tracks = [track with { EndOffsetMs = 20_000 }] },
            "duplicate-track" => request with { Tracks = [track, track] },
            "mean-above-max" => request with { Tracks = [track with { MeanConfidence = .99, MaxConfidence = .9 }] },
            "negative-offset" => request with { Tracks = [track with { StartOffsetMs = -1 }] },
            "invalid-object-class" => request with { Tracks = [track with { ObjectClass = "animal" }] },
            "non-finite-score" => request with { Tracks = [track with { MeanConfidence = double.NaN }] },
            "representative-outside-track" => request with
            {
                Tracks = [track with
                {
                    Representative = track.Representative! with { OffsetMs = 501 }
                }]
            },
            "tracks-with-zero-frames" => request with { FramesProcessed = 0 },
            "malformed-artifact-sha" => request with
            {
                Tracks = [track with
                {
                    TrajectoryArtifact = track.TrajectoryArtifact! with { Sha256 = new string('A', 64) }
                }]
            },
            "wrong-track-filename" => request with
            {
                Tracks = [track with
                {
                    TrajectoryArtifact = track.TrajectoryArtifact! with
                    {
                        StorageKey = track.TrajectoryArtifact.StorageKey!.Replace("person-000001.msgpack", "person-999999.msgpack")
                    }
                }]
            },
            "invalid-normalized-box" => request with
            {
                Tracks = [track with
                {
                    Representative = track.Representative! with
                    {
                        BoundingBox = new VisionBoundingBoxContract(.9, .2, .3, .4)
                    }
                }]
            },
            "verified-without-qualification" => request with
            {
                Provenance = request.Provenance! with
                {
                    VerificationStatus = "verified",
                    QualificationId = null,
                    QualificationSha256 = null
                }
            },
            "overlong-model-id" => request with
            {
                Provenance = request.Provenance! with { ModelId = new string('m', 129) }
            },
            "overlong-tracker-version" => request with
            {
                Provenance = request.Provenance! with
                {
                    DependencyVersions = new Dictionary<string, string>
                    {
                        ["python"] = "3.12.14",
                        ["trackers"] = new string('v', 129)
                    }
                }
            },
            "overlong-platform-detail" => request with
            {
                Provenance = request.Provenance! with
                {
                    Platform = request.Provenance.Platform! with
                    {
                        PythonCompiler = new string('c', 257)
                    }
                }
            },
            "padded-runtime-variant" => request with
            {
                Provenance = request.Provenance! with { RuntimeVariant = " padded " }
            },
            _ => request,
        };

        Assert.Throws<VisionResultValidationException>(() => validator.Validate(routeJobId, request, duration));
    }

    private static VisionJobCompleteRequest Request(params VisionTrackResultContract[] tracks) =>
        new(
            "2.0",
            JobId,
            "gpu-sdd-01",
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            1,
            20,
            900,
            Provenance(),
            tracks);

    private static VisionTrackResultContract Track(string trackId, string objectClass)
    {
        var prefix = $"staging/{JobId:D}/attempt-0001";
        return new VisionTrackResultContract(
            trackId,
            objectClass,
            0,
            500,
            3,
            .85,
            .9,
            new VisionRepresentativeObservationContract(
                250,
                10,
                .88,
                .8,
                new VisionBoundingBoxContract(.1, .2, .3, .4),
                new VisionArtifactDescriptorContract(
                    $"{prefix}/thumbnails/{trackId}.jpg",
                    "image/jpeg",
                    10,
                    new string('a', 64))),
            new VisionArtifactDescriptorContract(
                $"{prefix}/trajectories/{trackId}.msgpack",
                "application/msgpack",
                20,
                new string('b', 64)));
    }

    private static VisionRuntimeProvenanceContract Provenance() =>
        new(
            "rtmdet-m",
            "1",
            new string('1', 64),
            new string('2', 64),
            new string('3', 64),
            "phase1",
            "1",
            new string('4', 64),
            null,
            null,
            "unverified",
            "runtime-v1",
            new string('5', 64),
            "linux-x86_64-cpu",
            new string('6', 64),
            "mmdetection",
            new Dictionary<string, string> { ["python"] = "3.12.14", ["trackers"] = "2.6.0" },
            null,
            new VisionPlatformIdentityContract(
                "Linux", "6.8", "qualified", "x86_64", "x86_64",
                "3.12.14", "CPython", ["main", "Sep 2026"], "GCC"),
            "cpu",
            0,
            "cpu",
            null,
            "build-a",
            new string('a', 40),
            "every-frame",
            new VisionTrackerParametersContract(30, .25, .1, .2, 2, 1),
            "RGB");
}
