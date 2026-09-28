using Mavi.Application.Modules.VisualAttributes;
using Mavi.Application.Modules.VisualAttributes.Completion;
using Mavi.Application.Modules.VisualAttributes.Release;
using Mavi.Contracts.Worker.Attributes;
using Mavi.Domain.VisualAttributes;

namespace Mavi.Application.Tests.VisualAttributes;

/// <summary>
/// Phase A's typed rules (S2b plan §13): one valid completion, then each rule broken alone.
/// Pure: no database, no clock, no capability.
/// </summary>
public sealed class VisualAttributeCompletionValidatorTests
{
    private static readonly VisualAttributeReleaseDefinition Definition =
        VisualAttributeReleaseParserTests.ParseFixture(VisualAttributeReleaseParserTests.BindingWithAttributesRole()).Definition!;
    private static readonly VisualAttributeIdentityFields Identity = Definition.Identity.ToFields();
    private static readonly Guid AnalysisId = Guid.Parse("01a0e000-0000-7000-8000-000000000001");
    private static readonly Guid Person = Guid.Parse("01a0e000-0000-7000-8000-0000000000a1");
    private static readonly Guid Vehicle = Guid.Parse("01a0e000-0000-7000-8000-0000000000b1");
    private static readonly Guid Bare = Guid.Parse("01a0e000-0000-7000-8000-0000000000c1");
    private static readonly Guid PersonCrop = Guid.Parse("01a0e000-0000-7000-8000-0000000000a2");
    private static readonly Guid VehicleCrop = Guid.Parse("01a0e000-0000-7000-8000-0000000000b2");
    private static readonly Guid ForeignCrop = Guid.Parse("01a0e000-0000-7000-8000-0000000000f1");

    private static readonly IReadOnlyList<CompletionTrackScope> Scope =
    [
        new(Person, "person", new HashSet<Guid> { PersonCrop }),
        new(Vehicle, "vehicle", new HashSet<Guid> { VehicleCrop }),
        new(Bare, "person", new HashSet<Guid>()),
    ];

    private static VisualAttributeProvenanceContract Provenance(string device = "cpu") => new(
        VisualAttributeContractRules.ProvenanceContract, "attributes",
        [
            new("person-attributes", VisualAttributeReleaseParserTests.PersonPack, new string('1', 64), "person-attributes-fixture", new string('2', 64), "unverified"),
            new("vehicle-attributes", VisualAttributeReleaseParserTests.VehiclePack, new string('3', 64), "vehicle-attributes-fixture", new string('4', 64), "unverified"),
        ],
        "mmdetection-phase1-v1", new string('5', 64), "linux-x86_64-cpu", null, "unpacked-environment",
        new string('6', 64), new string('7', 64), "cpu", device, null, null);

    private static VisualAttributeRowContract Observed(string type, string value = "dark", Guid? supporting = null) =>
        new(type, VisualAttributeContractRules.OutcomeObserved, value, 0.75, supporting ?? PersonCrop);

    private static VisualAttributeCompleteRequest Valid() => new(
        VisualAttributeContractRules.SchemaVersion, AnalysisId, "attributes-01", 1, Provenance(),
        new VisualAttributeCompletionPayloadContract(
            new VisualAttributeArtifactDescriptorContract(VisualAttributeContractRules.PredictionsMediaType, 1234, new string('8', 64)),
            [
                new(Person, VisualAttributeContractRules.OutcomeAnalysed, null,
                    [Observed("fixture-person-lower"), new("fixture-person-upper", VisualAttributeContractRules.OutcomeUnknown, null, null, null)]),
                new(Vehicle, VisualAttributeContractRules.OutcomeAnalysed, null, [Observed("fixture-vehicle-body", "light", VehicleCrop)]),
                new(Bare, VisualAttributeContractRules.OutcomeUnavailable, "no_accepted_evidence", []),
            ]));

    private static CompletionValidation Validate(VisualAttributeCompleteRequest request) =>
        VisualAttributeCompletionValidator.Validate(AnalysisId, request, Identity, Definition.Schema, Scope);

