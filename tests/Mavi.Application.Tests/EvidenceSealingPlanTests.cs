using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;

namespace Mavi.Application.Tests;

/// <summary>The shared sealing plan and graph builder (F3 plan §6.5, §6.7; slice 2).</summary>
public sealed class EvidenceSealingPlanTests
{
    private static readonly Guid JobId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761");
    private static readonly Guid RunId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd762");
    private static readonly Guid VideoId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd763");
    private static readonly DateTimeOffset Start = new(2026, 9, 25, 8, 0, 0, TimeSpan.Zero);

    [Fact]
    public void V3PlanReproducesTheSynchronousKeysCropsInRankOrderThenTrajectoryPerTrack()
    {
        var result = Result(CompletionSchema.V3, 2, [ObservationType.Representative, ObservationType.NearView, ObservationType.LateDiverse]);

        var plan = EvidenceSealingPlan.Build(JobId, result);

        var prefix = $"evidence/{JobId:D}/attempt-0002";
        Assert.Equal(
            [
                $"{prefix}/crops/person-000001-representative-{Sha("t1-representative")}.jpg",
                $"{prefix}/crops/person-000001-near-view-{Sha("t1-near-view")}.jpg",
                $"{prefix}/crops/person-000001-late-diverse-{Sha("t1-late-diverse")}.jpg",
                $"{prefix}/trajectories/person-000001-{Sha("t1-trajectory")}.msgpack",
                $"{prefix}/crops/person-000002-representative-{Sha("t2-representative")}.jpg",
                $"{prefix}/crops/person-000002-near-view-{Sha("t2-near-view")}.jpg",
                $"{prefix}/crops/person-000002-late-diverse-{Sha("t2-late-diverse")}.jpg",
                $"{prefix}/trajectories/person-000002-{Sha("t2-trajectory")}.msgpack",
            ],
            plan.Select(x => x.AcceptedStorageKey));
        Assert.Equal(["crops", "crops", "crops", "trajectories", "crops", "crops", "crops", "trajectories"], plan.Select(x => x.Category));
        Assert.Equal([0, 0, 0, 0, 1, 1, 1, 1], plan.Select(x => x.TrackIndex));
        Assert.All(plan, unit => Assert.StartsWith($"staging/{JobId:D}/attempt-0002/", unit.SourceStorageKey, StringComparison.Ordinal));
        Assert.Equal(plan.Select(x => x.SourceStorageKey).Distinct().Count(), plan.Count);
        var first = plan[0];
        Assert.Equal(11, first.ExpectedSizeBytes);
        Assert.Equal(Sha("t1-representative"), first.ExpectedSha256);
    }

    [Fact]
    public void V2PlanUsesTheHistoricalThumbnailKeys()
    {
        var result = Result(CompletionSchema.V2, 1, [ObservationType.Representative]);

        var plan = EvidenceSealingPlan.Build(JobId, result);

        Assert.Equal(
            [
                $"evidence/{JobId:D}/attempt-0001/thumbnails/person-000001-{Sha("t1-representative")}.jpg",
                $"evidence/{JobId:D}/attempt-0001/trajectories/person-000001-{Sha("t1-trajectory")}.msgpack",
            ],
            plan.Select(x => x.AcceptedStorageKey));
    }

    [Fact]
    public void AcceptedKeyRuleIsExact()
    {
        Assert.Equal(
            $"evidence/{JobId:D}/attempt-0007/crops/stem-abc.jpg",
            EvidenceSealingPlan.AcceptedEvidenceKey(JobId, 7, "crops", "stem", "abc", "jpg"));
    }

    [Fact]
    public void AdmittedCropQuotaIsEnforcedForV3Only()
    {
        var half = WorkerContractRules.MaximumCompletionEvidenceCropBytes / 2 + 1;
        var v3 = Result(CompletionSchema.V3, 1, [ObservationType.Representative, ObservationType.NearView], cropBytes: half);
        var v2 = Result(CompletionSchema.V2, 1, [ObservationType.Representative], cropBytes: WorkerContractRules.MaximumCompletionEvidenceCropBytes + 1);
        var within = Result(CompletionSchema.V3, 1, [ObservationType.Representative, ObservationType.NearView], cropBytes: half - 1);

        Assert.True(EvidenceSealingPlan.ExceedsAdmittedCropQuota(v3));
        Assert.False(EvidenceSealingPlan.ExceedsAdmittedCropQuota(v2));
        Assert.False(EvidenceSealingPlan.ExceedsAdmittedCropQuota(within));
    }

