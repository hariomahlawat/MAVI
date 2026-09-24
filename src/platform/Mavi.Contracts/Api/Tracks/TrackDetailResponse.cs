using System.Text.Json.Serialization;

namespace Mavi.Contracts.Api.Tracks;

/// <summary>One Track with its provenance and, once resolved, its analytics for one identity.</summary>
/// <remarks>
/// <see cref="Observations"/> is the Track's Evidence Set: the authoritative read-side
/// evidence, in rank order (at most four). <see cref="Representative"/> is kept for
/// compatibility, and is always derived from <c>Observations[0]</c>: it is null exactly
/// when <see cref="Observations"/> is empty, which is the legacy shape of a Track with no
/// Representative relation.
/// </remarks>
public sealed record TrackDetailResponse(
    Guid Id,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    TrackCameraResponse Camera,
    string ObjectClass,
    int LocalTrackNumber,
    long StartOffsetMs,
    long EndOffsetMs,
    DateTimeOffset StartTimestampUtc,
    DateTimeOffset EndTimestampUtc,
    long DurationMs,
    int DetectionCount,
    double MeanConfidence,
    double MaxConfidence,
    string ReviewStatus,
    TrackProcessingResponse Processing,
    TrackVideoResponse Video,
    TrackRepresentativeResponse? Representative,
    IReadOnlyList<TrackEvidenceObservationResponse> Observations,
    Guid? TrajectoryArtifactId,
    string? TrajectoryContentUrl,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    TrackDetailAnalyticsResponse? Analytics = null);

public sealed record TrackCameraResponse(Guid Id, string Code, string Name);

public sealed record TrackProcessingResponse(
    string PipelineVersion,
    string? DetectorName,
    string? DetectorVersion,
    string? TrackerName,
    string? TrackerVersion,
    DateTimeOffset CompletedAtUtc);

public sealed record TrackVideoResponse(
    DateTimeOffset RecordingStartUtc,
    DateTimeOffset RecordingEndUtc,
    long DurationMs,
    int Width,
    int Height,
    int FrameRateNumerator,
    int FrameRateDenominator,
    string VideoContentUrl);

public sealed record TrackRepresentativeResponse(
    Guid ObservationId,
    long SourceFrameNumber,
    long VideoOffsetMs,
    DateTimeOffset TimestampUtc,
    double Confidence,
    double QualityScore,
    TrackBoundingBoxResponse BoundingBox,
    Guid? ThumbnailArtifactId,
    string? ThumbnailContentUrl);

/// <summary>
/// One accepted Observation of a Track's Evidence Set (S1.3 plan §4.1).
/// </summary>
/// <remarks>
/// <see cref="EvidenceRole"/> is one of <c>Representative</c>, <c>NearView</c>,
/// <c>EarlyDiverse</c>, <c>LateDiverse</c>. <see cref="EvidenceRank"/> is its contiguous
/// position, 0 for the Representative. <see cref="EvidenceContentUrl"/> is server-authored
/// and served only by the accepted-evidence content route. Clients use it as given and
/// never build an artifact URL from <see cref="EvidenceArtifactId"/>. Neither is a claim
/// that the bytes are currently available.
/// </remarks>
public sealed record TrackEvidenceObservationResponse(
    Guid ObservationId,
    string EvidenceRole,
    int EvidenceRank,
    long SourceFrameNumber,
    long VideoOffsetMs,
    DateTimeOffset TimestampUtc,
    double Confidence,
    double QualityScore,
    double SelectionScore,
    TrackBoundingBoxResponse BoundingBox,
    Guid? EvidenceArtifactId,
    string? EvidenceContentUrl);

public sealed record TrackBoundingBoxResponse(float X, float Y, float Width, float Height);
