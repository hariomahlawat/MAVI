using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.Processing;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The analytic half of Track search (plan §H, §S; ADR-011 decisions 5 and 6).
/// </summary>
/// <remarks>
/// <para>
/// The first page is one linearisation point. The read transaction takes the shared
/// processing-visibility barrier <i>first</i>, before any scope is read; only then is
/// the query resolved to one camera, the explicit or active scene revision read, the
/// engine version captured, the snapshot sequence allocated, coverage computed over the
/// base candidate scope and the page fetched. Both publication events — run completion
/// and scene activation — take the exclusive counterpart of that barrier and hold it
/// through commit, so neither can commit while the page is being assembled. Nothing
/// about the search can change between those steps: a scene activation committing
/// between two unrelated reads cannot make the first page mean one thing and its cursor
/// another.
/// </para>
/// <para>
/// The identity this establishes — camera, scene revision, algorithm version and
/// snapshot sequence — is the search result set's identity. It is resolved here and
/// nowhere else: the request's filters are a request, and what the first page returns
/// in its coverage block is the answer. Every later read that belongs to these results
/// —a continuation, the geometry their labels are drawn from, the detail of one of
/// them — is made against that identity rather than against whatever is current when
/// the read happens.
/// </para>
/// <para>
/// A continuation never re-resolves "current". It evaluates against the pinned revision,
/// version and snapshot sequence exactly as pinned, and returns the pinned coverage
/// byte-for-byte. The only thing it checks is that the pinned revision still belongs to
/// the camera the supplied scope resolves to — revisions are immutable and never
/// deleted, so that is the one way a cursor can be wrong about its scope.
/// </para>
/// <para>
/// The fact join accepts both fact-bearing states. The join is already pinned to one
/// <c>revision_id</c> and one <c>algorithm_version</c>, which <i>is</i> the unit's
/// identity, so admitting <c>Superseded</c> widens nothing and stops a continuation
/// losing the very facts its identity produced when a re-analysis supersedes them
/// between pages.
/// </para>
/// </remarks>
public sealed partial class TrackSearchRepository
{
    public async Task<TrackAnalyticsSearchRepositoryResult> SearchAnalyticsAsync(
        TrackSearchQuery query,
        TrackAnalyticsCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);
        if (query.Analytics is not { } analytics)
            throw new ArgumentException("An analytic search needs an analytic query.", nameof(query));