    [Fact]
    public void GraphBuilderIsPureDeterministicAndPairsTheRepresentative()
    {
        var result = Result(CompletionSchema.V3, 2, [ObservationType.Representative, ObservationType.NearView]);
        var accepted = EvidenceSealingPlan.Build(JobId, result).ToDictionary(x => x.SourceStorageKey, x => x.AcceptedStorageKey, StringComparer.Ordinal);

        var first = FinalizationGraphBuilder.Build(result, accepted, RunId, VideoId, Start, Start.AddMinutes(1));
        var second = FinalizationGraphBuilder.Build(result, accepted, RunId, VideoId, Start, Start.AddMinutes(1));

        Assert.Equal(2, first.TrackCount);
        Assert.Equal(4, first.ObservationCount);
        Assert.Equal(6, first.ArtifactCount);
        for (var index = 0; index < 2; index++)
        {
            var track = first.Tracks[index];
            Assert.Equal(index + 1, track.Track.LocalTrackNumber);
            Assert.Equal(RunId, track.Track.ProcessingRunId);
            Assert.Equal(VideoId, track.Track.VideoAssetId);
            Assert.Equal(track.TrajectoryArtifact.Id, track.Track.TrajectoryArtifactId);
            Assert.Equal(ArtifactType.TrackTrajectory, track.TrajectoryArtifact.ArtifactType);
            Assert.Equal(accepted[result.Tracks[index].TrajectoryArtifact.StorageKey], track.TrajectoryArtifact.StorageKey);
            Assert.Null(track.Track.RepresentativeObservationId); // attached only after the observation row exists
            Assert.Same(track.Observations[0].Observation, track.Representative);
            Assert.Equal(ObservationType.Representative, track.Representative.ObservationType);
            Assert.Equal(0, track.Representative.EvidenceRank);
            foreach (var observation in track.Observations)
            {
                Assert.Equal(track.Track.Id, observation.Observation.TrackId);
                Assert.Equal(observation.CropArtifact.Id, observation.Observation.ThumbnailArtifactId);
                Assert.Equal(ArtifactType.EvidenceCrop, observation.CropArtifact.ArtifactType);
                Assert.StartsWith("evidence/", observation.CropArtifact.StorageKey, StringComparison.Ordinal);
            }
        }

        // Same facts, same shape; only the generated ids differ.
        Assert.Equal(
            first.Tracks.SelectMany(t => t.Observations).Select(o => (o.CropArtifact.StorageKey, o.Observation.EvidenceRank, o.Observation.VideoOffsetMs)),
            second.Tracks.SelectMany(t => t.Observations).Select(o => (o.CropArtifact.StorageKey, o.Observation.EvidenceRank, o.Observation.VideoOffsetMs)));
        Assert.NotEqual(first.Tracks[0].Track.Id, second.Tracks[0].Track.Id);
    }

    [Fact]
    public void V2GraphKeepsTheThumbnailArtifactType()
    {
        var result = Result(CompletionSchema.V2, 1, [ObservationType.Representative]);
        var accepted = EvidenceSealingPlan.Build(JobId, result).ToDictionary(x => x.SourceStorageKey, x => x.AcceptedStorageKey, StringComparer.Ordinal);

        var graph = FinalizationGraphBuilder.Build(result, accepted, RunId, VideoId, Start, Start);

        Assert.Equal(ArtifactType.Thumbnail, Assert.Single(Assert.Single(graph.Tracks).Observations).CropArtifact.ArtifactType);
    }

    [Fact]
    public void GraphBuilderRefusesAnUnsealedKey()
    {
        var result = Result(CompletionSchema.V3, 1, [ObservationType.Representative]);
        var accepted = EvidenceSealingPlan.Build(JobId, result)
            .Where(x => x.Category == EvidenceSealingPlan.CropsCategory)
            .ToDictionary(x => x.SourceStorageKey, x => x.AcceptedStorageKey, StringComparer.Ordinal);

        Assert.Throws<KeyNotFoundException>(() => FinalizationGraphBuilder.Build(result, accepted, RunId, VideoId, Start, Start));
    }

