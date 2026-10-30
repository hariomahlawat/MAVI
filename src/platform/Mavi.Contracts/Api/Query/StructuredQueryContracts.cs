using System.Text.Json;
using Mavi.Contracts.Api.Analytics;

namespace Mavi.Contracts.Api.Query;

/// <summary>
/// The result envelope of a structured query (ADR-024 §6). Every answer states what was asked (the canonical query
/// and its fingerprint), the snapshot it was read in, the identities it was evaluated against, how much of the scope
/// was covered, the result, and the Development disclosure.
/// </summary>
public sealed record QueryEnvelopeResponse(
    string ContractVersion,
    JsonElement ResolvedQuery,
    string QueryFingerprint,
    string Unit,
    string Operation,
    QuerySnapshotResponse Snapshot,
    QueryIdentityResponse Identity,
    QueryCoverageResponse Coverage,
    QueryResultResponse Result,
    string Disclosure);

/// <param name="VisibilitySequence">The snapshot sequence; null when nothing was read (an Entity query).</param>
/// <param name="SimilaritySnapshot">The signed S4 snapshot a <c>similarTo</c> query was ranked in.</param>
public sealed record QuerySnapshotResponse(long? VisibilitySequence, DateTimeOffset EvaluatedAtUtc, string? SimilaritySnapshot = null);

public sealed record QueryCameraIdentityResponse(
    Guid CameraId,
    string CameraCode,
    string CameraName,
    Guid? SceneRevisionId,
    int? SceneRevisionNumber,
    string AlgorithmVersion);

public sealed record QueryIdentityResponse(
    IReadOnlyList<QueryCameraIdentityResponse> Cameras,
    string? AttributeIdentityFingerprint = null,
    string? AttributeDisclosure = null,
    string? PlateIdentityFingerprint = null,
    string? EmbeddingIdentityFingerprint = null,
    string? EventCatalogueVersion = null);

/// <summary>
/// One part of the coverage: which capability, for which camera and which window (<c>query</c> or <c>baseline</c>),
/// with the same block that capability's own read surface reports. <paramref name="Complete"/> is computed by the
/// server from that block.
/// </summary>
public sealed record QueryCoverageComponentResponse(
    string Kind,
    string Window,
    bool Complete,
    Guid? CameraId = null,
    AnalyticsCoverageResponse? SceneAnalytics = null,
    int? DerivedRuns = null,
    int? EventsPendingRuns = null,
    QueryAttributeCoverageResponse? Attributes = null,
    QueryPlateCoverageResponse? Plates = null,
    string? Reason = null);

public sealed record QueryAttributeCoverageResponse(
    int TracksInScope,
    int Analysed,
    int Unavailable,
    int NotAnalysed,
    IReadOnlyList<QueryAttributeAbstentionResponse> Unknown);

/// <summary>Analysed Tracks whose final row for the type is Unknown: neither matched nor excluded.</summary>
public sealed record QueryAttributeAbstentionResponse(string Type, string Value, int Tracks);

public sealed record QueryPlateCoverageResponse(int VehicleTracksInScope, int Ready, int Pending, int Failed, int Stale, int NotConfigured);

public sealed record QueryCoverageResponse(bool Complete, IReadOnlyList<QueryCoverageComponentResponse> Components);

/// <summary>
/// The result, discriminated by <paramref name="Kind"/>:
/// <c>rows</c> (Tracks or Events, with <paramref name="Truncation"/>), <c>value</c>, <c>groups</c>, <c>buckets</c>,
/// <c>comparison</c>, <c>withheld</c> (coverage incomplete: no figure) or <c>empty</c> (the unit has no data, with the
/// reason). Exactly the members of its kind are set.
/// </summary>
public sealed record QueryResultResponse(
    string Kind,
    IReadOnlyList<QueryTrackRowResponse>? Tracks = null,
    IReadOnlyList<QueryEventRowResponse>? Events = null,
    QueryTruncationResponse? Truncation = null,
    long? Value = null,
    string? Dimension = null,
    IReadOnlyList<QueryGroupResponse>? Groups = null,
    int? BucketSeconds = null,
    IReadOnlyList<QueryBucketResponse>? Buckets = null,
    QueryComparisonResponse? Comparison = null,
    string? Reason = null,
    string? Message = null);

