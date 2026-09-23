using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests;

/// <summary>Completion 3.0 Evidence Set validation (S1.2 plan §7.2–§7.3).</summary>
public sealed class VisionResultValidatorV3Tests
{
    private static readonly Guid JobId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761");
    private static readonly string[] AllRoles = ["representative", "near-view", "early-diverse", "late-diverse"];

    [Fact]
    public void FullEvidenceSetIsAcceptedInCanonicalRoleAndRankOrder()
    {
        var track = Track("person-000001", AllRoles);
        var shuffled = track with { Observations = [.. track.Observations!.Reverse()] };

        var result = new VisionResultValidator().Validate(JobId, Request([shuffled]), 10_000);

        Assert.Equal(CompletionSchema.V3, result.Schema);
        var observations = Assert.Single(result.Tracks).Observations;
        Assert.Equal(
            [ObservationType.Representative, ObservationType.NearView, ObservationType.EarlyDiverse, ObservationType.LateDiverse],
            observations.Select(x => x.Role));
        Assert.Equal([0, 1, 2, 3], observations.Select(x => x.Rank));
        Assert.Equal(ObservationType.Representative, result.Tracks[0].Representative.Role);
        Assert.NotNull(result.EvidenceAccounting);
        Assert.Equal(1, result.EvidenceAccounting!.NearView.Admitted);
    }

    [Fact]
    public void RepresentativeOnlyTrackIsAccepted()
    {
        var result = new VisionResultValidator().Validate(JobId, Request([Track("person-000001", ["representative"])]), 10_000);

        Assert.Single(Assert.Single(result.Tracks).Observations);
    }

    [Fact]
    public void SupplementalRanksFollowTheRolesKept()
    {
        // NearView omitted: EarlyDiverse takes rank 1 and LateDiverse rank 2.
        var result = new VisionResultValidator().Validate(
            JobId, Request([Track("person-000001", ["representative", "early-diverse", "late-diverse"])]), 10_000);

        var observations = Assert.Single(result.Tracks).Observations;
        Assert.Equal([0, 1, 2], observations.Select(x => x.Rank));
        Assert.Equal(ObservationType.LateDiverse, observations[2].Role);
    }

    [Fact]
    public void ObservationInputOrderDoesNotChangeTheDigest()
    {
        var track = Track("person-000001", AllRoles);
        var validator = new VisionResultValidator();

        var first = validator.Validate(JobId, Request([track]), 10_000);
        var second = validator.Validate(JobId, Request([track with { Observations = [.. track.Observations!.Reverse()] }]), 10_000);

        Assert.Equal(first.CompletionDigest, second.CompletionDigest);
    }

    [Fact]
    public void EveryDigestedMemberChangesTheDigest()
    {
        var validator = new VisionResultValidator();
        var baseline = validator.Validate(JobId, Request([Track("person-000001", AllRoles)]), 10_000).CompletionDigest;
        var variants = new List<VisionJobCompleteRequest>
        {
            Request([Mutate(Track("person-000001", AllRoles), 1, o => o with { SelectionScore = .5 })]),
            Request([Mutate(Track("person-000001", AllRoles), 1, o => o with { QualityScore = .5 })]),
            Request([Mutate(Track("person-000001", AllRoles), 2, o => o with { SourceFrameNumber = 19 })]),
            Request([Mutate(Track("person-000001", AllRoles), 3, o => o with { Crop = o.Crop! with { Sha256 = new string('e', 64) } })]),
            Request([Track("person-000001", AllRoles)], Accounting(1, AllRoles, extraNearViewCandidates: 1)),
        };

        foreach (var variant in variants)
            Assert.NotEqual(baseline, validator.Validate(JobId, variant, 10_000).CompletionDigest);
    }

