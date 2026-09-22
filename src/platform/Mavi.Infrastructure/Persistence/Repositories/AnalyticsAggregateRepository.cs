using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.Processing;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The Slice-6 read side: persisted facts for aggregates, and the cheap bounded
/// scope a heatmap must clear before any evidence is opened.
/// </summary>
/// <remarks>
/// <para>
/// Scope, identity and coverage come from <see cref="AnalyticsScopeQuery"/> — the
/// same implementation Investigation uses — so the two surfaces cannot disagree
/// about the same camera and window.
/// </para>
/// <para>
/// Every read follows ADR-011 decision 8: the shared processing-visibility barrier
/// is taken <i>before</i> any snapshot-defining state is read, and the sequence is
/// allocated inside it. Later reads are filtered by that pinned sequence, so nothing
/// published after the snapshot can enter the answer and nothing in the answer
/// describes a different world.
/// </para>
/// <para>
/// Facts are fetched as narrow projections and counted by the pure aggregator rather
/// than in SQL. Four set-based queries replace per-zone, per-line and per-bucket
/// round trips, and the counting rules stay where a fixture can reach them.
/// </para>
/// </remarks>
public sealed class AnalyticsAggregateRepository(MaviDbContext db) : IAnalyticsAggregateRepository
{
    public async Task<AnalyticsAggregateResult> AggregateAsync(
        AnalyticsAggregateQuery query,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        // First, before a byte of scope is read. While this shared lock is held,
        // neither a run completion nor a scene activation can commit, so the camera,
        // the active revision, the sequence and everything resolved from them belong
        // to one world.
        await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(db, cancellationToken);
        var snapshotVisibilitySequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);

        if (!await db.Cameras.AsNoTracking().AnyAsync(camera => camera.Id == query.CameraId, cancellationToken))
        {
            return AnalyticsAggregateResult.NotFound;
        }

        var scope = await AnalyticsScopeQuery.ResolveRevisionAsync(db, query.CameraId, null, cancellationToken);
        if (scope is null)
        {
            return AnalyticsAggregateResult.NotFound;
        }

        var algorithmVersion = SceneAnalyticsAlgorithm.Version;
        var identity = new AnalyticsResolvedIdentity(
            query.CameraId,
            scope.Revision?.Id,
            scope.Revision?.RevisionNumber,
            algorithmVersion,
            snapshotVisibilitySequence);

        var request = AnalyticsScopeRequest.ForCameraWindow(
            query.CameraId, query.FromUtc, query.ToUtc, query.ObjectClass);
        var candidates = AnalyticsScopeQuery.BaseCandidates(db, request, snapshotVisibilitySequence);

        var coverage = await AnalyticsScopeQuery.ComputeCoverageAsync(
            db,
            candidates,
            new TrackAnalyticsPinnedIdentity(query.CameraId, scope.Revision?.Id, algorithmVersion),
            scope,
            snapshotVisibilitySequence,
            cancellationToken);

        // Nothing is evaluable: coverage has already said why, and reading the fact
        // tables could only return nothing.
        if (scope.Revision is null || !scope.AnalyticsEnabled)
        {
            await transaction.CommitAsync(cancellationToken);
            return new AnalyticsAggregateResult(AnalyticsFailure.None, identity, coverage, AnalyticsFactSet.Empty);
        }

        var facts = await ReadFactsAsync(
            query, scope.Revision.Id, algorithmVersion, candidates, snapshotVisibilitySequence, scope, cancellationToken);

