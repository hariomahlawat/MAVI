using System.Text.Json.Serialization;
using Mavi.Contracts.Worker.Attributes;

namespace Mavi.Contracts.Worker.Plates;

// The plate control plane `mavi-plate-control-v1` (Stage 4 plan §5.3; ADR-013 implementation
// amendment 2026-10-13, items 11–15). Every request body is the reusable envelope of ADR-013 §9 as
// amended by item 2: schemaVersion, analysisId, workerId, attemptCount, provenance and a typed
// payload. The lease capability is never a member of any of these records. JSON Schemas:
// contracts/schemas/plate-lease-v1, plate-complete-v1 and plate-predictions-v1.

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateLeaseRequest(
    string? SchemaVersion,
    string? WorkerId,
    string? IdentityFingerprint);

public sealed record PlateCapabilityIdentityContract(string CapabilityId, string ModelPackId);

public sealed record PlateNormalisationIdentityContract(string Id, string Sha256);

public sealed record PlateSummaryPolicyIdentityContract(string Id, string Version, string Sha256);

/// <summary>The plate analysis identity of ADR-013 item 11 without the run, and its fingerprint.</summary>
public sealed record PlateIdentityContract(
    string Fingerprint,
    string PipelineId,
    string PipelineVersion,
    string PredictionsSchemaVersion,
    PlateNormalisationIdentityContract Normalisation,
    PlateSummaryPolicyIdentityContract SummaryPolicy,
    IReadOnlyList<PlateCapabilityIdentityContract> Capabilities,
    string ParametersSha256);

/// <summary>One accepted EvidenceCrop the leased attempt may read, with its recorded facts.</summary>
public sealed record PlateLeaseObservationContract(
    Guid ObservationId,
    string Role,
    int EvidenceRank,
    long SizeBytes,
    string Sha256);

/// <summary>One Vehicle Track of the run; Person Tracks are not applicable and never leased.</summary>
public sealed record PlateLeaseTrackContract(
    Guid TrackId,
    string ObjectClass,
    IReadOnlyList<PlateLeaseObservationContract> Observations);

/// <summary>
/// The lease response. The capability itself is in the <c>X-Mavi-Lease-Capability</c> response
/// header, never here.
/// </summary>
public sealed record PlateLeaseContract(
    string SchemaVersion,
    Guid AnalysisId,
    Guid ProcessingRunId,
    string WorkerId,
    int AttemptCount,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset LeaseExpiresAtUtc,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset DeadlineAtUtc,
    PlateIdentityContract Identity,
    IReadOnlyList<PlateLeaseTrackContract> Tracks);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateHeartbeatRequest(
    string? SchemaVersion,
    Guid? AnalysisId,
    string? WorkerId,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? AttemptCount);

public sealed record PlateHeartbeatResponse(
    string SchemaVersion,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset LeaseExpiresAtUtc);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateFailRequest(
    string? SchemaVersion,
    Guid? AnalysisId,
    string? WorkerId,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? AttemptCount,
    string? FailureCode,
    string? FailureMessage);

/// <summary><c>requeued</c> (a retryable failure with attempts and time left) or <c>failed</c>.</summary>
public sealed record PlateFailResponse(string SchemaVersion, string Outcome);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateCapabilityProvenanceContract(
    string? CapabilityId,
    string? ModelPackId,
    string? ModelManifestSha256,
    string? QualificationId,
    string? QualificationSha256,
    string? VerificationStatus);

/// <summary>
/// Producer provenance (ADR-014 §8). Not identity: it enters the completion digest, so a replay
/// from another device or build is a conflict, but it never creates a new analysis.
/// </summary>
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateProvenanceContract(
    string? ProvenanceContract,
    string? RoleId,
    [property: JsonConverter(typeof(BoundedPlateCapabilityProvenanceListJsonConverter))]
    IReadOnlyList<PlateCapabilityProvenanceContract>? Capabilities,
    string? RuntimePackFamilyId,
    string? RuntimeProfileSha256,
    string? RuntimeVariant,
    string? RuntimePackId,
    string? RuntimePackSource,
    string? ComponentBindingSha256,
    string? PipelineProfileSha256,
    string? ConfiguredDevicePolicy,
    string? ActualDevice,
    string? MaviBuild,
    string? MaviCommit);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateArtifactDescriptorContract(
    string? MediaType,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? SizeBytes,
    string? Sha256);