    [Fact]
    public void V3AndV2DigestDomainsAreSeparate()
    {
        var validator = new VisionResultValidator();
        var v3 = validator.Validate(JobId, Request([Track("person-000001", ["representative"])]), 10_000);
        var v2Track = Track("person-000001", ["representative"]);
        var observation = v2Track.Observations![0];
        var v2 = validator.Validate(JobId, Request([v2Track with
        {
            Observations = null,
            Representative = new VisionRepresentativeObservationContract(
                observation.OffsetMs, observation.SourceFrameNumber, observation.Confidence, observation.QualityScore,
                observation.BoundingBox, observation.Crop! with { StorageKey = $"{Prefix}/thumbnails/person-000001.jpg" }),
        }]) with { SchemaVersion = "2.0", EvidenceAccounting = null }, 10_000);

        Assert.Equal(CompletionSchema.V2, v2.Schema);
        Assert.NotEqual(v2.CompletionDigest, v3.CompletionDigest);
    }

    [Theory]
    [InlineData("schema-unknown", "schema_version_invalid")]
    [InlineData("accounting-missing", "evidence_accounting_missing")]
    [InlineData("representative-member-present", "representative_unexpected")]
    [InlineData("observations-null", "observations_missing")]
    [InlineData("observations-empty", "observations_missing")]
    [InlineData("observations-five", "observation_count_invalid")]
    [InlineData("observation-null", "observation_missing")]
    [InlineData("role-unknown", "observation_role_invalid")]
    [InlineData("role-legacy", "observation_role_invalid")]
    [InlineData("role-case", "observation_role_invalid")]
    [InlineData("role-duplicate", "observation_role_duplicate")]
    [InlineData("rank-missing", "observation_rank_invalid")]
    [InlineData("rank-gap", "observation_rank_invalid")]
    [InlineData("rank-representative-nonzero", "observation_rank_invalid")]
    [InlineData("representative-missing", "observation_representative_missing")]
    [InlineData("frame-duplicate", "observation_frame_duplicate")]
    [InlineData("offset-outside-track", "observation_invalid")]
    [InlineData("frame-outside-processed", "observation_invalid")]
    [InlineData("confidence-above-track-max", "observation_invalid")]
    [InlineData("selection-score-nan", "observation_invalid")]
    [InlineData("selection-score-missing", "observation_invalid")]
    [InlineData("quality-score-above-one", "observation_invalid")]
    [InlineData("crop-missing", "observation_invalid")]
    [InlineData("box-invalid", "bounding_box_invalid")]
    [InlineData("crop-key-v2-thumbnail-path", "artifact_descriptor_invalid")]
    [InlineData("crop-key-wrong-role", "artifact_descriptor_invalid")]
    [InlineData("crop-key-wrong-attempt", "artifact_descriptor_invalid")]
    [InlineData("crop-media-type", "artifact_descriptor_invalid")]
    [InlineData("crop-empty", "observation_crop_size_invalid")]
    [InlineData("crop-representative-over-cap", "observation_crop_size_invalid")]
    [InlineData("crop-supplemental-over-cap", "observation_crop_size_invalid")]
    [InlineData("accounting-role-missing", "evidence_accounting_invalid")]
    [InlineData("accounting-negative", "evidence_accounting_invalid")]
    [InlineData("accounting-admitted-mismatch", "evidence_accounting_invalid")]
    [InlineData("accounting-admitted-bytes-mismatch", "evidence_accounting_invalid")]
    [InlineData("accounting-omitted-mismatch", "evidence_accounting_invalid")]
    [InlineData("accounting-admitted-above-candidates", "evidence_accounting_invalid")]
    [InlineData("accounting-admitted-bytes-above-candidate-bytes", "evidence_accounting_invalid")]
    [InlineData("accounting-representative-candidates", "evidence_accounting_invalid")]
    [InlineData("accounting-representative-omitted", "evidence_accounting_invalid")]
    public void InvalidEvidenceSetIsRejectedWithoutRepair(string mutation, string expectedCode)
    {
        var track = Track("person-000001", AllRoles);
        var accounting = Accounting(1, AllRoles);
        var request = Request([track], accounting);
        request = mutation switch
        {
            "schema-unknown" => request with { SchemaVersion = "4.0" },
            "accounting-missing" => request with { EvidenceAccounting = null },
            "representative-member-present" => request with
            {
                Tracks = [track with { Representative = new VisionRepresentativeObservationContract(250, 10, .88, .8, Box(), Crop("representative", 10)) }],
            },
            "observations-null" => request with { Tracks = [track with { Observations = null }] },
            "observations-empty" => request with { Tracks = [track with { Observations = [] }] },
            "observations-five" => request with { Tracks = [track with { Observations = [.. track.Observations!, track.Observations![3]] }] },
            "observation-null" => request with { Tracks = [track with { Observations = [track.Observations![0], null!] }] },
            "role-unknown" => Replace(request, track, 1, o => o with { Role = "side-view" }),
            "role-legacy" => Replace(request, track, 1, o => o with { Role = "BestQuality" }),
            "role-case" => Replace(request, track, 1, o => o with { Role = "Near-View" }),
            "role-duplicate" => Replace(request, track, 2, o => o with { Role = "near-view" }),
            "rank-missing" => Replace(request, track, 1, o => o with { Rank = null }),
            "rank-gap" => Replace(request, track, 3, o => o with { Rank = 4 }),
            "rank-representative-nonzero" => request with
            {
                Tracks = [track with
                {
                    Observations = [track.Observations![0] with { Rank = 1 }, track.Observations![1] with { Rank = 0 }, track.Observations![2], track.Observations![3]],
                }],
            },
            "representative-missing" => request with { Tracks = [track with { Observations = [.. track.Observations!.Skip(1)] }] },
            "frame-duplicate" => Replace(request, track, 2, o => o with { SourceFrameNumber = 10 }),
            "offset-outside-track" => Replace(request, track, 1, o => o with { OffsetMs = 501 }),
            "frame-outside-processed" => Replace(request, track, 1, o => o with { SourceFrameNumber = 20 }),
            "confidence-above-track-max" => Replace(request, track, 1, o => o with { Confidence = .95 }),
            "selection-score-nan" => Replace(request, track, 1, o => o with { SelectionScore = double.NaN }),
            "selection-score-missing" => Replace(request, track, 1, o => o with { SelectionScore = null }),
            "quality-score-above-one" => Replace(request, track, 1, o => o with { QualityScore = 1.01 }),
            "crop-missing" => Replace(request, track, 1, o => o with { Crop = null }),
            "box-invalid" => Replace(request, track, 1, o => o with { BoundingBox = new VisionBoundingBoxContract(.9, .2, .3, .4) }),
            "crop-key-v2-thumbnail-path" => Replace(request, track, 0, o => o with { Crop = o.Crop! with { StorageKey = $"{Prefix}/thumbnails/person-000001.jpg" } }),
            "crop-key-wrong-role" => Replace(request, track, 1, o => o with { Crop = o.Crop! with { StorageKey = $"{Prefix}/evidence/person-000001-early-diverse.jpg" } }),
            "crop-key-wrong-attempt" => Replace(request, track, 1, o => o with { Crop = o.Crop! with { StorageKey = o.Crop.StorageKey!.Replace("attempt-0001", "attempt-0002", StringComparison.Ordinal) } }),
            "crop-media-type" => Replace(request, track, 1, o => o with { Crop = o.Crop! with { MediaType = "image/png" } }),
            "crop-empty" => Replace(request, track, 1, o => o with { Crop = o.Crop! with { SizeBytes = 0 } }),
            "crop-representative-over-cap" => Replace(request, track, 0, o => o with { Crop = o.Crop! with { SizeBytes = WorkerContractRules.MaximumRepresentativeCropBytes + 1 } }),
            "crop-supplemental-over-cap" => Replace(request, track, 3, o => o with { Crop = o.Crop! with { SizeBytes = WorkerContractRules.MaximumSupplementalCropBytes + 1 } }),
            "accounting-role-missing" => request with { EvidenceAccounting = accounting with { LateDiverse = null } },
            "accounting-negative" => request with { EvidenceAccounting = accounting with { NearView = accounting.NearView! with { Candidates = -1 } } },
            "accounting-admitted-mismatch" => request with { EvidenceAccounting = accounting with { NearView = accounting.NearView! with { Admitted = 0, Omitted = 1 } } },
            "accounting-admitted-bytes-mismatch" => request with { EvidenceAccounting = accounting with { NearView = accounting.NearView! with { AdmittedBytes = 11 } } },
            "accounting-omitted-mismatch" => request with { EvidenceAccounting = accounting with { NearView = accounting.NearView! with { Candidates = 3, Omitted = 1 } } },
            "accounting-admitted-above-candidates" => request with { EvidenceAccounting = accounting with { NearView = accounting.NearView! with { Candidates = 0, Omitted = -1 } } },
            "accounting-admitted-bytes-above-candidate-bytes" => request with { EvidenceAccounting = accounting with { NearView = accounting.NearView! with { CandidateBytes = 9 } } },
            "accounting-representative-candidates" => request with { EvidenceAccounting = accounting with { Representative = accounting.Representative! with { Candidates = 2, Omitted = 1 } } },
            "accounting-representative-omitted" => request with { EvidenceAccounting = accounting with { Representative = accounting.Representative! with { Omitted = 1 } } },
            _ => throw new ArgumentOutOfRangeException(nameof(mutation)),
        };

        var exception = Assert.Throws<VisionResultValidationException>(
            () => new VisionResultValidator().Validate(JobId, request, 10_000));
        Assert.Equal(expectedCode, exception.ReasonCode);
    }

