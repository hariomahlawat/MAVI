using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.SceneAnalytics.Aggregates;

/// <summary>A bucketed aggregate request for one camera and window.</summary>
public sealed record AnalyticsAggregateQuery(
    Guid CameraId,
    DateTimeOffset FromUtc,
    DateTimeOffset ToUtc,
    int BucketSeconds,
    ObjectClass? ObjectClass);

/// <summary>A heatmap request for one camera and window.</summary>
/// <remarks>
/// <paramref name="ProcessingRunId"/> narrows the scope to one completed, published
/// run of the same camera. It is the only place Slice 6 accepts a run id, and it is
/// resolved through the ordinary non-enumerating boundary: an unknown, hidden or
/// cross-camera id is indistinguishable from a missing camera.
/// </remarks>
public sealed record AnalyticsHeatmapQuery(
    Guid CameraId,
    DateTimeOffset FromUtc,
    DateTimeOffset ToUtc,
    ObjectClass? ObjectClass,
    int GridWidth,
    Guid? ProcessingRunId);

/// <summary>Why an analytics query could not be answered.</summary>
public enum AnalyticsFailure
{
    None = 0,
    /// <summary>The camera does not exist, or a supplied run is not visibly its own.</summary>
    NotFound,
    /// <summary>The request was refused before work began: too many runs or candidate Tracks.</summary>
    ScopeTooLarge,
    /// <summary>Evidence an analysed unit says exists could not be read as valid.</summary>
    EvidenceUnreadable,
}

/// <summary>
/// The analytical identity one response was resolved against, established once under
/// the visibility barrier and used for every part of that answer.
/// </summary>
public sealed record AnalyticsResolvedIdentity(
    Guid CameraId,
    Guid? SceneRevisionId,
    int? SceneRevisionNumber,
    string AlgorithmVersion,
    long SnapshotVisibilitySequence);

/// <summary>The aggregate answer, or why there is not one.</summary>
public sealed record AnalyticsAggregateResult(
    AnalyticsFailure Failure,
    AnalyticsResolvedIdentity? Identity = null,
    TrackAnalyticsCoverage? Coverage = null,
    AnalyticsFactSet? Facts = null)
{
    public static AnalyticsAggregateResult NotFound { get; } = new(AnalyticsFailure.NotFound);

    public bool IsSuccess => Failure == AnalyticsFailure.None;
}

/// <summary>
/// The cheap heatmap scope: everything needed to decide whether the request is
/// answerable at all, resolved without opening a single trajectory artefact.
/// </summary>
/// <remarks>
/// <paramref name="CoveredRunCount"/> and <paramref name="CandidateTrackCount"/> are
/// the two bounded dimensions of plan §5.5. They are database-side counts, which is
/// what lets the guard run before the I/O it exists to bound.
/// </remarks>
public sealed record AnalyticsHeatmapScope(
    AnalyticsFailure Failure,
    AnalyticsResolvedIdentity? Identity = null,
    TrackAnalyticsCoverage? Coverage = null,
    int CoveredRunCount = 0,
    int CandidateTrackCount = 0)
{
    public static AnalyticsHeatmapScope NotFound { get; } = new(AnalyticsFailure.NotFound);

    public bool IsSuccess => Failure == AnalyticsFailure.None;
}

/// <summary>
/// One analysed Track whose sealed trajectory is a heatmap candidate.
/// </summary>
/// <param name="RecordingStartUtc">
/// The immutable source recording start. A sample's absolute instant is this plus
/// its media-relative offset; nothing else reconstructs it.
/// </param>
/// <param name="StorageKey">
/// Null when the artefact row the Track referenced is gone. The Track is still a
/// candidate: the unit recorded it as <c>Analysed</c>, which the executor only does
/// after reading and hashing a trajectory, so evidence that has since disappeared is
/// an integrity failure rather than a Track with nothing to read.
/// </param>
/// <param name="Sha256">
/// The digest the artefact was sealed with, which is the authority on its bytes.
/// </param>
public sealed record HeatmapCandidateTrack(
    Guid TrackId,
    DateTimeOffset RecordingStartUtc,
    string? StorageKey,
    string? Sha256);

/// <summary>The heatmap answer, or why there is not one.</summary>
public sealed record AnalyticsHeatmapResult(
    AnalyticsFailure Failure,
    AnalyticsResolvedIdentity? Identity = null,
    TrackAnalyticsCoverage? Coverage = null,
    HeatmapGrid? Grid = null,
    int TrackCount = 0,
    string? ExceededDimension = null,
    int ExceededLimit = 0)
{
    public bool IsSuccess => Failure == AnalyticsFailure.None;
}

/// <summary>
/// The read-only analytical scope and fact source behind the Slice-6 projections.
/// </summary>
/// <remarks>
/// Split deliberately into a cheap scope resolution and an expensive candidate
/// listing so the caller can refuse an oversized request between them. A port that
/// answered "give me the heatmap" in one call would have to open artefacts to
/// discover it should not have.
/// </remarks>
public interface IAnalyticsAggregateRepository
{
    Task<AnalyticsAggregateResult> AggregateAsync(
        AnalyticsAggregateQuery query,
        CancellationToken cancellationToken);

    /// <summary>
    /// Resolves identity, coverage and both bounded dimensions under one visibility
    /// snapshot, without touching evidence.
    /// </summary>
    Task<AnalyticsHeatmapScope> ResolveHeatmapScopeAsync(
        AnalyticsHeatmapQuery query,
        CancellationToken cancellationToken);

    /// <summary>
    /// The candidate Tracks of an already-accepted scope, in a deterministic order.
    /// Called only after the work bounds have been cleared.
    /// </summary>
    Task<IReadOnlyList<HeatmapCandidateTrack>> ListHeatmapCandidatesAsync(
        AnalyticsHeatmapQuery query,
        AnalyticsResolvedIdentity identity,
        CancellationToken cancellationToken);
}

/// <summary>Reads one sealed trajectory artefact through the accepted-evidence boundary.</summary>
public interface IHeatmapEvidenceReader
{
    /// <summary>The artefact's bytes, or null when it is not there.</summary>
    Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken);
}
