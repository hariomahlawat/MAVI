using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The visual-attribute half of Track search and detail (PoC S5; Stage-2 plan §16).
/// </summary>
/// <remarks>
/// <para>
/// <b>Predicate.</b> A Track matches a predicate when a fact-bearing attribute analysis of its run, of the pinned
/// identity and published inside the snapshot, has the Track's final row for the type <c>Observed</c> with the
/// value: one correlated EXISTS per predicate, ANDed with every other filter before keyset and ordering, which are
/// unchanged. <c>Unknown</c> never matches and a Track whose run has no visible analysis never matches; both are
/// counted in coverage instead (no implicit negative). The identity is unique per run, so a superseding analysis
/// published mid-pagination cannot change what an open result set means (ADR-013 §16).
/// </para>
/// <para>
/// <b>Scale.</b> The predicate is probed per base candidate through <c>ix_visual_attributes_track</c>; nothing here
/// is measured at the Stage-2 E8 volume, which this PoC slice does not claim. The plate search's batching
/// (ADR-018) is the template if a measured plan needs it.
/// </para>
/// </remarks>
public sealed partial class TrackSearchRepository : ITrackAttributeSearchRepository
{
    public async Task<TrackAttributeSearchRepositoryResult> SearchAttributesAsync(
        TrackSearchQuery query,
        string? preferredFingerprint,
        string? disclosure,
        TrackAttributeCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);
        if (query.Attributes is not { } attributes)
            throw new ArgumentException("An attribute search needs attribute predicates.", nameof(query));
        if (query.IsAnalytic != (cursor?.IsAnalytic ?? query.IsAnalytic))
            throw new ArgumentException("The cursor was minted for a different query kind.", nameof(cursor));