        if (cursor is not null)
        {
            return await ContinueAsync(query, analytics, cursor, take, cancellationToken);
        }

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        // The barrier is the first thing this transaction does, before a single byte of
        // scope is read. Both publication events — a run completion and a scene
        // activation — take the exclusive counterpart and hold it through commit, so
        // while this shared lock is held neither can commit. Everything read after this
        // line therefore describes one world: the camera, the active revision, the
        // resolved revision's geometry, the snapshot sequence, coverage and the page.
        //
        // Reading scope before the lock would not be a smaller window, it would be a
        // different world: an activation committing in the gap leaves the page pinned to
        // revision 1 while its snapshot already contains revision-2 work, and coverage
        // then calls revision-1 gaps Pending although reconciliation will only ever
        // create revision-2 units.
        await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(db, cancellationToken);
        var snapshotVisibilitySequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);
        var snapshotUtc = timeProvider.GetUtcNow().ToUniversalTime();

        var cameraId = await ResolveCameraAsync(query, cancellationToken);
        if (cameraId is null)
            return TrackAnalyticsSearchRepositoryResult.Invalid;

        var scope = await ResolveRevisionAsync(cameraId.Value, analytics.SceneRevisionId, cancellationToken);
        if (scope is null)
            return TrackAnalyticsSearchRepositoryResult.Invalid;

        var identity = new TrackAnalyticsPinnedIdentity(
            cameraId.Value,
            scope.Revision?.Id,
            analytics.AnalyticsAlgorithmVersion ?? SceneAnalyticsAlgorithm.Version);

        if (!OwnsGeometry(scope.Revision, analytics))
            return TrackAnalyticsSearchRepositoryResult.Invalid;

        var coverage = await ComputeCoverageAsync(query, identity, scope, snapshotVisibilitySequence, cancellationToken);
        var (rows, itemAnalytics) = await FetchPageAsync(
            query, analytics, identity, scope, snapshotVisibilitySequence, cursor: null, take, cancellationToken);

        await transaction.CommitAsync(cancellationToken);
        return new TrackAnalyticsSearchRepositoryResult(new TrackAnalyticsSearchRepositoryPage(
            rows, snapshotUtc, snapshotVisibilitySequence, identity, coverage, itemAnalytics));
    }

    private async Task<TrackAnalyticsSearchRepositoryResult> ContinueAsync(
        TrackSearchQuery query,
        TrackAnalyticsQuery analytics,
        TrackAnalyticsCursorPosition cursor,
        int take,
        CancellationToken cancellationToken)
    {
        var cameraId = await ResolveCameraAsync(query, cancellationToken);
        if (cameraId is null || cameraId != cursor.Identity.CameraId)
            return TrackAnalyticsSearchRepositoryResult.Invalid;

        // The pinned revision, read as pinned — never the camera's current one.
        var scope = await ResolveRevisionAsync(cameraId.Value, cursor.Identity.SceneRevisionId, cancellationToken, pinned: true);
        if (scope is null || !OwnsGeometry(scope.Revision, analytics))
            return TrackAnalyticsSearchRepositoryResult.Invalid;

        var (rows, itemAnalytics) = await FetchPageAsync(
            query, analytics, cursor.Identity, scope, cursor.Position.SnapshotVisibilitySequence,
            cursor.Position, take, cancellationToken);

        return new TrackAnalyticsSearchRepositoryResult(new TrackAnalyticsSearchRepositoryPage(
            rows,
            cursor.Position.SnapshotUtc,
            cursor.Position.SnapshotVisibilitySequence,
            cursor.Identity,
            // Snapshot-stable by construction: the block the first page computed, carried
            // inside the authenticated cursor, not a recomputation over mutable state.
            cursor.Coverage,
            itemAnalytics));
    }

    // --- Scope and identity -------------------------------------------------

    /// <summary>
    /// The one camera every supplied scope identifier resolves to, or null when any is
    /// missing, unknown or names a different camera.
    /// </summary>
    /// <remarks>
    /// A run resolves only when it is completed and published, the boundary the analytics
    /// endpoints already draw: an analytic query must not confirm that a hidden run exists.
    /// </remarks>
    private async Task<Guid?> ResolveCameraAsync(TrackSearchQuery query, CancellationToken cancellationToken)
    {
        var resolved = new List<Guid>(3);

        if (query.CameraId is { } cameraId)
        {
            if (!await db.Cameras.AsNoTracking().AnyAsync(camera => camera.Id == cameraId, cancellationToken))
                return null;
            resolved.Add(cameraId);
        }

        if (query.VideoAssetId is { } videoId)
        {
            var owner = await db.VideoAssets.AsNoTracking()
                .Where(video => video.Id == videoId)
                .Select(video => (Guid?)video.CameraId)
                .SingleOrDefaultAsync(cancellationToken);
            if (owner is null)
                return null;
            resolved.Add(owner.Value);
        }

        if (query.ProcessingRunId is { } runId)
        {
            var owner = await (from run in db.ProcessingRuns.AsNoTracking()
                               where run.Id == runId
                                     && run.Status == ProcessingRunStatus.Completed
                                     && run.VisibilitySequence != null
                               join video in db.VideoAssets.AsNoTracking() on run.VideoAssetId equals video.Id
                               select (Guid?)video.CameraId)
                .SingleOrDefaultAsync(cancellationToken);
            if (owner is null)
                return null;
            resolved.Add(owner.Value);
        }

        if (resolved.Count == 0 || resolved.Distinct().Count() != 1)
            return null;
        return resolved[0];
    }

    /// <summary>
    /// Resolves the explicit revision, else the camera's active one, from the one shared
    /// implementation in <see cref="AnalyticsScopeQuery"/>.
    /// </summary>
    private Task<ResolvedScope?> ResolveRevisionAsync(
        Guid cameraId,
        Guid? revisionId,
        CancellationToken cancellationToken,
        bool pinned = false) =>
        AnalyticsScopeQuery.ResolveRevisionAsync(db, cameraId, revisionId, cancellationToken, pinned);

    /// <summary>
    /// A zone or line predicate must name geometry of the resolved revision. Against no
    /// revision there is nothing to own; a disabled member still belongs to its revision
    /// and simply matches nothing.
    /// </summary>
    private static bool OwnsGeometry(SceneConfigurationRevision? revision, TrackAnalyticsQuery analytics)
    {
        if (analytics.ZoneId is { } zoneId &&
            (revision is null || !revision.Zones.Any(zone => zone.ZoneId == zoneId)))
            return false;

        if (analytics.LineId is { } lineId &&
            (revision is null || !revision.TripLines.Any(line => line.LineId == lineId)))
            return false;

        return true;
    }

    // --- Coverage -----------------------------------------------------------

    /// <summary>
    /// Coverage over the distinct runs of the base candidate set, from the one shared
    /// implementation. Slice 6 classifies the same denominator the same way.
    /// </summary>
    private Task<TrackAnalyticsCoverage> ComputeCoverageAsync(
        TrackSearchQuery query,
        TrackAnalyticsPinnedIdentity identity,
        ResolvedScope scope,
        long snapshotVisibilitySequence,
        CancellationToken cancellationToken) =>
        AnalyticsScopeQuery.ComputeCoverageAsync(
            db,
            BaseCandidates(query, snapshotVisibilitySequence),
            identity,
            scope,
            snapshotVisibilitySequence,
            cancellationToken);

    // --- Page ---------------------------------------------------------------

    /// <summary>A base candidate joined to the fact-bearing unit that evaluated its run.</summary>
    private sealed class EvaluatedCandidate
    {
        public required TrackCandidate Candidate { get; init; }
        public required SceneAnalysis Unit { get; init; }
    }

    private sealed record AnalyticRow(TrackSearchRow Row, Guid UnitId);

    private async Task<(IReadOnlyList<TrackSearchRow> Rows, IReadOnlyDictionary<Guid, TrackItemAnalytics> ItemAnalytics)> FetchPageAsync(
        TrackSearchQuery query,
        TrackAnalyticsQuery analytics,
        TrackAnalyticsPinnedIdentity identity,
        ResolvedScope scope,
        long snapshotVisibilitySequence,
        TrackCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken)
    {
        var empty = new Dictionary<Guid, TrackItemAnalytics>();
        if (scope.Revision is null || !scope.AnalyticsEnabled)
        {
            // Nothing is evaluable; coverage has already said why. Reading the fact tables
            // here would only cost a query that can return nothing.
            return ([], empty);
        }

        var revisionId = scope.Revision.Id;
        var algorithmVersion = identity.AlgorithmVersion;

        var evaluated = BaseCandidates(query, snapshotVisibilitySequence)
            .Join(
                db.SceneAnalyses.AsNoTracking().Where(unit =>
                    unit.RevisionId == revisionId
                    && unit.AlgorithmVersion == algorithmVersion
                    && (unit.Status == SceneAnalysisStatus.Completed || unit.Status == SceneAnalysisStatus.Superseded)
                    && unit.VisibilitySequence != null
                    && unit.VisibilitySequence <= snapshotVisibilitySequence),
                x => x.run.Id,
                unit => unit.ProcessingRunId,
                (x, unit) => new EvaluatedCandidate { Candidate = x, Unit = unit });

        evaluated = ApplyPredicates(evaluated, analytics);

        if (cursor is not null)
        {
            var timestamp = cursor.StartTimestampUtc;
            var trackId = cursor.TrackId;
            evaluated = evaluated.Where(x =>
                x.Candidate.track.StartTimestampUtc < timestamp ||
                (x.Candidate.track.StartTimestampUtc == timestamp &&
                 x.Candidate.track.Id.CompareTo(trackId) < 0));
        }

        var page = await evaluated
            .OrderByDescending(x => x.Candidate.track.StartTimestampUtc)
            .ThenByDescending(x => x.Candidate.track.Id)
            .Select(x => new AnalyticRow(
                new TrackSearchRow(
                    x.Candidate.track.Id,
                    x.Candidate.track.ProcessingRunId,
                    x.Candidate.track.VideoAssetId,
                    x.Candidate.camera.Id,
                    x.Candidate.camera.Code,
                    x.Candidate.camera.Name,
                    x.Candidate.track.ObjectClass,
                    x.Candidate.track.StartTimestampUtc,
                    x.Candidate.track.EndTimestampUtc,
                    x.Candidate.track.StartOffsetMs,
                    x.Candidate.track.EndOffsetMs,
                    x.Candidate.track.DurationMs,
                    x.Candidate.track.DetectionCount,
                    x.Candidate.track.MeanConfidence,
                    x.Candidate.track.MaxConfidence,
                    x.Candidate.track.ReviewStatus,
                    x.Candidate.observation == null ? null : x.Candidate.observation.ThumbnailArtifactId),
                x.Unit.Id))
            .Take(take)
            .ToArrayAsync(cancellationToken);

        var rows = page.Select(x => x.Row).ToArray();
        var itemAnalytics = rows.Length == 0
            ? empty
            : await ExplainPageAsync(page, analytics, identity, revisionId, cancellationToken);
        return (rows, itemAnalytics);
    }

    /// <summary>Every supplied analytic predicate, combined with AND (plan §S).</summary>
    private IQueryable<EvaluatedCandidate> ApplyPredicates(IQueryable<EvaluatedCandidate> evaluated, TrackAnalyticsQuery analytics)
    {
        if (analytics.ZoneId is { } zoneId)
        {
            var minDwellMs = analytics.MinDwellMs;
            var loitering = analytics.Loitering;
            evaluated = evaluated.Where(x => db.TrackZoneSummaries.Any(summary =>
                summary.AnalysisId == x.Unit.Id
                && summary.TrackId == x.Candidate.track.Id
                && summary.ZoneId == zoneId
                && (minDwellMs == null || summary.TotalDwellMs >= minDwellMs)
                && (!loitering || summary.Loitering)));

            switch (analytics.EffectiveZoneRelation)
            {
                case TrackZoneRelation.Dwelled:
                    evaluated = evaluated.Where(x => db.TrackZoneSummaries.Any(summary =>
                        summary.AnalysisId == x.Unit.Id
                        && summary.TrackId == x.Candidate.track.Id
                        && summary.ZoneId == zoneId
                        && summary.TotalDwellMs > 0));
                    break;
                case TrackZoneRelation.Entered:
                    evaluated = evaluated.Where(x => db.TrackZoneVisits.Any(visit =>
                        visit.AnalysisId == x.Unit.Id
                        && visit.TrackId == x.Candidate.track.Id
                        && visit.ZoneId == zoneId
                        && !visit.BeganInside));
                    break;
                case TrackZoneRelation.Exited:
                    evaluated = evaluated.Where(x => db.TrackZoneVisits.Any(visit =>
                        visit.AnalysisId == x.Unit.Id
                        && visit.TrackId == x.Candidate.track.Id
                        && visit.ZoneId == zoneId
                        && !visit.EndedInside));
                    break;
            }
        }
        else if (analytics.Loitering)
        {
            evaluated = evaluated.Where(x => db.TrackZoneSummaries.Any(summary =>
                summary.AnalysisId == x.Unit.Id
                && summary.TrackId == x.Candidate.track.Id
                && summary.Loitering));
        }

        if (analytics.LineId is { } lineId)
        {
            var direction = analytics.CrossingDirection is { } crossing
                ? TrackAnalyticsQueryRules.ToPersisted(crossing)
                : null;
            evaluated = evaluated.Where(x => db.TrackLineCrossings.Any(crossingRow =>
                crossingRow.AnalysisId == x.Unit.Id
                && crossingRow.TrackId == x.Candidate.track.Id
                && crossingRow.LineId == lineId
                && (direction == null || crossingRow.Direction == direction)));
        }

        if (analytics.MotionDirection is not null || analytics.MinStationaryMs is not null)
        {
            var heading = analytics.MotionDirection;
            var minStationaryMs = analytics.MinStationaryMs;
            evaluated = evaluated.Where(x => db.TrackMotionSummaries.Any(motion =>
                motion.AnalysisId == x.Unit.Id
                && motion.TrackId == x.Candidate.track.Id
                && (heading == null || motion.Heading == heading)
                && (minStationaryMs == null || motion.LongestStationaryMs >= minStationaryMs)));
        }

        return evaluated;
    }

    /// <summary>
    /// The bounded explanation for the rows on this page and no others: which zones and
    /// lines matched, and the one motion summary when motion was asked about. Three
    /// queries at most, each keyed on the page's (unit, Track) pairs.
    /// </summary>
    private async Task<IReadOnlyDictionary<Guid, TrackItemAnalytics>> ExplainPageAsync(
        AnalyticRow[] page,
        TrackAnalyticsQuery analytics,
        TrackAnalyticsPinnedIdentity identity,
        Guid revisionId,
        CancellationToken cancellationToken)
    {
        var unitIds = page.Select(x => x.UnitId).Distinct().ToArray();
        var trackIds = page.Select(x => x.Row.Id).ToArray();

        var zones = new Dictionary<Guid, List<TrackItemZoneAnalytics>>();
        if (analytics.ZoneId is not null || analytics.Loitering)
        {
            var zoneId = analytics.ZoneId;
            var loiteringOnly = analytics.ZoneId is null;
            var summaries = await db.TrackZoneSummaries.AsNoTracking()
                .Where(summary => unitIds.Contains(summary.AnalysisId) && trackIds.Contains(summary.TrackId)
                    && (zoneId == null || summary.ZoneId == zoneId)
                    && (!loiteringOnly || summary.Loitering))
                .OrderBy(summary => summary.ZoneId)
                .Select(summary => new { summary.TrackId, summary.ZoneId, summary.VisitCount, summary.TotalDwellMs, summary.Loitering })
                .ToListAsync(cancellationToken);
            foreach (var summary in summaries)
            {
                if (!zones.TryGetValue(summary.TrackId, out var list))
                    zones[summary.TrackId] = list = [];
                list.Add(new TrackItemZoneAnalytics(summary.ZoneId, summary.VisitCount, summary.TotalDwellMs, summary.Loitering));
            }
        }

        var lines = new Dictionary<Guid, List<TrackItemLineAnalytics>>();
        if (analytics.LineId is { } lineId)
        {
            var direction = analytics.CrossingDirection is { } requested
                ? TrackAnalyticsQueryRules.ToPersisted(requested)
                : null;
            var crossings = await db.TrackLineCrossings.AsNoTracking()
                .Where(row => unitIds.Contains(row.AnalysisId) && trackIds.Contains(row.TrackId)
                    && row.LineId == lineId
                    && (direction == null || row.Direction == direction))
                .GroupBy(row => row.TrackId)
                .Select(group => new
                {
                    TrackId = group.Key,
                    Count = group.Count(),
                    First = group.Min(row => row.TimestampUtc),
                })
                .ToListAsync(cancellationToken);
            foreach (var crossing in crossings)
            {
                lines[crossing.TrackId] =
                    [new TrackItemLineAnalytics(lineId, crossing.Count, direction, crossing.First)];
            }
        }

        var motions = new Dictionary<Guid, TrackItemMotionAnalytics>();
        if (analytics.MotionDirection is not null || analytics.MinStationaryMs is not null)
        {
            var summaries = await db.TrackMotionSummaries.AsNoTracking()
                .Where(motion => unitIds.Contains(motion.AnalysisId) && trackIds.Contains(motion.TrackId))
                .Select(motion => new { motion.TrackId, motion.Heading, motion.LongestStationaryMs })
                .ToListAsync(cancellationToken);
            foreach (var motion in summaries)
                motions[motion.TrackId] = new TrackItemMotionAnalytics(motion.Heading, motion.LongestStationaryMs);
        }

        var result = new Dictionary<Guid, TrackItemAnalytics>(page.Length);
        foreach (var row in page)
        {
            result[row.Row.Id] = new TrackItemAnalytics(
                revisionId,
                identity.AlgorithmVersion,
                zones.TryGetValue(row.Row.Id, out var zoneList) ? zoneList : [],
                lines.TryGetValue(row.Row.Id, out var lineList) ? lineList : [],
                motions.TryGetValue(row.Row.Id, out var motion) ? motion : null);
        }

        return result;
    }

    // --- Detail -------------------------------------------------------------

    public async Task<TrackDetailAnalyticsResult?> GetDetailAnalyticsAsync(
        Guid trackId,
        TrackAnalyticsDetailRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);

        var owner = await (from track in db.Tracks.AsNoTracking()
                           join run in db.ProcessingRuns.AsNoTracking() on track.ProcessingRunId equals run.Id
                           join video in db.VideoAssets.AsNoTracking() on track.VideoAssetId equals video.Id
                           where track.Id == trackId
                                 && run.Status == ProcessingRunStatus.Completed
                                 && run.CompletedAtUtc != null
                           select new { RunId = run.Id, video.CameraId })
            .SingleOrDefaultAsync(cancellationToken);
        if (owner is null)
            return null;

        var scope = await ResolveRevisionAsync(owner.CameraId, request.SceneRevisionId, cancellationToken);
        if (scope is null)
            return TrackDetailAnalyticsResult.Invalid;

        var algorithmVersion = request.AlgorithmVersion ?? SceneAnalyticsAlgorithm.Version;

        var units = await (from unit in db.SceneAnalyses.AsNoTracking()
                           where unit.ProcessingRunId == owner.RunId
                           join revision in db.SceneConfigurationRevisions.AsNoTracking()
                               on unit.RevisionId equals revision.Id
                           orderby revision.RevisionNumber, unit.AlgorithmVersion
                           select new { Unit = unit, revision.RevisionNumber })
            .ToListAsync(cancellationToken);

        // Compact summaries of every other identity that produced facts for this Track,
        // so the operator can see that a different revision or engine also looked at it.
        var factBearingUnitIds = units
            .Where(x => x.Unit.IsFactBearing)
            .Select(x => x.Unit.Id)
            .ToArray();
        var outcomes = factBearingUnitIds.Length == 0
            ? []
            : await db.TrackAnalysisOutcomes.AsNoTracking()
                .Where(outcome => outcome.TrackId == trackId && factBearingUnitIds.Contains(outcome.AnalysisId))
                .ToListAsync(cancellationToken);

        var others = units
            .Where(x => x.Unit.IsFactBearing
                && !(x.Unit.RevisionId == scope.Revision?.Id
                     && string.Equals(x.Unit.AlgorithmVersion, algorithmVersion, StringComparison.Ordinal)))
            .Select(x => new TrackAnalyticsIdentitySummary(
                x.Unit.RevisionId,
                x.RevisionNumber,
                x.Unit.AlgorithmVersion,
                x.Unit.Status,
                outcomes.FirstOrDefault(outcome => outcome.AnalysisId == x.Unit.Id)?.Outcome
                    ?? TrackAnalysisOutcomeKind.Unavailable))
            .ToArray();

        if (scope.Revision is null)
        {
            return new TrackDetailAnalyticsResult(Bare(null, null, algorithmVersion, "NotConfigured", others));
        }

        var revisionNumber = scope.Revision.RevisionNumber;
        if (!scope.AnalyticsEnabled)
        {
            return new TrackDetailAnalyticsResult(Bare(scope.Revision.Id, revisionNumber, algorithmVersion, "Disabled", others));
        }

        var exact = units.FirstOrDefault(x =>
            x.Unit.RevisionId == scope.Revision.Id
            && string.Equals(x.Unit.AlgorithmVersion, algorithmVersion, StringComparison.Ordinal))?.Unit;

        switch (exact?.Status)
        {
            case SceneAnalysisStatus.Queued:
            case SceneAnalysisStatus.Running:
                return new TrackDetailAnalyticsResult(Bare(scope.Revision.Id, revisionNumber, algorithmVersion, "Pending", others));
            case SceneAnalysisStatus.Failed:
                return new TrackDetailAnalyticsResult(Bare(scope.Revision.Id, revisionNumber, algorithmVersion, "Failed", others));
            case SceneAnalysisStatus.Completed:
            case SceneAnalysisStatus.Superseded:
                break;
            default:
                {
                    var identityIsCurrent = scope.ActiveRevisionId == scope.Revision.Id
                        && string.Equals(algorithmVersion, SceneAnalyticsAlgorithm.Version, StringComparison.Ordinal);
                    var status = !identityIsCurrent || units.Any(x => x.Unit.IsFactBearing) ? "Stale" : "Pending";
                    return new TrackDetailAnalyticsResult(Bare(scope.Revision.Id, revisionNumber, algorithmVersion, status, others));
                }
        }

        var outcome = outcomes.FirstOrDefault(row => row.AnalysisId == exact.Id);
        if (outcome is null || outcome.Outcome == TrackAnalysisOutcomeKind.Unavailable)
        {
            // Every Track of a completed unit has an outcome row by invariant; a missing
            // one is reported as unavailable with no reason rather than invented as facts.
            return new TrackDetailAnalyticsResult(new TrackDetailAnalytics(
                scope.Revision.Id, revisionNumber, algorithmVersion, "Unavailable", outcome, [], [], [], null, others));
        }

        var unitId = exact.Id;
        var zoneSummaries = await db.TrackZoneSummaries.AsNoTracking()
            .Where(x => x.AnalysisId == unitId && x.TrackId == trackId)
            .OrderBy(x => x.ZoneId)
            .ToListAsync(cancellationToken);
        var zoneVisits = await db.TrackZoneVisits.AsNoTracking()
            .Where(x => x.AnalysisId == unitId && x.TrackId == trackId)
            .OrderBy(x => x.ZoneId).ThenBy(x => x.VisitIndex)
            .ToListAsync(cancellationToken);
        var lineCrossings = await db.TrackLineCrossings.AsNoTracking()
            .Where(x => x.AnalysisId == unitId && x.TrackId == trackId)
            .OrderBy(x => x.LineId).ThenBy(x => x.CrossingIndex)
            .ToListAsync(cancellationToken);
        var motion = await db.TrackMotionSummaries.AsNoTracking()
            .SingleOrDefaultAsync(x => x.AnalysisId == unitId && x.TrackId == trackId, cancellationToken);

        return new TrackDetailAnalyticsResult(new TrackDetailAnalytics(
            scope.Revision.Id, revisionNumber, algorithmVersion, "Analysed",
            outcome, zoneSummaries, zoneVisits, lineCrossings, motion, others));
    }

    private static TrackDetailAnalytics Bare(
        Guid? revisionId,
        int? revisionNumber,
        string algorithmVersion,
        string status,
        IReadOnlyList<TrackAnalyticsIdentitySummary> others) =>
        new(revisionId, revisionNumber, algorithmVersion, status, null, [], [], [], null, others);
}
