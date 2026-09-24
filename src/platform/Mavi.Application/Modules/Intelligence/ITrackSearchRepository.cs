using Mavi.Domain.SceneAnalytics;

namespace Mavi.Application.Modules.Intelligence;

public sealed record TrackCursorPosition(
    DateTimeOffset SnapshotUtc,
    long SnapshotVisibilitySequence,
    DateTimeOffset StartTimestampUtc,
    Guid TrackId,
    string FilterFingerprint);

public sealed record TrackSearchRepositoryPage(
    IReadOnlyList<TrackSearchRow> Items,
    DateTimeOffset SnapshotUtc,
    long SnapshotVisibilitySequence);

/// <summary>
/// One page of an analytic search, with everything the first page resolved: the pinned
/// identity, the coverage of the base candidate scope, and the bounded explanation for
/// each row on this page.
/// </summary>
public sealed record TrackAnalyticsSearchRepositoryPage(
    IReadOnlyList<TrackSearchRow> Items,
    DateTimeOffset SnapshotUtc,
    long SnapshotVisibilitySequence,
    TrackAnalyticsPinnedIdentity Identity,
    TrackAnalyticsCoverage Coverage,
    IReadOnlyDictionary<Guid, TrackItemAnalytics> ItemAnalytics);

/// <summary>
/// The outcome of an analytic search at the repository: a page, or a refusal because the
/// query's scope did not resolve to one camera, named geometry outside the resolved
/// revision, or pinned a revision that is not this camera's (plan §H, §S).
/// </summary>
public sealed record TrackAnalyticsSearchRepositoryResult(TrackAnalyticsSearchRepositoryPage? Page)
{
    public bool IsValid => Page is not null;

    public static TrackAnalyticsSearchRepositoryResult Invalid { get; } = new((TrackAnalyticsSearchRepositoryPage?)null);
}

/// <summary>Which identity a Track's detail analytics should be read against.</summary>
/// <remarks>
/// Both null means the camera's active revision and the current engine. An explicit
/// revision that is not the Track's camera's is a refusal, never a substitution.
/// </remarks>
public sealed record TrackAnalyticsDetailRequest(Guid? SceneRevisionId, string? AlgorithmVersion)
{
    public static TrackAnalyticsDetailRequest Current { get; } = new(null, null);
}

/// <summary>Another identity that produced facts for the same run, summarised.</summary>
public sealed record TrackAnalyticsIdentitySummary(
    Guid SceneRevisionId,
    int SceneRevisionNumber,
    string AlgorithmVersion,
    SceneAnalysisStatus UnitStatus,
    TrackAnalysisOutcomeKind Outcome);

/// <summary>
/// Everything analytics knows about one Track for one identity, as the persisted facts.
/// </summary>
/// <remarks>
/// <paramref name="Status"/> is one of the contract's Track analytics statuses. Facts are
/// present only for <c>Analysed</c>; <paramref name="Outcome"/> carries the reason for
/// <c>Unavailable</c>; the remaining statuses describe the run's unit for this identity.
/// </remarks>
public sealed record TrackDetailAnalytics(
    Guid? SceneRevisionId,
    int? SceneRevisionNumber,
    string AlgorithmVersion,
    string Status,
    TrackAnalysisOutcome? Outcome,
    IReadOnlyList<TrackZoneSummary> ZoneSummaries,
    IReadOnlyList<TrackZoneVisit> ZoneVisits,
    IReadOnlyList<TrackLineCrossing> LineCrossings,
    TrackMotionSummary? MotionSummary,
    IReadOnlyList<TrackAnalyticsIdentitySummary> OtherIdentities);

/// <summary>A Track's detail analytics, or a refusal of the requested identity.</summary>
public sealed record TrackDetailAnalyticsResult(TrackDetailAnalytics? Analytics)
{
    public bool IsValid => Analytics is not null;

    public static TrackDetailAnalyticsResult Invalid { get; } = new((TrackDetailAnalytics?)null);
}

public interface ITrackSearchRepository
{
    Task<TrackSearchRepositoryPage> SearchAsync(
        TrackSearchQuery query,
        TrackCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken);

    /// <summary>
    /// An analytics-dependent search, coordinated as one operation (plan §S "First-page
    /// resolution and transaction boundary").
    /// </summary>
    /// <remarks>
    /// With no <paramref name="cursor"/>, the repository opens the read transaction that
    /// takes the shared visibility barrier, resolves every supplied scope to one camera,
    /// reads the explicit or active revision, captures the engine version, allocates the
    /// snapshot, computes coverage over the base candidate scope and fetches the page —
    /// one linearisation point. With a cursor it evaluates against the pinned identity
    /// and snapshot exactly as pinned, validating only that the pinned revision belongs to
    /// the supplied scope, and returns the pinned coverage untouched.
    /// </remarks>
    Task<TrackAnalyticsSearchRepositoryResult> SearchAnalyticsAsync(
        TrackSearchQuery query,
        TrackAnalyticsCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken);

    /// <summary>
    /// The Track's scalar detail, or null when the Track is not addressable (no such Track,
    /// or its run is not Completed). One query; no Observation is joined.
    /// </summary>
    Task<TrackDetailRow?> GetDetailAsync(Guid trackId, CancellationToken cancellationToken);

    /// <summary>
    /// Every Observation of the Track, ordered by <c>EvidenceRank</c>, as persisted and
    /// unvalidated. One bounded query, never one per Observation. It reads at most
    /// <see cref="TrackEvidenceSet.MaximumCount"/> + 1 rows, so an over-full set is seen
    /// and refused rather than silently truncated.
    /// </summary>
    Task<IReadOnlyList<TrackEvidenceObservationRow>> GetEvidenceSetAsync(
        Guid trackId,
        CancellationToken cancellationToken);

    /// <summary>
    /// The Track's analytics for the requested identity. Null when the Track is not
    /// addressable (as <see cref="GetDetailAsync"/> would say); invalid when the requested
    /// revision is not the Track's camera's.
    /// </summary>
    Task<TrackDetailAnalyticsResult?> GetDetailAnalyticsAsync(
        Guid trackId,
        TrackAnalyticsDetailRequest request,
        CancellationToken cancellationToken);
}