    private static VisualAttributeCompleteRequest WithTracks(params VisualAttributeTrackResultContract[] tracks) =>
        Valid() with { Payload = Valid().Payload! with { Tracks = tracks } };

    private static VisualAttributeTrackResultContract Track(Guid id) => Valid().Payload!.Tracks!.Single(item => item.TrackId == id);

    [Fact]
    public void AValidCompletionIsAcceptedWithItsCountsAndSortedRows()
    {
        var result = Validate(Valid());
        Assert.True(result.IsValid, result.ErrorCode);
        var completion = result.Completion!;
        Assert.Equal((2, 1, 2, 1), (completion.TracksAnalysed, completion.TracksUnavailable, completion.AttributesObserved, completion.AttributesUnknown));
        Assert.Equal(completion.Tracks.Select(item => item.TrackId).Order(), completion.Tracks.Select(item => item.TrackId));
        Assert.Matches("^[0-9a-f]{64}$", completion.CompletionDigest);
    }

    [Fact]
    public void TheDigestIsStableUnderTrackOrderAndMovesWithEveryFact()
    {
        var digest = Validate(Valid()).Completion!.CompletionDigest;
        var tracks = Valid().Payload!.Tracks!;
        Assert.Equal(digest, Validate(WithTracks([.. tracks.Reverse()])).Completion!.CompletionDigest);
        Assert.NotEqual(digest, Validate(Valid() with { Provenance = Provenance("cuda:1") }).Completion!.CompletionDigest);
        Assert.NotEqual(digest, Validate(Valid() with { AttemptCount = 2 }).Completion!.CompletionDigest);
        Assert.NotEqual(digest, Validate(WithTracks(
            Track(Person) with { Attributes = [Observed("fixture-person-lower", "mid"), Track(Person).Attributes![1]] },
            Track(Vehicle), Track(Bare))).Completion!.CompletionDigest);
    }