    [Theory]
    [InlineData("v2-with-observations", "observations_unexpected")]
    [InlineData("v2-with-accounting", "evidence_accounting_unexpected")]
    public void V2BodyMayNotCarryV3Members(string mutation, string expectedCode)
    {
        var observation = Track("person-000001", ["representative"]).Observations![0];
        var v2Track = Track("person-000001", ["representative"]) with
        {
            Observations = null,
            Representative = new VisionRepresentativeObservationContract(
                observation.OffsetMs, observation.SourceFrameNumber, observation.Confidence, observation.QualityScore,
                observation.BoundingBox, observation.Crop! with { StorageKey = $"{Prefix}/thumbnails/person-000001.jpg" }),
        };
        var request = Request([v2Track]) with { SchemaVersion = "2.0", EvidenceAccounting = null };
        request = mutation == "v2-with-observations"
            ? request with { Tracks = [v2Track with { Observations = [observation] }] }
            : request with { EvidenceAccounting = Accounting(1, ["representative"]) };

        var exception = Assert.Throws<VisionResultValidationException>(
            () => new VisionResultValidator().Validate(JobId, request, 10_000));
        Assert.Equal(expectedCode, exception.ReasonCode);
    }

    [Fact]
    public void CropBytesAtEachRoleCapAreAccepted()
    {
        var track = Track("person-000001", AllRoles, representativeBytes: WorkerContractRules.MaximumRepresentativeCropBytes,
            supplementalBytes: WorkerContractRules.MaximumSupplementalCropBytes);

        var result = new VisionResultValidator().Validate(JobId, Request([track],
            Accounting(1, AllRoles, WorkerContractRules.MaximumRepresentativeCropBytes, WorkerContractRules.MaximumSupplementalCropBytes)), 10_000);

        Assert.Equal(WorkerContractRules.MaximumRepresentativeCropBytes, result.Tracks[0].Representative.Crop.SizeBytes);
    }