        await transaction.CommitAsync(cancellationToken);
        return new AnalyticsAggregateResult(AnalyticsFailure.None, identity, coverage, facts);
    }

    private async Task<AnalyticsFactSet> ReadFactsAsync(
        AnalyticsAggregateQuery query,
        Guid revisionId,
        string algorithmVersion,
        IQueryable<TrackCandidate> candidates,
        long snapshotVisibilitySequence,
        ResolvedScope scope,
        CancellationToken cancellationToken)
    {
        var units = AnalyticsScopeQuery.VisibleUnits(db, revisionId, algorithmVersion, snapshotVisibilitySequence);

        // The covered Tracks: base candidates whose run has a fact-bearing unit of this
        // exact identity, visible in this snapshot.
        var covered = candidates.Join(units, x => x.run.Id, unit => unit.ProcessingRunId, (x, unit) => new
        {
            x.track,
            UnitId = unit.Id,
        });

        // Only geometry the resolved revision enables. A disabled zone produced no
        // facts, and returning it as a row of zeros would read as an observed absence.
        var zones = scope.Revision!.Zones
            .Where(zone => zone.Enabled)
            .OrderBy(zone => zone.Name, StringComparer.Ordinal)
            .Select(zone => new EnabledZone(zone.ZoneId, zone.Name))
            .ToList();
        var lines = scope.Revision.TripLines
            .Where(line => line.Enabled)
            .OrderBy(line => line.Name, StringComparer.Ordinal)
            .Select(line => new EnabledLine(line.LineId, line.Name, line.AToBLabel, line.BToALabel))
            .ToList();

        var enabledZoneIds = zones.Select(zone => zone.ZoneId).ToList();
        var enabledLineIds = lines.Select(line => line.LineId).ToList();

        // A visit contributes when it overlaps the window at all, or when its exit
        // lands exactly on the window's opening instant — which is inside the
        // half-open window and therefore a countable exit event.
        var visits = enabledZoneIds.Count == 0
            ? []
            : await covered
                .Join(
                    db.TrackZoneVisits.AsNoTracking().Where(visit => enabledZoneIds.Contains(visit.ZoneId)),
                    x => new { TrackId = x.track.Id, AnalysisId = x.UnitId },
                    visit => new { visit.TrackId, visit.AnalysisId },
                    (x, visit) => visit)
                .Where(visit => visit.EntryTimestampUtc < query.ToUtc && visit.ExitTimestampUtc >= query.FromUtc)
                .Select(visit => new AggregateZoneVisit(
                    visit.TrackId,
                    visit.ZoneId,
                    visit.EntryTimestampUtc,
                    visit.ExitTimestampUtc,
                    visit.BeganInside,
                    visit.EndedInside))
                .ToListAsync(cancellationToken);

        var crossings = enabledLineIds.Count == 0
            ? []
            : await covered
                .Join(
                    db.TrackLineCrossings.AsNoTracking().Where(crossing => enabledLineIds.Contains(crossing.LineId)),
                    x => new { TrackId = x.track.Id, AnalysisId = x.UnitId },
                    crossing => new { crossing.TrackId, crossing.AnalysisId },
                    (x, crossing) => crossing)
                .Where(crossing => crossing.TimestampUtc >= query.FromUtc && crossing.TimestampUtc < query.ToUtc)
                .Select(crossing => new AggregateLineCrossing(
                    crossing.LineId,
                    crossing.TimestampUtc,
                    crossing.Direction == "AToB"))
                .ToListAsync(cancellationToken);

        // Whole-Track summary semantics: the persisted visit count for the Track, not
        // a count of its visits inside this window.
        var summaries = enabledZoneIds.Count == 0
            ? []
            : await covered
                .Join(
                    db.TrackZoneSummaries.AsNoTracking()
                        .Where(summary => enabledZoneIds.Contains(summary.ZoneId) && summary.VisitCount >= 2),
                    x => new { TrackId = x.track.Id, AnalysisId = x.UnitId },
                    summary => new { summary.TrackId, summary.AnalysisId },
                    (x, summary) => new AggregateZoneSummary(summary.TrackId, summary.ZoneId, summary.VisitCount))
                .ToListAsync(cancellationToken);

        // Class counts are over analysed Tracks: an unavailable outcome produced no
        // facts and must not be counted as observed activity.
        var intervals = await covered
            .Join(
                db.TrackAnalysisOutcomes.AsNoTracking()
                    .Where(outcome => outcome.Outcome == TrackAnalysisOutcomeKind.Analysed),
                x => new { TrackId = x.track.Id, AnalysisId = x.UnitId },
                outcome => new { outcome.TrackId, outcome.AnalysisId },
                (x, outcome) => new AggregateTrackInterval(
                    x.track.Id,
                    x.track.ObjectClass,
                    x.track.StartTimestampUtc,
                    x.track.EndTimestampUtc))
            .ToListAsync(cancellationToken);

        return new AnalyticsFactSet(zones, lines, visits, crossings, summaries, intervals);
    }

    public async Task<AnalyticsHeatmapScope> ResolveHeatmapScopeAsync(
        AnalyticsHeatmapQuery query,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(db, cancellationToken);
        var snapshotVisibilitySequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);

        if (!await db.Cameras.AsNoTracking().AnyAsync(camera => camera.Id == query.CameraId, cancellationToken))
        {
            return AnalyticsHeatmapScope.NotFound;
        }

        // An explicit run must be completed, published and this camera's own. Anything
        // else is indistinguishable from a missing camera: the boundary does not
        // confirm that a hidden run exists.
        if (query.ProcessingRunId is { } runId)
        {
            var owns = await (from run in db.ProcessingRuns.AsNoTracking()
                              where run.Id == runId
                                    && run.Status == ProcessingRunStatus.Completed
                                    && run.VisibilitySequence != null
                                    && run.VisibilitySequence <= snapshotVisibilitySequence
                              join video in db.VideoAssets.AsNoTracking() on run.VideoAssetId equals video.Id
                              where video.CameraId == query.CameraId
                              select run.Id)
                .AnyAsync(cancellationToken);
            if (!owns)
            {
                return AnalyticsHeatmapScope.NotFound;
            }
        }

        var scope = await AnalyticsScopeQuery.ResolveRevisionAsync(db, query.CameraId, null, cancellationToken);
        if (scope is null)
        {
            return AnalyticsHeatmapScope.NotFound;
        }

        var algorithmVersion = SceneAnalyticsAlgorithm.Version;
        var identity = new AnalyticsResolvedIdentity(
            query.CameraId,
            scope.Revision?.Id,
            scope.Revision?.RevisionNumber,
            algorithmVersion,
            snapshotVisibilitySequence);

        var request = AnalyticsScopeRequest.ForCameraWindow(
            query.CameraId, query.FromUtc, query.ToUtc, query.ObjectClass, query.ProcessingRunId);
        var candidates = AnalyticsScopeQuery.BaseCandidates(db, request, snapshotVisibilitySequence);

        var coverage = await AnalyticsScopeQuery.ComputeCoverageAsync(
            db,
            candidates,
            new TrackAnalyticsPinnedIdentity(query.CameraId, scope.Revision?.Id, algorithmVersion),
            scope,
            snapshotVisibilitySequence,
            cancellationToken);

        if (scope.Revision is null || !scope.AnalyticsEnabled)
        {
            await transaction.CommitAsync(cancellationToken);
            return new AnalyticsHeatmapScope(AnalyticsFailure.None, identity, coverage, 0, 0);
        }

        var units = AnalyticsScopeQuery.VisibleUnits(db, scope.Revision.Id, algorithmVersion, snapshotVisibilitySequence);

        // Both bounded dimensions, from the database. Counting is what makes the guard
        // cheap enough to run before the work it bounds (plan §5.5).
        var coveredRunCount = await candidates
            .Join(units, x => x.run.Id, unit => unit.ProcessingRunId, (x, unit) => x.run.Id)
            .Distinct()
            .CountAsync(cancellationToken);
        var candidateTrackCount = await CandidateTracks(candidates, units).CountAsync(cancellationToken);

        await transaction.CommitAsync(cancellationToken);
        return new AnalyticsHeatmapScope(
            AnalyticsFailure.None, identity, coverage, coveredRunCount, candidateTrackCount);
    }

    public async Task<IReadOnlyList<HeatmapCandidateTrack>> ListHeatmapCandidatesAsync(
        AnalyticsHeatmapQuery query,
        AnalyticsResolvedIdentity identity,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);
        ArgumentNullException.ThrowIfNull(identity);

        if (identity.SceneRevisionId is not { } revisionId)
        {
            return [];
        }

        // Evaluated against the identity already pinned, never against what is current
        // now: the snapshot sequence is the one the scope resolved under.
        var request = AnalyticsScopeRequest.ForCameraWindow(
            query.CameraId, query.FromUtc, query.ToUtc, query.ObjectClass, query.ProcessingRunId);
        var candidates = AnalyticsScopeQuery.BaseCandidates(db, request, identity.SnapshotVisibilitySequence);
        var units = AnalyticsScopeQuery.VisibleUnits(
            db, revisionId, identity.AlgorithmVersion, identity.SnapshotVisibilitySequence);

        return await CandidateTracks(candidates, units).ToListAsync(cancellationToken);
    }

    /// <summary>
    /// The Analysed Track outcomes whose sealed trajectories are heatmap candidates,
    /// with the storage key and recording start each sample's absolute instant needs.
    /// </summary>
    /// <remarks>
    /// One definition, used by both the count that guards the work and the listing
    /// that does it, so the bound can never be measured against a different set from
    /// the one that is read. A Track with no trajectory artefact is not a candidate:
    /// there is nothing to open.
    /// </remarks>
    private IQueryable<HeatmapCandidateTrack> CandidateTracks(
        IQueryable<TrackCandidate> candidates,
        IQueryable<SceneAnalysis> units) =>
        candidates
            .Join(units, x => x.run.Id, unit => unit.ProcessingRunId, (x, unit) => new { x.track, x.video, unit })
            .Join(
                db.TrackAnalysisOutcomes.AsNoTracking()
                    .Where(outcome => outcome.Outcome == TrackAnalysisOutcomeKind.Analysed),
                x => new { TrackId = x.track.Id, AnalysisId = x.unit.Id },
                outcome => new { outcome.TrackId, outcome.AnalysisId },
                (x, outcome) => x)
            .Where(x => x.track.TrajectoryArtifactId != null)
            .Join(
                db.Artifacts.AsNoTracking(),
                x => x.track.TrajectoryArtifactId,
                artifact => (Guid?)artifact.Id,
                (x, artifact) => new { x.track, x.video, artifact })
            // Ordered here rather than at the call site, so the order is part of the one
            // definition: two executions of the same scope read the same artefacts in the
            // same sequence and produce the same matrix.
            .OrderBy(x => x.track.Id)
            .Select(x => new HeatmapCandidateTrack(
                x.track.Id,
                x.video.RecordingStartUtc,
                x.artifact.StorageKey));
}