/// <summary>
/// How much of the matching set a row result shows. When coverage is incomplete <paramref name="TotalIsLowerBound"/> is
/// true: <paramref name="Total"/> counts only the analysed part of the scope, so it is "at least", never the scope's count.
/// </summary>
public sealed record QueryTruncationResponse(bool Truncated, int Returned, int Total, int Limit, bool TotalIsLowerBound = false);

/// <summary>A group: its key (an id or a vocabulary value; null for records without one) and a display label.</summary>
public sealed record QueryGroupResponse(string? Key, string Label, long Count);

public sealed record QueryBucketResponse(DateTimeOffset StartUtc, DateTimeOffset EndUtc, long Count);

public sealed record QueryComparisonResponse(long Current, long Baseline, long Difference);

public sealed record QueryTrackRowResponse(
    Guid TrackId,
    Guid CameraId,
    string CameraCode,
    string CameraName,
    Guid VideoAssetId,
    Guid ProcessingRunId,
    string ObjectClass,
    string? ObjectSubclass,
    DateTimeOffset StartTimestampUtc,
    DateTimeOffset EndTimestampUtc,
    long StartOffsetMs,
    long DurationMs,
    double MeanConfidence,
    Guid? ThumbnailArtifactId,
    double? SimilarityScore = null);

public sealed record QueryEventRowResponse(
    Guid EventId,
    string RuleId,
    int RuleVersion,
    Guid CameraId,
    string CameraCode,
    string CameraName,
    Guid VideoAssetId,
    Guid? PrimaryTrackId,
    string? ObjectClass,
    Guid? ZoneId,
    string? ZoneName,
    Guid? LineId,
    string? LineName,
    string? Direction,
    DateTimeOffset StartUtc,
    DateTimeOffset EndUtc,
    long StartOffsetMs);

/// <summary>A refusal: the request is outside the contract, or the contract cannot answer it as asked.</summary>
public sealed record QueryRefusalResponse(string Code, string Path, string Message);

/// <summary>The machine-readable vocabulary a builder or Ask MAVI composes from (<c>GET /api/query/contract</c>).</summary>
public sealed record QueryContractResponse(
    string ContractVersion,
    IReadOnlyList<QueryUnitVocabularyResponse> Units,
    IReadOnlyList<string> Operations,
    IReadOnlyList<string> ObjectClasses,
    IReadOnlyList<string> ObjectSubclasses,
    IReadOnlyList<string> ZoneRelations,
    IReadOnlyList<string> CrossingDirections,
    IReadOnlyList<string> MotionDirections,
    IReadOnlyList<string> PlateMatches,
    IReadOnlyList<QueryAttributeVocabularyResponse> Attributes,
    string? AttributeDisclosure,
    IReadOnlyList<string> EventRuleIds,
    string EventCatalogueVersion,
    QueryBoundsResponse Bounds,
    IReadOnlyList<string> RefusalCodes,
    string Disclosure);

public sealed record QueryUnitVocabularyResponse(
    string Unit,
    bool DataAvailable,
    string? UnavailableReason,
    IReadOnlyList<string> Predicates,
    IReadOnlyList<string> GroupDimensions,
    IReadOnlyList<string> DistinctFields);

public sealed record QueryAttributeVocabularyResponse(string Type, string ObjectClass, IReadOnlyList<string> Values);

public sealed record QueryBoundsResponse(
    int MaximumCameraIds,
    int DefaultFindLimit,
    int MaximumFindLimit,
    int MaximumTopK,
    int MaximumSimilarK,
    int MinimumBucketSeconds,
    int MaximumBucketSeconds,
    int MaximumBuckets,
    int MaximumMatchedRecords);