        if (cursor is not null)
        {
            await using var continuation = await db.Database.BeginTransactionAsync(cancellationToken);
            var continued = await ContinueAttributesAsync(query, attributes, cursor, take, cancellationToken);
            await continuation.CommitAsync(cancellationToken);
            return continued;
        }

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        // As a plate first page: the barrier before any scope is read, so the snapshot, the analyses it admits and
        // both coverage blocks describe one world.
        await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(db, cancellationToken);
        var snapshotVisibilitySequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);
        var snapshotUtc = timeProvider.GetUtcNow().ToUniversalTime();

        var coverage = await ComputeAttributeCoverageAsync(
            query, attributes, preferredFingerprint, disclosure, snapshotVisibilitySequence, cancellationToken);

        TrackAttributeSearchRepositoryPage page;
        if (query.Analytics is { } analytics)
        {
            var cameraId = await ResolveCameraAsync(query, cancellationToken);
            if (cameraId is null)
                return TrackAttributeSearchRepositoryResult.Invalid;
            var scope = await ResolveRevisionAsync(cameraId.Value, analytics.SceneRevisionId, cancellationToken);
            if (scope is null)
                return TrackAttributeSearchRepositoryResult.Invalid;
            var identity = new TrackAnalyticsPinnedIdentity(
                cameraId.Value,
                scope.Revision?.Id,
                analytics.AnalyticsAlgorithmVersion ?? SceneAnalyticsAlgorithm.Version);
            if (!OwnsGeometry(scope.Revision, analytics))
                return TrackAttributeSearchRepositoryResult.Invalid;

            var analyticsCoverage = await ComputeCoverageAsync(query, identity, scope, snapshotVisibilitySequence, cancellationToken);
            page = await FetchAnalyticAttributePageAsync(
                query, attributes, analytics, identity, analyticsCoverage, scope, preferredFingerprint, coverage,
                snapshotUtc, snapshotVisibilitySequence, keyset: null, take, cancellationToken);
        }
        else
        {
            page = await FetchAttributePageAsync(
                query, attributes, preferredFingerprint, coverage, snapshotUtc, snapshotVisibilitySequence, keyset: null, take,
                cancellationToken);
        }

        await transaction.CommitAsync(cancellationToken);
        return new TrackAttributeSearchRepositoryResult(page);
    }

    private async Task<TrackAttributeSearchRepositoryResult> ContinueAttributesAsync(
        TrackSearchQuery query,
        TrackAttributeQuery attributes,
        TrackAttributeCursorPosition cursor,
        int take,
        CancellationToken cancellationToken)
    {
        var position = cursor.Position;
        if (query.Analytics is not { } analytics)
        {
            return new TrackAttributeSearchRepositoryResult(await FetchAttributePageAsync(
                query, attributes, cursor.AttributeIdentityFingerprint, cursor.AttributeCoverage, position.SnapshotUtc,
                position.SnapshotVisibilitySequence, position, take, cancellationToken));
        }

        // The analytic half is continued exactly as an analytic continuation is.
        var identity = cursor.AnalyticsIdentity!;
        var cameraId = await ResolveCameraAsync(query, cancellationToken);
        if (cameraId is null || cameraId != identity.CameraId)
            return TrackAttributeSearchRepositoryResult.Invalid;
        var scope = await ResolveRevisionAsync(cameraId.Value, identity.SceneRevisionId, cancellationToken, pinned: true);
        if (scope is null || !OwnsGeometry(scope.Revision, analytics))
            return TrackAttributeSearchRepositoryResult.Invalid;

        return new TrackAttributeSearchRepositoryResult(await FetchAnalyticAttributePageAsync(
            query, attributes, analytics, identity, cursor.AnalyticsCoverage!, scope, cursor.AttributeIdentityFingerprint,
            cursor.AttributeCoverage, position.SnapshotUtc, position.SnapshotVisibilitySequence, position, take, cancellationToken));
    }

    private async Task<TrackAttributeSearchRepositoryPage> FetchAttributePageAsync(
        TrackSearchQuery query,
        TrackAttributeQuery attributes,
        string? fingerprint,
        TrackAttributeCoverage coverage,
        DateTimeOffset snapshotUtc,
        long snapshotVisibilitySequence,
        TrackCursorPosition? keyset,
        int take,
        CancellationToken cancellationToken)
    {
        if (fingerprint is null)
        {
            // No attribute capability is configured: nothing can match, and coverage says why.
            return new TrackAttributeSearchRepositoryPage(
                [], snapshotUtc, snapshotVisibilitySequence, coverage, new Dictionary<Guid, IReadOnlyList<TrackItemAttributeMatch>>());
        }

        var rows = await BuildQuery(
                query, snapshotVisibilitySequence, keyset,
                candidates => WhereAttributesObserved(candidates, attributes, fingerprint, snapshotVisibilitySequence))
            .Take(take)
            .ToArrayAsync(cancellationToken);
        var explained = await ExplainAttributesAsync(rows, attributes, fingerprint, snapshotVisibilitySequence, cancellationToken);
        return new TrackAttributeSearchRepositoryPage(rows, snapshotUtc, snapshotVisibilitySequence, coverage, explained);
    }

    private async Task<TrackAttributeSearchRepositoryPage> FetchAnalyticAttributePageAsync(
        TrackSearchQuery query,
        TrackAttributeQuery attributes,
        TrackAnalyticsQuery analytics,
        TrackAnalyticsPinnedIdentity identity,
        TrackAnalyticsCoverage analyticsCoverage,
        ResolvedScope scope,
        string? fingerprint,
        TrackAttributeCoverage coverage,
        DateTimeOffset snapshotUtc,
        long snapshotVisibilitySequence,
        TrackCursorPosition? keyset,
        int take,
        CancellationToken cancellationToken)
    {
        if (fingerprint is null || !AnalyticsCanMatch(scope, analyticsCoverage))
        {
            return new TrackAttributeSearchRepositoryPage(
                [], snapshotUtc, snapshotVisibilitySequence, coverage, new Dictionary<Guid, IReadOnlyList<TrackItemAttributeMatch>>(),
                identity, analyticsCoverage, new Dictionary<Guid, TrackItemAnalytics>());
        }

        var (rows, itemAnalytics) = await FetchPageAsync(
            query, analytics, identity, scope, snapshotVisibilitySequence, keyset, take, cancellationToken,
            candidates => WhereAttributesObserved(candidates, attributes, fingerprint, snapshotVisibilitySequence));
        var explained = await ExplainAttributesAsync(rows, attributes, fingerprint, snapshotVisibilitySequence, cancellationToken);
        return new TrackAttributeSearchRepositoryPage(
            rows, snapshotUtc, snapshotVisibilitySequence, coverage, explained, identity, analyticsCoverage, itemAnalytics);
    }

    // --- Predicate ---------------------------------------------------------------------------

    /// <summary>
    /// The fact-bearing attribute analyses of one identity published inside the snapshot. Completed and Superseded both
    /// qualify: the identity is pinned, so admitting a superseded analysis widens nothing (the plate rule).
    /// </summary>
    private IQueryable<VisualAttributeAnalysis> VisibleAttributeAnalyses(string fingerprint, long snapshotVisibilitySequence) =>
        db.VisualAttributeAnalyses.AsNoTracking().Where(analysis =>
            analysis.IdentityFingerprint == fingerprint
            && (analysis.Status == VisualAttributeAnalysisStatus.Completed || analysis.Status == VisualAttributeAnalysisStatus.Superseded)
            && analysis.VisibilitySequence != null
            && analysis.VisibilitySequence <= snapshotVisibilitySequence);

    private IQueryable<TrackCandidate> WhereAttributesObserved(
        IQueryable<TrackCandidate> candidates,
        TrackAttributeQuery attributes,
        string fingerprint,
        long snapshotVisibilitySequence)
    {
        var visible = VisibleAttributeAnalyses(fingerprint, snapshotVisibilitySequence);
        foreach (var predicate in attributes.Predicates)
        {
            var type = predicate.AttributeType;
            var value = predicate.Value;
            candidates = candidates.Where(x => db.VisualAttributes.Any(row =>
                row.TrackId == x.track.Id &&
                row.AttributeType == type &&
                row.Outcome == VisualAttributeOutcome.Observed &&
                row.Value == value &&
                visible.Any(analysis => analysis.Id == row.AnalysisId && analysis.ProcessingRunId == x.track.ProcessingRunId)));
        }

        return candidates;
    }

    /// <summary>Each page row's Observed rows for the predicate types, from the pinned visible analysis.</summary>
    private async Task<IReadOnlyDictionary<Guid, IReadOnlyList<TrackItemAttributeMatch>>> ExplainAttributesAsync(
        IReadOnlyList<TrackSearchRow> rows,
        TrackAttributeQuery attributes,
        string fingerprint,
        long snapshotVisibilitySequence,
        CancellationToken cancellationToken)
    {
        if (rows.Count == 0)
            return new Dictionary<Guid, IReadOnlyList<TrackItemAttributeMatch>>();
        var ids = rows.Select(row => row.Id).ToArray();
        var types = attributes.Predicates.Select(item => item.AttributeType).ToArray();
        var visible = VisibleAttributeAnalyses(fingerprint, snapshotVisibilitySequence);
        var facts = await db.VisualAttributes.AsNoTracking()
            .Where(row => ids.Contains(row.TrackId) &&
                          types.Contains(row.AttributeType) &&
                          row.Outcome == VisualAttributeOutcome.Observed &&
                          visible.Any(analysis => analysis.Id == row.AnalysisId))
            .Select(row => new { row.TrackId, row.AttributeType, row.Value, row.Confidence, row.SupportingObservationId })
            .ToArrayAsync(cancellationToken);
        return facts
            .GroupBy(fact => fact.TrackId)
            .ToDictionary(
                group => group.Key,
                group => (IReadOnlyList<TrackItemAttributeMatch>)group
                    .OrderBy(fact => fact.AttributeType, StringComparer.Ordinal)
                    .Select(fact => new TrackItemAttributeMatch(fact.AttributeType, fact.Value!, fact.Confidence!.Value, fact.SupportingObservationId!.Value))
                    .ToArray());
    }

    // --- Coverage ----------------------------------------------------------------------------

    /// <summary>
    /// Coverage over the base candidate scope (every ordinary filter, the predicates' object class stated): Tracks
    /// Analysed or Unavailable in the pinned visible analysis of their run, the rest NotAnalysed; and per predicate the
    /// analysed Tracks with an Unknown row.
    /// </summary>
    private async Task<TrackAttributeCoverage> ComputeAttributeCoverageAsync(
        TrackSearchQuery query,
        TrackAttributeQuery attributes,
        string? fingerprint,
        string? disclosure,
        long snapshotVisibilitySequence,
        CancellationToken cancellationToken)
    {
        var candidates = BaseCandidates(query, snapshotVisibilitySequence);
        var inScope = await candidates.CountAsync(cancellationToken);
        if (fingerprint is null)
            return TrackAttributeCoverage.NotConfigured(inScope, attributes.Predicates.Count);

        var visible = VisibleAttributeAnalyses(fingerprint, snapshotVisibilitySequence);
        var analysed = await candidates.CountAsync(x => db.VisualAttributeTrackOutcomes.Any(outcome =>
            outcome.TrackId == x.track.Id &&
            outcome.Outcome == VisualAttributeTrackOutcomeKind.Analysed &&
            visible.Any(analysis => analysis.Id == outcome.AnalysisId && analysis.ProcessingRunId == x.track.ProcessingRunId)),
            cancellationToken);
        var unavailable = await candidates.CountAsync(x => db.VisualAttributeTrackOutcomes.Any(outcome =>
            outcome.TrackId == x.track.Id &&
            outcome.Outcome == VisualAttributeTrackOutcomeKind.Unavailable &&
            visible.Any(analysis => analysis.Id == outcome.AnalysisId && analysis.ProcessingRunId == x.track.ProcessingRunId)),
            cancellationToken);
        var unknown = new int[attributes.Predicates.Count];
        for (var index = 0; index < unknown.Length; index++)
        {
            var type = attributes.Predicates[index].AttributeType;
            unknown[index] = await candidates.CountAsync(x => db.VisualAttributes.Any(row =>
                row.TrackId == x.track.Id &&
                row.AttributeType == type &&
                row.Outcome == VisualAttributeOutcome.Unknown &&
                visible.Any(analysis => analysis.Id == row.AnalysisId && analysis.ProcessingRunId == x.track.ProcessingRunId)),
                cancellationToken);
        }

        return new TrackAttributeCoverage(fingerprint, disclosure, inScope, analysed, unavailable, inScope - analysed - unavailable, unknown);
    }

    // --- Detail ------------------------------------------------------------------------------

    public async Task<TrackAttributeFacts?> GetTrackAttributeFactsAsync(Guid trackId, Guid analysisId, CancellationToken cancellationToken)
    {
        var header = await db.VisualAttributeAnalyses.AsNoTracking()
            .Where(analysis => analysis.Id == analysisId)
            .Select(analysis => new TrackAttributeProvenance(
                analysis.Id,
                analysis.IdentityFingerprint,
                analysis.AttributeSchemaId,
                analysis.AttributeSchemaVersion,
                analysis.PipelineId,
                analysis.PipelineVersion,
                analysis.AggregationPolicyId,
                analysis.AggregationPolicyVersion,
                analysis.CapabilitiesCanonical,
                analysis.CompletedAtUtc))
            .SingleOrDefaultAsync(cancellationToken);
        if (header is null)
            return null;

        var outcome = await db.VisualAttributeTrackOutcomes.AsNoTracking()
            .Where(item => item.AnalysisId == analysisId && item.TrackId == trackId)
            .Select(item => new { item.Outcome, item.Reason })
            .SingleOrDefaultAsync(cancellationToken);
        var rows = await db.VisualAttributes.AsNoTracking()
            .Where(item => item.AnalysisId == analysisId && item.TrackId == trackId)
            .Select(item => new TrackAttributeRow(item.AttributeType, item.Outcome, item.Value, item.Confidence, item.SupportingObservationId))
            .ToArrayAsync(cancellationToken);
        return new TrackAttributeFacts(
            outcome?.Outcome,
            outcome?.Reason,
            rows.OrderBy(item => item.AttributeType, StringComparer.Ordinal).ToArray(),
            header);
    }
}
