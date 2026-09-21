using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.SceneAnalytics;

/// <summary>Read-only projections behind the analytics status and re-analysis surfaces.</summary>
public sealed class SceneAnalyticsStatusReader(MaviDbContext db) : ISceneAnalyticsStatusReader
{
    public async Task<Guid?> GetRunCameraAsync(Guid processingRunId, CancellationToken cancellationToken) =>
        await (from run in db.ProcessingRuns.AsNoTracking()
               where run.Id == processingRunId
               join video in db.VideoAssets.AsNoTracking() on run.VideoAssetId equals video.Id
               select (Guid?)video.CameraId)
            .SingleOrDefaultAsync(cancellationToken);

    public async Task<Guid?> GetVisibleRunCameraAsync(Guid processingRunId, CancellationToken cancellationToken) =>
        await (from run in db.ProcessingRuns.AsNoTracking()
               where run.Id == processingRunId
                     && run.Status == ProcessingRunStatus.Completed
                     && run.VisibilitySequence != null
               join video in db.VideoAssets.AsNoTracking() on run.VideoAssetId equals video.Id
               select (Guid?)video.CameraId)
            .SingleOrDefaultAsync(cancellationToken);

    public async Task<SceneAnalyticsCameraScope?> GetCameraScopeAsync(
        Guid cameraId,
        CancellationToken cancellationToken)
    {
        if (!await db.Cameras.AsNoTracking().AnyAsync(camera => camera.Id == cameraId, cancellationToken))
        {
            return null;
        }

        // A camera with no configuration, and one whose configuration has no active
        // revision, are the same answer here: nothing to analyse against. The left join
        // keeps that a single query rather than a branch.
        var scope = await (from configuration in db.SceneConfigurations.AsNoTracking()
                           where configuration.CameraId == cameraId && configuration.ActiveRevisionId != null
                           join revision in db.SceneConfigurationRevisions.AsNoTracking()
                               on configuration.ActiveRevisionId equals revision.Id
                           select new SceneAnalyticsCameraScope(
                               cameraId,
                               revision.Id,
                               revision.RevisionNumber,
                               revision.Zones.Any(zone => zone.Enabled)
                                   || revision.TripLines.Any(line => line.Enabled)))
            .SingleOrDefaultAsync(cancellationToken);

        return scope ?? new SceneAnalyticsCameraScope(cameraId, null, null, false);
    }

    public async Task<IReadOnlyList<SceneAnalysisUnitView>> ListRunUnitsAsync(
        Guid processingRunId,
        CancellationToken cancellationToken) =>
        await UnitQuery(unit => unit.ProcessingRunId == processingRunId).ToListAsync(cancellationToken);

    public async Task<IReadOnlyList<Guid>> ListAnalysableRunsAsync(
        Guid cameraId,
        bool allRuns,
        CancellationToken cancellationToken)
    {
        // Completed and visible: analytics are derived from evidence that has already
        // been published, so a run that is not yet visible is not yet analysable.
        var analysable = from run in db.ProcessingRuns.AsNoTracking()
                         where run.Status == ProcessingRunStatus.Completed
                               && run.VisibilitySequence != null
                               && run.CompletedAtUtc != null
                         join video in db.VideoAssets.AsNoTracking() on run.VideoAssetId equals video.Id
                         where video.CameraId == cameraId
                         select new { run.Id, run.VideoAssetId, run.CompletedAtUtc };

        if (allRuns)
        {
            return await analysable
                .OrderBy(run => run.CompletedAtUtc).ThenBy(run => run.Id)
                .Select(run => run.Id)
                .ToListAsync(cancellationToken);
        }

        // "Re-analyse this camera" means its current picture of each video, not its whole
        // processing history; a video reprocessed three times has one latest answer.
        return await analysable
            .GroupBy(run => run.VideoAssetId)
            .Select(group => group
                .OrderByDescending(run => run.CompletedAtUtc)
                .ThenByDescending(run => run.Id)
                .First().Id)
            .ToListAsync(cancellationToken);
    }

    private IQueryable<SceneAnalysisUnitView> UnitQuery(
        System.Linq.Expressions.Expression<Func<Domain.SceneAnalytics.SceneAnalysis, bool>> predicate) =>
        from unit in db.SceneAnalyses.AsNoTracking().Where(predicate)
        join revision in db.SceneConfigurationRevisions.AsNoTracking() on unit.RevisionId equals revision.Id
        orderby unit.QueuedAtUtc, unit.Id
        select new SceneAnalysisUnitView(
            unit.Id,
            unit.ProcessingRunId,
            unit.RevisionId,
            revision.RevisionNumber,
            unit.AlgorithmVersion,
            unit.Status,
            unit.AttemptCount,
            unit.QueuedAtUtc,
            unit.StartedAtUtc,
            unit.CompletedAtUtc,
            unit.LeaseExpiresAtUtc,
            unit.AnalysedTrackCount,
            unit.UnavailableTrackCount,
            unit.FailureCode);
}
