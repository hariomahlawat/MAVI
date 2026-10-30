using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Query;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Contracts.Api.Query;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The Event unit of the structured query contract (ADR-024 §5). Each camera is resolved, covered and read exactly as
/// the events timeline reads it (<see cref="ReadTimelineAsync"/>): the camera's active revision, the current analytics
/// engine, the base chain's coverage, the derived units of the current catalogue and the same half-open window rule.
/// All cameras and windows share one snapshot.
/// </summary>
public sealed partial class AnalyticEventRepository
{
    internal async Task<QueryRead<QueryEventRecord>> ReadQueryEventsAsync(
        QueryPredicates where,
        IReadOnlyList<QueryReadWindow> windows,
        CancellationToken cancellationToken)
    {
        var catalogueVersion = where.CatalogueVersion
            ?? throw new ArgumentException("An Event query pins its catalogue version.", nameof(where));

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(db, cancellationToken);
        var snapshotVisibilitySequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);

        var cameras = await StructuredQueryScope.ResolveCamerasAsync(db, where.CameraIds, cancellationToken);
        if (cameras.Refusal is { } unknownCamera)
            return QueryRead.Refused<QueryEventRecord>(unknownCamera);

        var algorithmVersion = SceneAnalyticsAlgorithm.Version;
        var scopes = new List<(QueryCamera Camera, ResolvedScope Scope)>(cameras.Cameras.Count);
        foreach (var camera in cameras.Cameras)
        {
            var scope = await AnalyticsScopeQuery.ResolveRevisionAsync(db, camera.Id, null, cancellationToken)
                ?? throw new InvalidOperationException("A camera's active revision always resolves.");
            scopes.Add((camera, scope));
        }

        // A zone or line must belong to the revision of a camera in scope; an id from nowhere is refused, not counted
        // as an observed absence.
        if (where.Zone is { } zone && !scopes.Any(item => item.Scope.Revision?.Zones.Any(candidate => candidate.ZoneId == zone.ZoneId) == true))
            return QueryRead.Refused<QueryEventRecord>(StructuredQueryScope.NotInRevision("/where/zone/zoneId", "zone"));
        if (where.Line is { } line && !scopes.Any(item => item.Scope.Revision?.TripLines.Any(candidate => candidate.LineId == line.LineId) == true))
            return QueryRead.Refused<QueryEventRecord>(StructuredQueryScope.NotInRevision("/where/line/lineId", "line"));

        var identities = scopes
            .Select(item => new QueryCameraIdentityResponse(
                item.Camera.Id, item.Camera.Code, item.Camera.Name, item.Scope.Revision?.Id, item.Scope.Revision?.RevisionNumber, algorithmVersion))
            .ToList();