    // Fixture

    private static string Sha(string seed) => Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(seed)));

    private static ValidatedVisionResult Result(CompletionSchema schema, int trackCount, ObservationType[] roles, long cropBytes = 11)
    {
        var prefix = $"staging/{JobId:D}/attempt-{(schema == CompletionSchema.V2 ? 1 : 2):0000}";
        var tracks = new List<ValidatedTrackResult>();
        for (var t = 1; t <= trackCount; t++)
        {
            var trackId = $"person-{t:000000}";
            var observations = roles.Select((role, rank) => new ValidatedObservation(
                role, rank, 250 + rank * 250, rank, .88, .8 - rank * .1, .8 - rank * .1, .1, .2, .3, .4,
                new ValidatedArtifactDescriptor($"{prefix}/evidence/{trackId}-{VisionResultValidator.RoleToken(role)}.jpg", "image/jpeg", cropBytes, Sha($"t{t}-{VisionResultValidator.RoleToken(role)}")))).ToList();
            tracks.Add(new ValidatedTrackResult(
                trackId, ObjectClass.Person, 0, 1000, 4, .85, .9, observations,
                new ValidatedArtifactDescriptor($"{prefix}/trajectories/{trackId}.msgpack", "application/msgpack", 19, Sha($"t{t}-trajectory"))));
        }

        return new ValidatedVisionResult(
            schema, schema == CompletionSchema.V2 ? 1 : 2, 20, 900, "{}", "det", "1", "trk", "1", tracks, null, new string('a', 64));
    }
}

/// <summary>
/// The sealing plan trusts the validator's storage keys to belong to the routed job and attempt.
/// This pins that promise so the finalizer's staging validation (F3 plan §6.5) rests on a tested
/// rule rather than on reading the validator.
/// </summary>
public sealed class ValidatorStagingKeyBindingTests
{
    private static readonly Guid JobId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761");
    private static readonly Guid OtherJobId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd799");

    [Theory]
    [InlineData("018fa7b6-2b31-7f42-9f33-9fd9f6fdd799", 1)] // another job
    [InlineData("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761", 2)] // another attempt
    public void ValidatorBindsStagingKeysToTheRoutedJobAndAttempt(string keyJob, int keyAttempt)
    {
        var request = Request($"staging/{keyJob}/attempt-{keyAttempt:0000}");

        var error = Assert.Throws<VisionResultValidationException>(() => new VisionResultValidator().Validate(JobId, request, 10_000));

        Assert.Equal("artifact_descriptor_invalid", error.ReasonCode);
        Assert.NotEqual(OtherJobId, JobId);
    }

    [Fact]
    public void ValidatorAcceptsTheRoutedJobAndAttemptKeys()
    {
        var result = new VisionResultValidator().Validate(JobId, Request($"staging/{JobId:D}/attempt-0001"), 10_000);
        Assert.All(
            EvidenceSealingPlan.Build(JobId, result),
            unit => Assert.StartsWith($"staging/{JobId:D}/attempt-0001/", unit.SourceStorageKey, StringComparison.Ordinal));
    }

    private static VisionJobCompleteRequest Request(string prefix)
    {
        var crop = new VisionArtifactDescriptorContract($"{prefix}/evidence/person-000001-representative.jpg", "image/jpeg", 10, new string('a', 64));
        var track = new VisionTrackResultContract(
            "person-000001", "person", 0, 500, 3, .85, .9, null,
            new VisionArtifactDescriptorContract($"{prefix}/trajectories/person-000001.msgpack", "application/msgpack", 20, new string('f', 64)),
            [new VisionTrackObservationContract("representative", 0, 100, 10, .88, .8, .8, new VisionBoundingBoxContract(.1, .2, .3, .4), crop)]);
        var role = new VisionEvidenceRoleAccountingContract(1, 1, 0, 10, 10);
        var none = new VisionEvidenceRoleAccountingContract(0, 0, 0, 0, 0);
        return new VisionJobCompleteRequest(
            "3.1", JobId, "gpu-sdd-01", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 1, 20, 900,
            VisionResultValidatorTestProvenance.Create(), [track], new VisionEvidenceAccountingContract(role, none, none, none));
    }
}