    [Fact]
    public void AggregateCropQuotaIsEnforcedSeparatelyFromTrajectories()
    {
        // 2,000 Tracks at every role cap is ~1.04 GiB of crops, above the 1 GiB crop
        // quota, while trajectories stay far below their own 512 MiB bound.
        const int trackCount = 2_000;
        var tracks = Enumerable.Range(1, trackCount)
            .Select(index => Track($"person-{index:D6}", AllRoles, WorkerContractRules.MaximumRepresentativeCropBytes,
                WorkerContractRules.MaximumSupplementalCropBytes))
            .ToArray();
        var request = Request(tracks, Accounting(trackCount, AllRoles, WorkerContractRules.MaximumRepresentativeCropBytes,
            WorkerContractRules.MaximumSupplementalCropBytes));

        var exception = Assert.Throws<VisionResultValidationException>(
            () => new VisionResultValidator().Validate(JobId, request, 10_000));
        Assert.Equal("artifact_evidence_size_invalid", exception.ReasonCode);

        // Just under the quota is accepted: crops no longer count against the 512 MiB bound.
        const int accepted = 1_900;
        var fewer = Request(tracks[..accepted], Accounting(accepted, AllRoles, WorkerContractRules.MaximumRepresentativeCropBytes,
            WorkerContractRules.MaximumSupplementalCropBytes));
        Assert.Equal(accepted, new VisionResultValidator().Validate(JobId, fewer, 10_000).Tracks.Count);
    }