        var reads = new List<QueryWindowRead<QueryEventRecord>>(windows.Count);
        foreach (var window in windows)
        {
            var records = new List<QueryEventRecord>();
            var coverage = new List<QueryCoverageComponentResponse>(scopes.Count);
            foreach (var (camera, scope) in scopes)
            {
                var candidates = AnalyticsScopeQuery.BaseCandidates(
                    db,
                    AnalyticsScopeRequest.ForCameraWindow(camera.Id, window.Window.FromUtc, window.Window.ToUtc, null),
                    snapshotVisibilitySequence);
                var analyticsCoverage = await AnalyticsScopeQuery.ComputeCoverageAsync(
                    db,
                    candidates,
                    new TrackAnalyticsPinnedIdentity(camera.Id, scope.Revision?.Id, algorithmVersion),
                    scope,
                    snapshotVisibilitySequence,
                    cancellationToken);

                if (scope.Revision is null || !scope.AnalyticsEnabled)
                {
                    coverage.Add(new QueryCoverageComponentResponse(
                        "events", window.Name, analyticsCoverage.Complete, camera.Id,
                        TrackSearchRepository.ToResponse(analyticsCoverage), 0, 0));
                    continue;
                }

                var revision = scope.Revision;
                var runIds = candidates.Select(x => x.run.Id).Distinct();
                var unitIds = await AnalyticsScopeQuery.VisibleUnits(db, revision.Id, algorithmVersion, snapshotVisibilitySequence)
                    .Where(unit => runIds.Contains(unit.ProcessingRunId))
                    .Select(unit => unit.Id)
                    .ToListAsync(cancellationToken);
                var derivedUnitIds = await db.AnalyticEventDerivations.AsNoTracking()
                    .Where(derivation => unitIds.Contains(derivation.SceneAnalysisId) && derivation.CatalogueVersion == catalogueVersion)
                    .Select(derivation => derivation.SceneAnalysisId)
                    .ToListAsync(cancellationToken);
                var pending = unitIds.Count - derivedUnitIds.Count;
                coverage.Add(new QueryCoverageComponentResponse(
                    "events", window.Name, analyticsCoverage.Complete && pending == 0, camera.Id,
                    TrackSearchRepository.ToResponse(analyticsCoverage), derivedUnitIds.Count, pending));

                var from = window.Window.FromUtc;
                var to = window.Window.ToUtc;
                var events = db.AnalyticEvents.AsNoTracking()
                    .Where(item => derivedUnitIds.Contains(item.SceneAnalysisId) &&
                                   item.CatalogueVersion == catalogueVersion &&
                                   item.StartUtc < to &&
                                   // The timeline's half-open rule: a span that ended exactly at "from" is outside;
                                   // a point event at "from" is inside.
                                   (item.EndUtc > from || item.StartUtc >= from));
                if (where.RuleIds.Count > 0)
                {
                    var rules = where.RuleIds.ToList();
                    events = events.Where(item => rules.Contains(item.RuleId));
                }

                if (where.ObjectClass is { } objectClass)
                {
                    var name = objectClass.ToString();
                    events = events.Where(item => item.ObjectClass == name);
                }

                if (where.Zone is { } zoneFilter)
                    events = events.Where(item => item.ZoneId == zoneFilter.ZoneId);
                if (where.Line is { } lineFilter)
                {
                    events = events.Where(item => item.LineId == lineFilter.LineId);
                    if (lineFilter.Direction is { } direction)
                    {
                        var persisted = TrackAnalyticsQueryRules.ToPersisted(direction);
                        events = events.Where(item => item.Direction == persisted);
                    }
                }

                var rows = await events
                    .OrderBy(item => item.Id)
                    .Take(QueryContract.MaximumMatchedRecords + 1 - records.Count)
                    .Select(item => new
                    {
                        item.Id,
                        item.RuleId,
                        item.RuleVersion,
                        item.VideoAssetId,
                        item.PrimaryTrackId,
                        item.ObjectClass,
                        item.ZoneId,
                        item.LineId,
                        item.Direction,
                        item.StartUtc,
                        item.EndUtc,
                        item.StartOffsetMs,
                    })
                    .ToListAsync(cancellationToken);

                var zoneNames = revision.Zones.ToDictionary(item => item.ZoneId, item => item.Name);
                var lineNames = revision.TripLines.ToDictionary(item => item.LineId, item => item.Name);
                records.AddRange(rows.Select(row => new QueryEventRecord(
                    row.Id,
                    row.RuleId,
                    row.RuleVersion,
                    camera.Id,
                    camera.Code,
                    camera.Name,
                    row.VideoAssetId,
                    row.PrimaryTrackId,
                    row.ObjectClass,
                    row.ZoneId,
                    row.ZoneId is { } zoneId && zoneNames.TryGetValue(zoneId, out var zoneName) ? zoneName : null,
                    row.LineId,
                    row.LineId is { } lineId && lineNames.TryGetValue(lineId, out var lineName) ? lineName : null,
                    row.Direction,
                    row.StartUtc,
                    row.EndUtc,
                    row.StartOffsetMs)));
                if (records.Count > QueryContract.MaximumMatchedRecords)
                    return QueryRead.Refused<QueryEventRecord>(StructuredQueryScope.TooLarge(window.Name));
            }

            reads.Add(new QueryWindowRead<QueryEventRecord>(records, coverage));
        }

        await transaction.CommitAsync(cancellationToken);
        return new QueryRead<QueryEventRecord>(null, snapshotVisibilitySequence, identities, reads);
    }
}
