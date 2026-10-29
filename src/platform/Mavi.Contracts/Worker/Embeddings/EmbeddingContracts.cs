namespace Mavi.Contracts.Worker.Embeddings;

// The embedding control plane mavi-embedding-control-v1 (PoC S4; ADR-021 §3). Capability-specific: no
// record is shared with the plate or attribute planes. The lease capability is never a member of any of
// these records. JSON Schemas: contracts/schemas/embedding-*-v1.schema.json.

public sealed record EmbeddingLeaseRequest(string? SchemaVersion, string? WorkerId, string? IdentityFingerprint);

public sealed record EmbeddingModelIdentityContract(string Id, string Version, string ManifestSha256, int Dimension);

public sealed record EmbeddingPipelineIdentityContract(string Id, string Version, string Sha256);

public sealed record EmbeddingIdentityContract(
    string Fingerprint,
    string SchemaVersion,
    EmbeddingModelIdentityContract Model,
    EmbeddingPipelineIdentityContract Pipeline);

public sealed record EmbeddingLeaseObservationContract(
    Guid ObservationId,
    string Role,
    int EvidenceRank,
    long SizeBytes,
    string Sha256);

public sealed record EmbeddingLeaseTrackContract(
    Guid TrackId,
    string ObjectClass,
    IReadOnlyList<EmbeddingLeaseObservationContract> Observations);

public sealed record EmbeddingLeaseContract(
    string SchemaVersion,
    Guid AnalysisId,
    Guid ProcessingRunId,
    string WorkerId,
    int AttemptCount,
    DateTimeOffset LeaseExpiresAtUtc,
    DateTimeOffset DeadlineAtUtc,
    EmbeddingIdentityContract Identity,
    IReadOnlyList<EmbeddingLeaseTrackContract> Tracks);

public sealed record EmbeddingHeartbeatRequest(string? SchemaVersion, Guid AnalysisId, string? WorkerId, int? AttemptCount);

public sealed record EmbeddingHeartbeatResponse(string SchemaVersion, DateTimeOffset LeaseExpiresAtUtc);

public sealed record EmbeddingFailRequest(
    string? SchemaVersion,
    Guid AnalysisId,
    string? WorkerId,
    int? AttemptCount,
    string? FailureCode,
    string? FailureMessage);

public sealed record EmbeddingFailResponse(string SchemaVersion, string Outcome);

public sealed record EmbeddingProvenanceContract(
    string? RoleId,
    string? IdentityFingerprint,
    string? RuntimeProfileId,
    string? RuntimeVariant,
    string? ExecutionProvider,
    string? ActualDevice,
    string? DeviceResolutionReason,
    string? OnnxRuntimeVersion,
    string? WorkerVersion);

/// <summary>One Track's outcome: <c>embedded</c> with a vector, or <c>unavailable</c> with a reason.</summary>
public sealed record EmbeddingTrackResultContract(
    Guid TrackId,
    string? Outcome,
    IReadOnlyList<Guid>? SourceObservationIds,
    string? Embedding,
    string? Reason);

public sealed record EmbeddingCompleteRequest(
    string? SchemaVersion,
    Guid AnalysisId,
    string? WorkerId,
    int? AttemptCount,
    EmbeddingProvenanceContract? Provenance,
    IReadOnlyList<EmbeddingTrackResultContract>? Tracks);

public sealed record EmbeddingCompleteResponse(
    string SchemaVersion,
    Guid AnalysisId,
    Guid ProcessingRunId,
    string Status,
    DateTimeOffset CompletedAtUtc,
    int TracksEmbedded,
    int TracksUnavailable);

// --- Appearance text queries (ADR-021 §4) --------------------------------------------------

public sealed record EmbeddingTextQueryLeaseContract(
    string SchemaVersion,
    Guid QueryId,
    string WorkerId,
    int AttemptCount,
    DateTimeOffset LeaseExpiresAtUtc,
    string IdentityFingerprint,
    string Text);

public sealed record EmbeddingTextQueryCompleteRequest(
    string? SchemaVersion,
    Guid QueryId,
    string? WorkerId,
    int? AttemptCount,
    string? Embedding);

public sealed record EmbeddingTextQueryFailRequest(
    string? SchemaVersion,
    Guid QueryId,
    string? WorkerId,
    int? AttemptCount,
    string? FailureCode,
    string? FailureMessage);

public sealed record EmbeddingTextQueryCompleteResponse(string SchemaVersion, string Status);