    // Builders
    private static string Prefix => $"staging/{JobId:D}/attempt-0001";

    private static VisionBoundingBoxContract Box() => new(.1, .2, .3, .4);

    private static VisionArtifactDescriptorContract Crop(string role, long sizeBytes, string trackId = "person-000001") =>
        new($"{Prefix}/evidence/{trackId}-{role}.jpg", "image/jpeg", sizeBytes, new string((char)('a' + Array.IndexOf(AllRoles, role)), 64));

    private static VisionTrackResultContract Track(
        string trackId,
        IReadOnlyList<string> roles,
        long representativeBytes = 10,
        long supplementalBytes = 10)
    {
        var observations = roles.Select((role, rank) => new VisionTrackObservationContract(
                role,
                rank,
                100 + rank * 100,
                10 + rank,
                .88,
                .8 - rank * .1,
                .8 - rank * .1,
                Box(),
                Crop(role, role == "representative" ? representativeBytes : supplementalBytes, trackId)))
            .ToArray();
        return new VisionTrackResultContract(
            trackId,
            "person",
            0,
            500,
            3,
            .85,
            .9,
            null,
            new VisionArtifactDescriptorContract($"{Prefix}/trajectories/{trackId}.msgpack", "application/msgpack", 20, new string('f', 64)),
            observations);
    }

    private static VisionEvidenceAccountingContract Accounting(
        int trackCount,
        IReadOnlyList<string> roles,
        long representativeBytes = 10,
        long supplementalBytes = 10,
        int extraNearViewCandidates = 0)
    {
        VisionEvidenceRoleAccountingContract Role(string role, long bytes, int extra)
        {
            var admitted = roles.Contains(role) ? trackCount : 0;
            var admittedBytes = admitted * bytes;
            return new VisionEvidenceRoleAccountingContract(admitted + extra, admitted, extra, admittedBytes + extra * bytes, admittedBytes);
        }

        return new VisionEvidenceAccountingContract(
            Role("representative", representativeBytes, 0),
            Role("near-view", supplementalBytes, extraNearViewCandidates),
            Role("early-diverse", supplementalBytes, 0),
            Role("late-diverse", supplementalBytes, 0));
    }

    private static VisionJobCompleteRequest Request(
        VisionTrackResultContract[] tracks,
        VisionEvidenceAccountingContract? accounting = null) =>
        new(
            "3.0",
            JobId,
            "gpu-sdd-01",
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            1,
            20,
            900,
            VisionResultValidatorTestProvenance.Create(),
            tracks,
            accounting ?? Accounting(tracks.Length, tracks.Length == 0 ? [] : tracks[0].Observations?.Select(x => x.Role!).ToArray() ?? []));

    private static VisionTrackResultContract Mutate(
        VisionTrackResultContract track, int index, Func<VisionTrackObservationContract, VisionTrackObservationContract> change) =>
        track with { Observations = [.. track.Observations!.Select((o, i) => i == index ? change(o) : o)] };

    private static VisionJobCompleteRequest Replace(
        VisionJobCompleteRequest request,
        VisionTrackResultContract track,
        int index,
        Func<VisionTrackObservationContract, VisionTrackObservationContract> change) =>
        request with { Tracks = [Mutate(track, index, change)] };
}