/// <summary>A plate box in the decoded evidence crop's pixel space (ADR-013 item 12).</summary>
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateBoxContract(
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? X,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? Y,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? Width,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? Height);

/// <summary>
/// One kept reading: raw text only. The platform derives the normalised text, its outcome and the
/// advisory format class (ADR-013 item 13).
/// </summary>
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateReadingContract(
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? Rank,
    string? RawText,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? RawLineCount,
    double? Confidence);

/// <summary>One selected plate of one leased crop: <c>read</c> with its kept readings, or <c>unreadable</c> with none.</summary>
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateObservationResultContract(
    Guid? SourceObservationId,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? PlateIndex,
    PlateBoxContract? Box,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? CropWidth,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? CropHeight,
    double? DetectorConfidence,
    string? Outcome,
    [property: JsonConverter(typeof(BoundedPlateReadingListJsonConverter))]
    IReadOnlyList<PlateReadingContract>? Readings);

/// <summary>A plate observation named by its natural key: the worker never knows a platform row id.</summary>
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateReferenceContract(
    Guid? SourceObservationId,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? PlateIndex);

/// <summary>
/// One Track text under the summary policy, by reference: its text is the normalised rank-0 reading
/// of <see cref="BestPlate"/>, derived by the platform.
/// </summary>
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateTrackTextContract(
    PlateReferenceContract? BestPlate,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? SupportCount,
    double? MaxConfidence);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateTrackResultContract(
    Guid? TrackId,
    string? Outcome,
    string? Reason,
    [property: JsonConverter(typeof(BoundedPlateObservationListJsonConverter))]
    IReadOnlyList<PlateObservationResultContract>? PlateObservations,
    [property: JsonConverter(typeof(BoundedPlateTrackTextListJsonConverter))]
    IReadOnlyList<PlateTrackTextContract>? Texts);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateCompletionPayloadContract(
    PlateArtifactDescriptorContract? PredictionArtifact,
    [property: JsonConverter(typeof(BoundedPlateTrackListJsonConverter))]
    IReadOnlyList<PlateTrackResultContract>? Tracks);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record PlateCompleteRequest(
    string? SchemaVersion,
    Guid? AnalysisId,
    string? WorkerId,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? AttemptCount,
    PlateProvenanceContract? Provenance,
    PlateCompletionPayloadContract? Payload);

/// <summary><c>completed</c> (the run's default) or <c>superseded</c> (an obsolete identity, published as history).</summary>
public sealed record PlateCompleteResponse(
    string SchemaVersion,
    Guid AnalysisId,
    Guid ProcessingRunId,
    string Status,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset CompletedAtUtc,
    int TracksAnalysed,
    int TracksUnavailable);

// --- Bounded collections: a hostile body cannot allocate past the contract bound. ---------

public sealed class BoundedPlateTrackListJsonConverter : BoundedListJsonConverter<PlateTrackResultContract>
{
    protected override int Maximum => PlateContractRules.MaximumAnalysisTracks;
    protected override string Name => "track";
}

public sealed class BoundedPlateObservationListJsonConverter : BoundedListJsonConverter<PlateObservationResultContract>
{
    protected override int Maximum => PlateContractRules.MaximumTrackPlateObservations;
    protected override string Name => "plate observation";
}

public sealed class BoundedPlateReadingListJsonConverter : BoundedListJsonConverter<PlateReadingContract>
{
    protected override int Maximum => PlateContractRules.MaximumReadingsPerPlate;
    protected override string Name => "plate reading";
}

public sealed class BoundedPlateTrackTextListJsonConverter : BoundedListJsonConverter<PlateTrackTextContract>
{
    protected override int Maximum => PlateContractRules.MaximumTrackPlateObservations;
    protected override string Name => "plate text";
}

public sealed class BoundedPlateCapabilityProvenanceListJsonConverter : BoundedListJsonConverter<PlateCapabilityProvenanceContract>
{
    // One entry per plate capability id.
    protected override int Maximum => 2;
    protected override string Name => "capability provenance";
}