    public static TheoryData<string, Func<VisualAttributeCompleteRequest>> Broken => new()
    {
        // Coverage: exactly one outcome per applicable Track of the run.
        { "visual_attribute_track_coverage_invalid", () => WithTracks(Track(Person), Track(Vehicle)) },
        { "visual_attribute_track_coverage_invalid", () => WithTracks(Track(Person), Track(Person), Track(Bare)) },
        { "visual_attribute_track_coverage_invalid", () => WithTracks(Track(Person), Track(Vehicle), Track(Bare) with { TrackId = Guid.NewGuid() }) },
        // One final row per applicable attribute type: a missing row is not Unknown.
        { "visual_attribute_row_cardinality_invalid", () => WithTracks(Track(Person) with { Attributes = [Observed("fixture-person-lower")] }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_row_cardinality_invalid", () => WithTracks(Track(Person) with { Attributes = [Observed("fixture-person-lower"), Observed("fixture-person-lower")] }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_row_cardinality_invalid", () => WithTracks(Track(Person), Track(Vehicle) with { Attributes = [Observed("fixture-person-lower", "dark", VehicleCrop)] }, Track(Bare)) },
        // Observed asserts a schema value with a confidence and one of the Track's own crops.
        { "visual_attribute_row_invalid", () => WithTracks(Track(Person) with { Attributes = [Observed("fixture-person-lower", "plaid"), Track(Person).Attributes![1]] }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_row_invalid", () => WithTracks(Track(Person) with { Attributes = [Observed("fixture-person-lower", "dark", ForeignCrop), Track(Person).Attributes![1]] }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_row_invalid", () => WithTracks(Track(Person) with { Attributes = [Observed("fixture-person-lower", "dark", VehicleCrop), Track(Person).Attributes![1]] }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_row_invalid", () => WithTracks(Track(Person) with { Attributes = [Observed("fixture-person-lower") with { SupportingObservationId = null }, Track(Person).Attributes![1]] }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_row_invalid", () => WithTracks(Track(Person) with { Attributes = [Observed("fixture-person-lower") with { Confidence = 1.5 }, Track(Person).Attributes![1]] }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_row_invalid", () => WithTracks(Track(Person) with { Attributes = [Observed("fixture-person-lower") with { Confidence = double.NaN }, Track(Person).Attributes![1]] }, Track(Vehicle), Track(Bare)) },
        // Unknown asserts nothing.
        { "visual_attribute_row_invalid", () => WithTracks(Track(Person) with { Attributes = [Observed("fixture-person-lower"), new("fixture-person-upper", "unknown", "dark", null, null)] }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_row_invalid", () => WithTracks(Track(Person) with { Attributes = [Observed("fixture-person-lower"), new("fixture-person-upper", "unknown", null, null, PersonCrop)] }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_row_invalid", () => WithTracks(Track(Person) with { Attributes = [Observed("fixture-person-lower"), new("fixture-person-upper", "absent", null, null, null)] }, Track(Vehicle), Track(Bare)) },
        // Unavailable only for platform-authoritative reasons; no_accepted_evidence only when true.
        { "visual_attribute_track_outcome_invalid", () => WithTracks(Track(Person) with { Outcome = "unavailable", Reason = "model_uncertain", Attributes = [] }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_track_outcome_invalid", () => WithTracks(Track(Person) with { Outcome = "unavailable", Reason = "no_accepted_evidence", Attributes = [] }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_track_outcome_invalid", () => WithTracks(Track(Person), Track(Vehicle), Track(Bare) with { Reason = "evidence_missing" }) },
        { "visual_attribute_track_outcome_invalid", () => WithTracks(Track(Person) with { Outcome = "unavailable", Reason = "evidence_missing" }, Track(Vehicle), Track(Bare)) },
        { "visual_attribute_track_outcome_invalid", () => WithTracks(Track(Person), Track(Vehicle), Track(Bare) with { Outcome = "analysed", Reason = null }) },
        // The producer is exactly the unit's identity.
        { "visual_attribute_provenance_identity_mismatch", () => Valid() with { Provenance = Provenance() with { Capabilities = [Provenance().Capabilities![1], Provenance().Capabilities![0]] } } },
        { "visual_attribute_provenance_identity_mismatch", () => Valid() with { Provenance = Provenance() with { Capabilities = [Provenance().Capabilities![0] with { ModelPackId = "mavi-model-v2-" + new string('9', 64) }, Provenance().Capabilities![1]] } } },
        { "visual_attribute_provenance_invalid", () => Valid() with { Provenance = Provenance() with { ProvenanceContract = "vision-job-complete-v3.2" } } },
        { "visual_attribute_provenance_invalid", () => Valid() with { Provenance = Provenance() with { Capabilities = [Provenance().Capabilities![0] with { VerificationStatus = "verified" }, Provenance().Capabilities![1]] } } },
        { "visual_attribute_provenance_invalid", () => Valid() with { Provenance = Provenance() with { RuntimePackId = "mavi-runtime-v2-" + new string('1', 64) } } },
        { "visual_attribute_provenance_invalid", () => Valid() with { Provenance = Provenance() with { ActualDevice = "cuda:01" } } },
        { "visual_attribute_prediction_descriptor_invalid", () => Valid() with { Payload = Valid().Payload! with { PredictionArtifact = new("application/msgpack", 1234, new string('8', 64)) } } },
        { "visual_attribute_prediction_descriptor_invalid", () => Valid() with { Payload = Valid().Payload! with { PredictionArtifact = new(VisualAttributeContractRules.PredictionsMediaType, VisualAttributeContractRules.MaximumPredictionArtifactBytes + 1, new string('8', 64)) } } },
        { "visual_attribute_completion_invalid", () => Valid() with { AnalysisId = Guid.NewGuid() } },
        { "worker_contract_version_unsupported", () => Valid() with { SchemaVersion = "mavi-visual-attribute-control-v0" } },
    };

    [Theory]
    [MemberData(nameof(Broken))]
    public void EachRuleRefusesAloneWithItsCode(string code, Func<VisualAttributeCompleteRequest> request)
    {
        var result = Validate(request());
        Assert.False(result.IsValid);
        Assert.Equal(code, result.ErrorCode);
    }
}
