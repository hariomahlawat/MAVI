using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>One page of results.</summary>
/// <remarks>
/// <paramref name="Coverage"/> and <paramref name="ItemAnalytics"/> are set only for an
/// analytics-dependent query. Item analytics are keyed by Track id rather than carried
/// on <see cref="TrackSearchRow"/>, so the row the ordinary path projects from the
/// database is untouched.
/// </remarks>
public sealed record TrackSearchPage(
    IReadOnlyList<TrackSearchRow> Items,
    string? NextCursor,
    TrackAnalyticsCoverage? Coverage = null,
    IReadOnlyDictionary<Guid, TrackItemAnalytics>? ItemAnalytics = null);

public sealed record TrackSearchRow(
    Guid Id,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    Guid CameraId,
    string CameraCode,
    string CameraName,
    ObjectClass ObjectClass,
    DateTimeOffset StartTimestampUtc,
    DateTimeOffset EndTimestampUtc,
    long StartOffsetMs,
    long EndOffsetMs,
    long DurationMs,
    int DetectionCount,
    double MeanConfidence,
    double MaxConfidence,
    ReviewStatus ReviewStatus,
    Guid? ThumbnailArtifactId);

public sealed record TrackDetailRow(
    Guid Id,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    Guid CameraId,
    string CameraCode,
    string CameraName,
    ObjectClass ObjectClass,
    int LocalTrackNumber,
    long StartOffsetMs,
    long EndOffsetMs,
    DateTimeOffset StartTimestampUtc,
    DateTimeOffset EndTimestampUtc,
    long DurationMs,
    int DetectionCount,
    double MeanConfidence,
    double MaxConfidence,
    ReviewStatus ReviewStatus,
    string PipelineVersion,
    string? DetectorName,
    string? DetectorVersion,
    string? TrackerName,
    string? TrackerVersion,
    DateTimeOffset CompletedAtUtc,
    DateTimeOffset RecordingStartUtc,
    DateTimeOffset RecordingEndUtc,
    long VideoDurationMs,
    int Width,
    int Height,
    int FrameRateNumerator,
    int FrameRateDenominator,
    Guid? RepresentativeObservationId,
    long? RepresentativeSourceFrameNumber,
    long? RepresentativeVideoOffsetMs,
    DateTimeOffset? RepresentativeTimestampUtc,
    double? RepresentativeConfidence,
    double? RepresentativeQualityScore,
    float? BoundingBoxX,
    float? BoundingBoxY,
    float? BoundingBoxWidth,
    float? BoundingBoxHeight,
    Guid? ThumbnailArtifactId,
    Guid? TrajectoryArtifactId);

// --- Analytics (Slice 4) ---------------------------------------------------

/// <summary>
/// How much of an analytic query's scope was evaluated, computed over the distinct
/// runs of the base candidate set (plan §H). The Application-side twin of the
/// coverage contract; the endpoint maps it one-to-one.
/// </summary>
public sealed record TrackAnalyticsCoverage(
    Guid? SceneRevisionId,
    string AlgorithmVersion,
    int EvaluatedRuns,
    int PendingRuns,
    int FailedRuns,
    int NotConfiguredRuns,
    int DisabledRuns,
    int StaleRuns,
    int AnalysedTracks,
    int UnavailableTracks)
{
    public bool Complete =>
        PendingRuns == 0 &&
        FailedRuns == 0 &&
        NotConfiguredRuns == 0 &&
        DisabledRuns == 0 &&
        StaleRuns == 0;
}

public sealed record TrackItemZoneAnalytics(Guid ZoneId, int VisitCount, long TotalDwellMs, bool Loitering);

/// <summary><paramref name="MatchedDirection"/> is the persisted form; the endpoint maps it to the wire.</summary>
public sealed record TrackItemLineAnalytics(
    Guid LineId,
    int CrossingCount,
    string? MatchedDirection,
    DateTimeOffset? FirstMatchedCrossingUtc);

public sealed record TrackItemMotionAnalytics(string Heading, long LongestStationaryMs);

/// <summary>The bounded explanation attached to one search row.</summary>
public sealed record TrackItemAnalytics(
    Guid SceneRevisionId,
    string AlgorithmVersion,
    IReadOnlyList<TrackItemZoneAnalytics> Zones,
    IReadOnlyList<TrackItemLineAnalytics> Lines,
    TrackItemMotionAnalytics? Motion);
