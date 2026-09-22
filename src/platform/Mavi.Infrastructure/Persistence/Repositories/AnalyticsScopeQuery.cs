using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Processing;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The one description of an analytical base scope, and the one implementation of
/// the base candidate chain, revision resolution and coverage classification over
/// it.
/// </summary>
/// <remarks>
/// <para>
/// Extracted from <see cref="TrackSearchRepository"/> when Slice 6 needed the same
/// answers for aggregates and heatmaps. It is deliberately a narrow projection
/// rather than a second resolver: coverage arithmetic and fact-bearing semantics
/// (ADR-011 decisions 5, 6 and 8) exist once, so an aggregate cannot drift from
/// what Investigation reports for the same camera and window.
/// </para>
/// <para>
/// This extraction is behaviour-preserving. The Slice-4 search and coverage test
/// suites pass unchanged against it; the chain below is the same chain, moved.
/// </para>
/// </remarks>
public sealed record AnalyticsScopeRequest(
    Guid? CameraId,
    Guid? VideoAssetId,
    Guid? ProcessingRunId,
    ObjectClass? ObjectClass,
    DateTimeOffset? FromUtc,
    DateTimeOffset? ToUtc,
    long? MinimumDurationMs,
    double? MinimumConfidence)
{
    /// <summary>The scope a Track-search query describes.</summary>
    public static AnalyticsScopeRequest From(TrackSearchQuery query)
    {
        ArgumentNullException.ThrowIfNull(query);
        return new AnalyticsScopeRequest(
            query.CameraId,
            query.VideoAssetId,
            query.ProcessingRunId,
            query.ObjectClass,
            query.FromUtc,
            query.ToUtc,
            query.MinimumDurationMs,
            query.MinimumConfidence);
    }

    /// <summary>The scope a Slice-6 camera/window request describes.</summary>
    /// <remarks>
    /// Aggregates and heatmaps filter by camera, window and class only. The
    /// remaining dimensions stay null so the base chain is literally the ordinary
    /// candidate set, which is what makes the coverage denominator comparable with
    /// Investigation's.
    /// </remarks>
    public static AnalyticsScopeRequest ForCameraWindow(
        Guid cameraId,
        DateTimeOffset fromUtc,
        DateTimeOffset toUtc,
        ObjectClass? objectClass,
        Guid? processingRunId = null) =>
        new(cameraId, null, processingRunId, objectClass, fromUtc, toUtc, null, null);
}

/// <summary>
/// One candidate row of the base chain, shared by every path that needs it.
/// Member-initialised rather than constructed: EF Core inlines an object initialiser
/// into later correlated subqueries the way it does an anonymous type, and does not
/// do the same for a constructor call.
/// </summary>
#pragma warning disable IDE1006 // Lower-case members keep the query text identical to the anonymous type it replaces.
public sealed class TrackCandidate
{
    public required Track track { get; init; }
    public required ProcessingRun run { get; init; }
    public required Domain.Media.VideoAsset video { get; init; }
    public required Domain.Cameras.Camera camera { get; init; }
    public Observation? observation { get; init; }
}
#pragma warning restore IDE1006

/// <summary>What an analytical read evaluates against: the revision, and what is active.</summary>
/// <param name="Revision">The resolved revision with its geometry; null only for a never-configured camera.</param>
/// <param name="ActiveRevisionId">The camera's active revision now, for classifying missing units.</param>
public sealed record ResolvedScope(SceneConfigurationRevision? Revision, Guid? ActiveRevisionId)
{
    /// <summary>Whether the resolved revision itself enables analytics (plan §H, disabledRuns).</summary>
    public bool AnalyticsEnabled => Revision?.AnalyticsEnabled ?? false;
}

