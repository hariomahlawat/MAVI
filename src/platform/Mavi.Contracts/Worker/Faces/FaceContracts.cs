using System.Text.Json.Serialization;

namespace Mavi.Contracts.Worker.Faces;

// The face control plane mavi-face-control-v1 (PoC S6; ADR-022 §3–§4). Capability-specific, on the embedding
// plane's shape: no record is shared with another plane, and the lease capability is never a member of any of
// these records. Design: docs/architecture/poc-s6-faces-implementation.md §2.

public sealed record FaceLeaseRequest(string? SchemaVersion, string? WorkerId, string? IdentityFingerprint);

public sealed record FaceModelIdentityContract(string Id, string Version, string ManifestSha256, int Dimension);

public sealed record FacePipelineIdentityContract(string Id, string Version, string Sha256);

public sealed record FaceIdentityContract(
    string Fingerprint,
    string SchemaVersion,
    FaceModelIdentityContract Model,
    FacePipelineIdentityContract Pipeline);

public sealed record FaceLeaseObservationContract(Guid ObservationId, string Role, int EvidenceRank, long SizeBytes, string Sha256);

public sealed record FaceLeaseTrackContract(Guid TrackId, string ObjectClass, IReadOnlyList<FaceLeaseObservationContract> Observations);

public sealed record FaceLeaseContract(
    string SchemaVersion,
    Guid AnalysisId,
    Guid ProcessingRunId,
    string WorkerId,
    int AttemptCount,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset LeaseExpiresAtUtc,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset DeadlineAtUtc,
    FaceIdentityContract Identity,
    IReadOnlyList<FaceLeaseTrackContract> Tracks);

public sealed record FaceHeartbeatRequest(string? SchemaVersion, Guid AnalysisId, string? WorkerId, int? AttemptCount);

public sealed record FaceHeartbeatResponse(
    string SchemaVersion,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset LeaseExpiresAtUtc);

public sealed record FaceFailRequest(
    string? SchemaVersion,
    Guid AnalysisId,
    string? WorkerId,
    int? AttemptCount,
    string? FailureCode,
    string? FailureMessage);

public sealed record FaceFailResponse(string SchemaVersion, string Outcome);

public sealed record FaceProvenanceContract(
    string? RoleId,
    string? IdentityFingerprint,
    string? RuntimeProfileId,
    string? RuntimeVariant,
    string? ExecutionProvider,
    string? ActualDevice,
    string? DeviceResolutionReason,
    string? OnnxRuntimeVersion,
    string? WorkerVersion);

public sealed record FaceBoxContract(double? X, double? Y, double? Width, double? Height);

/// <summary>
/// One detected face in crop pixels: box, five landmarks, score; <c>usable</c> faces (shorter side at least the
/// profile's minimum) carry an embedding, and in a query completion a 112×112 aligned JPEG <c>thumbnail</c>.
/// </summary>
public sealed record FaceDetectionContract(
    Guid? ObservationId,
    FaceBoxContract? Box,
    IReadOnlyList<IReadOnlyList<double>>? Landmarks,
    double? Score,
    bool? Usable,
    string? Embedding,
    string? Thumbnail);

/// <summary>One Track's outcome: <c>observed</c> (at least one usable face) or <c>unknown</c> with a reason.</summary>
public sealed record FaceTrackResultContract(
    Guid TrackId,
    string? Outcome,
    string? Reason,
    IReadOnlyList<FaceDetectionContract>? Faces);

public sealed record FaceCompleteRequest(
    string? SchemaVersion,
    Guid AnalysisId,
    string? WorkerId,
    int? AttemptCount,
    FaceProvenanceContract? Provenance,
    IReadOnlyList<FaceTrackResultContract>? Tracks);

public sealed record FaceCompleteResponse(
    string SchemaVersion,
    Guid AnalysisId,
    Guid ProcessingRunId,
    string Status,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset CompletedAtUtc,
    int TracksObserved,
    int TracksUnknown);

// --- Transient query images (ADR-022 §4–§5) --------------------------------------------------

public sealed record FaceQueryImageContract(string MimeType, long SizeBytes, string Sha256);

public sealed record FaceQueryLeaseContract(
    string SchemaVersion,
    Guid QueryId,
    string WorkerId,
    int AttemptCount,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset LeaseExpiresAtUtc,
    FaceIdentityContract Identity,
    FaceQueryImageContract Image);

public sealed record FaceQueryCompleteRequest(
    string? SchemaVersion,
    Guid QueryId,
    string? WorkerId,
    int? AttemptCount,
    IReadOnlyList<FaceDetectionContract>? Faces);

public sealed record FaceQueryFailRequest(
    string? SchemaVersion,
    Guid QueryId,
    string? WorkerId,
    int? AttemptCount,
    string? FailureCode,
    string? FailureMessage);

public sealed record FaceQueryCompleteResponse(string SchemaVersion, string Status);