public static class AnalyticsScopeQuery
{
    /// <summary>
    /// The non-analytic base candidate set: every existing Track filter and the latest-run
    /// scope, before any analytic predicate, keyset or ordering. Ordinary search orders and
    /// pages it directly; analytic search and the Slice-6 aggregates take their coverage
    /// denominator from it (plan §H) and then narrow it.
    /// </summary>
    public static IQueryable<TrackCandidate> BaseCandidates(
        MaviDbContext db,
        AnalyticsScopeRequest scope,
        long snapshotVisibilitySequence)
    {
        ArgumentNullException.ThrowIfNull(db);
        ArgumentNullException.ThrowIfNull(scope);

        var tracks =
            from track in db.Tracks.AsNoTracking()
            join run in db.ProcessingRuns.AsNoTracking() on track.ProcessingRunId equals run.Id
            join video in db.VideoAssets.AsNoTracking() on track.VideoAssetId equals video.Id
            join camera in db.Cameras.AsNoTracking() on video.CameraId equals camera.Id
            join observation in db.Observations.AsNoTracking()
                on track.RepresentativeObservationId equals observation.Id into observations
            from observation in observations.DefaultIfEmpty()
            where run.Status == ProcessingRunStatus.Completed &&
                  run.CompletedAtUtc != null &&
                  run.VisibilitySequence != null &&
                  run.VisibilitySequence <= snapshotVisibilitySequence
            select new TrackCandidate { track = track, run = run, video = video, camera = camera, observation = observation };

        if (scope.ProcessingRunId is { } runId)
        {
            tracks = tracks.Where(x => x.run.Id == runId);
        }
        else
        {
            tracks = tracks.Where(x =>
                !db.ProcessingRuns.AsNoTracking().Any(other =>
                    other.VideoAssetId == x.video.Id &&
                    other.Status == ProcessingRunStatus.Completed &&
                    other.CompletedAtUtc != null &&
                    other.VisibilitySequence != null &&
                    other.VisibilitySequence <= snapshotVisibilitySequence &&
                    other.VisibilitySequence > x.run.VisibilitySequence));
        }

        if (scope.CameraId is { } cameraId)
            tracks = tracks.Where(x => x.camera.Id == cameraId);
        if (scope.VideoAssetId is { } videoId)
            tracks = tracks.Where(x => x.video.Id == videoId);
        if (scope.ObjectClass is { } objectClass)
            tracks = tracks.Where(x => x.track.ObjectClass == objectClass);
        if (scope.FromUtc is { } fromUtc)
            tracks = tracks.Where(x => x.track.EndTimestampUtc >= fromUtc);
        if (scope.ToUtc is { } toUtc)
            tracks = tracks.Where(x => x.track.StartTimestampUtc < toUtc);
        if (scope.MinimumDurationMs is { } minimumDurationMs)
            tracks = tracks.Where(x => x.track.DurationMs >= minimumDurationMs);
        if (scope.MinimumConfidence is { } minimumConfidence)
            tracks = tracks.Where(x => x.track.MeanConfidence >= minimumConfidence);

        return tracks;
    }

    /// <summary>
    /// Resolves the explicit revision, else the camera's active one. Null when an explicit
    /// revision does not belong to this camera.
    /// </summary>
    /// <param name="pinned">
    /// True on continuation: the revision id is the cursor's, and a null id means the
    /// first page found a never-configured camera, which is then honoured rather than
    /// re-resolved.
    /// </param>
    public static async Task<ResolvedScope?> ResolveRevisionAsync(
        MaviDbContext db,
        Guid cameraId,
        Guid? revisionId,
        CancellationToken cancellationToken,
        bool pinned = false)
    {
        ArgumentNullException.ThrowIfNull(db);

        var activeRevisionId = await db.SceneConfigurations.AsNoTracking()
            .Where(configuration => configuration.CameraId == cameraId)
            .Select(configuration => configuration.ActiveRevisionId)
            .SingleOrDefaultAsync(cancellationToken);

        var targetId = revisionId ?? (pinned ? null : activeRevisionId);
        if (targetId is null)
        {
            // Never configured, or an activation that happened after a never-configured
            // first page: either way this chain evaluates nothing and says so in coverage.
            return new ResolvedScope(null, activeRevisionId);
        }

        var revision = await (from candidate in db.SceneConfigurationRevisions.AsNoTracking()
                              join configuration in db.SceneConfigurations.AsNoTracking()
                                  on candidate.SceneConfigurationId equals configuration.Id
                              where candidate.Id == targetId && configuration.CameraId == cameraId
                              select candidate)
            .Include(candidate => candidate.Zones)
            .Include(candidate => candidate.TripLines)
            .SingleOrDefaultAsync(cancellationToken);

        return revision is null ? null : new ResolvedScope(revision, activeRevisionId);
    }

    /// <summary>
    /// Coverage over the distinct runs of the base candidate set, after every ordinary
    /// filter and the latest-run scope, before analytic predicates and pagination.
    /// </summary>
    /// <remarks>
    /// A zero-run denominator is complete vacuously: there was nothing in scope to
    /// evaluate, so every bucket is zero and <c>Complete</c> is true. That is the
    /// genuinely-empty observation, and it is a different answer from a non-empty
    /// denominator none of whose runs were evaluated — which lands in the pending,
    /// failed, stale, not-configured or disabled buckets and is therefore incomplete.
    /// Callers must keep those two apart; the arithmetic here already does.
    /// </remarks>
    public static async Task<TrackAnalyticsCoverage> ComputeCoverageAsync(
        MaviDbContext db,
        IQueryable<TrackCandidate> candidates,
        TrackAnalyticsPinnedIdentity identity,
        ResolvedScope scope,
        long snapshotVisibilitySequence,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(db);
        ArgumentNullException.ThrowIfNull(candidates);
        ArgumentNullException.ThrowIfNull(identity);
        ArgumentNullException.ThrowIfNull(scope);

        var runIds = await candidates.Select(x => x.run.Id).Distinct().ToListAsync(cancellationToken);

        if (scope.Revision is null)
        {
            return new TrackAnalyticsCoverage(null, identity.AlgorithmVersion, 0, 0, 0, runIds.Count, 0, 0, 0, 0);
        }

        if (!scope.AnalyticsEnabled)
        {
            // The resolved revision itself is empty. A disabled revision never receives a
            // unit, so there is nothing to evaluate and every run is a switch-off, not a gap.
            return new TrackAnalyticsCoverage(scope.Revision.Id, identity.AlgorithmVersion, 0, 0, 0, 0, runIds.Count, 0, 0, 0);
        }

        if (runIds.Count == 0)
        {
            return new TrackAnalyticsCoverage(scope.Revision.Id, identity.AlgorithmVersion, 0, 0, 0, 0, 0, 0, 0, 0);
        }

        var revisionId = scope.Revision.Id;
        var algorithmVersion = identity.AlgorithmVersion;
        var units = await db.SceneAnalyses.AsNoTracking()
            .Where(unit => runIds.Contains(unit.ProcessingRunId))
            .Select(unit => new
            {
                unit.Id,
                unit.ProcessingRunId,
                unit.RevisionId,
                unit.AlgorithmVersion,
                unit.Status,
                unit.VisibilitySequence,
            })
            .ToListAsync(cancellationToken);

        // A missing unit is "pending" only where automatic reconciliation can legitimately
        // create it: the active revision and the current engine. Any other identity is
        // history, and history that was never computed is stale, not on its way.
        var identityIsCurrent = scope.ActiveRevisionId == revisionId
            && string.Equals(algorithmVersion, SceneAnalyticsAlgorithm.Version, StringComparison.Ordinal);

        var evaluated = 0;
        var pending = 0;
        var failed = 0;
        var stale = 0;
        var evaluatedUnitIds = new List<Guid>(runIds.Count);

        foreach (var runId in runIds)
        {
            var exact = units.FirstOrDefault(unit =>
                unit.ProcessingRunId == runId
                && unit.RevisionId == revisionId
                && string.Equals(unit.AlgorithmVersion, algorithmVersion, StringComparison.Ordinal));

            switch (exact?.Status)
            {
                case SceneAnalysisStatus.Completed:
                case SceneAnalysisStatus.Superseded:
                    // Fact-bearing, but only if it was published inside this snapshot: a
                    // unit completed after the first page is not part of the answer.
                    if (exact.VisibilitySequence is { } sequence && sequence <= snapshotVisibilitySequence)
                    {
                        evaluated++;
                        evaluatedUnitIds.Add(exact.Id);
                    }
                    else
                    {
                        pending++;
                    }
                    break;
                case SceneAnalysisStatus.Queued:
                case SceneAnalysisStatus.Running:
                    pending++;
                    break;
                case SceneAnalysisStatus.Failed:
                    failed++;
                    break;
                default:
                    if (!identityIsCurrent)
                    {
                        stale++;
                    }
                    else if (units.Any(unit => unit.ProcessingRunId == runId
                                 && unit.Status is SceneAnalysisStatus.Completed or SceneAnalysisStatus.Superseded))
                    {
                        // Older facts exist for this run; the current geometry has not been
                        // applied. The same word the readiness rule uses.
                        stale++;
                    }
                    else
                    {
                        pending++;
                    }
                    break;
            }
        }

        var analysedTracks = 0;
        var unavailableTracks = 0;
        if (evaluatedUnitIds.Count > 0)
        {
            // Evidence accounting inside the same candidate set, not whole-unit totals: a
            // Track the ordinary filters excluded is not counted either way.
            var accounting = await candidates
                .Join(
                    db.TrackAnalysisOutcomes.AsNoTracking().Where(outcome => evaluatedUnitIds.Contains(outcome.AnalysisId)),
                    x => x.track.Id,
                    outcome => outcome.TrackId,
                    (x, outcome) => outcome.Outcome)
                .GroupBy(outcome => outcome)
                .Select(group => new { Outcome = group.Key, Count = group.Count() })
                .ToListAsync(cancellationToken);
            analysedTracks = accounting.FirstOrDefault(x => x.Outcome == TrackAnalysisOutcomeKind.Analysed)?.Count ?? 0;
            unavailableTracks = accounting.FirstOrDefault(x => x.Outcome == TrackAnalysisOutcomeKind.Unavailable)?.Count ?? 0;
        }

        return new TrackAnalyticsCoverage(
            revisionId, algorithmVersion, evaluated, pending, failed, 0, 0, stale, analysedTracks, unavailableTracks);
    }

    /// <summary>
    /// The fact-bearing analysis units of the resolved identity that are visible in this
    /// snapshot, for the runs of the given candidate set.
    /// </summary>
    /// <remarks>
    /// <c>Completed</c> and <c>Superseded</c> both qualify: the join is already pinned to
    /// one revision and one algorithm version, which <i>is</i> the unit's identity, so
    /// admitting a superseded unit widens nothing. Currency is not validity (ADR-011).
    /// </remarks>
    public static IQueryable<SceneAnalysis> VisibleUnits(
        MaviDbContext db,
        Guid revisionId,
        string algorithmVersion,
        long snapshotVisibilitySequence)
    {
        ArgumentNullException.ThrowIfNull(db);
        return db.SceneAnalyses.AsNoTracking().Where(unit =>
            unit.RevisionId == revisionId
            && unit.AlgorithmVersion == algorithmVersion
            && (unit.Status == SceneAnalysisStatus.Completed || unit.Status == SceneAnalysisStatus.Superseded)
            && unit.VisibilitySequence != null
            && unit.VisibilitySequence <= snapshotVisibilitySequence);
    }
}
