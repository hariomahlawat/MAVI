using Mavi.Application.Modules.Events;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.Events;
using Mavi.Domain.Processing;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// Derivation and reads for analytic events (ADR-025).
/// </summary>
/// <remarks>
/// <para>
/// A derivation is one short transaction over one fact-bearing unit. It serialises on a
/// transaction-scoped advisory lock keyed by the unit, re-checks that no derivation at the
/// catalogue version exists, reads the unit's persisted facts, runs the pure deriver and
/// inserts the derivation with its events. The unique (unit, catalogue version) index is
/// the backstop. No lease is needed: a unit's facts never change after completion and the
/// work is bounded by one run.
/// </para>
/// <para>
/// The timeline resolves its scope, identity and coverage through
/// <see cref="AnalyticsScopeQuery"/> under the processing-visibility barrier, exactly as the
/// Stage-3 aggregates do, so Events and Analytics cannot disagree about one camera and window.
/// </para>
/// </remarks>
public sealed partial class AnalyticEventRepository(MaviDbContext db) : IAnalyticEventRepository
{
    private const string UniqueViolation = "23505";
    private const string DerivationUniqueIndex = "ux_analytic_event_derivations_unit_catalogue";

    public async Task<IReadOnlyList<EventDerivationCandidate>> ListUnitsAwaitingDerivationAsync(
        string catalogueVersion,
        EventDerivationCandidate? after,
        int batchSize,
        CancellationToken cancellationToken)
    {
        var units = db.SceneAnalyses.AsNoTracking()
            .Where(unit =>
                (unit.Status == SceneAnalysisStatus.Completed || unit.Status == SceneAnalysisStatus.Superseded) &&
                unit.VisibilitySequence != null &&
                !db.AnalyticEventDerivations.Any(derivation =>
                    derivation.SceneAnalysisId == unit.Id && derivation.CatalogueVersion == catalogueVersion));
        if (after is not null)
        {
            var sequence = after.VisibilitySequence;
            var id = after.SceneAnalysisId;
            units = units.Where(unit =>
                unit.VisibilitySequence > sequence || (unit.VisibilitySequence == sequence && unit.Id > id));
        }

        return await units
            .OrderBy(unit => unit.VisibilitySequence)
            .ThenBy(unit => unit.Id)
            .Select(unit => new EventDerivationCandidate(unit.VisibilitySequence!.Value, unit.Id))
            .Take(batchSize)
            .ToListAsync(cancellationToken);
    }

    public async Task<EventDerivationOutcome> DeriveAsync(
        Guid sceneAnalysisId,
        RuleCatalogueDefinition catalogue,
        DateTimeOffset nowUtc,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(catalogue);

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        await db.Database.ExecuteSqlInterpolatedAsync(
            $"SELECT pg_advisory_xact_lock(hashtextextended({"analytic-events:" + sceneAnalysisId.ToString("D")}, 0))",
            cancellationToken);

        if (await db.AnalyticEventDerivations.AsNoTracking().AnyAsync(
                derivation => derivation.SceneAnalysisId == sceneAnalysisId &&
                              derivation.CatalogueVersion == catalogue.CatalogueVersion,
                cancellationToken))
        {
            return EventDerivationOutcome.AlreadyDerived;
        }

        var (outcome, input) = await ReadInputAsync(sceneAnalysisId, cancellationToken);
        if (input is null)
            return outcome;

        var result = EventDeriver.Derive(input, catalogue);
        var unit = input.Unit;
        var derivation = AnalyticEventDerivation.Create(
            unit.SceneAnalysisId,
            unit.ProcessingRunId,
            unit.CameraId,
            unit.SceneRevisionId,
            unit.AnalyticsAlgorithmVersion,
            result.CatalogueVersion,
            result.CatalogueSha256,
            result.InputsSha256,
            result.Events.Count,
            result.RuleStatesJson,
            nowUtc);
        db.AnalyticEventDerivations.Add(derivation);
        foreach (var item in result.Events)
        {
            db.AnalyticEvents.Add(AnalyticEvent.Create(
                item.EventId,
                derivation.Id,
                unit.SceneAnalysisId,
                unit.ProcessingRunId,
                unit.VideoAssetId,
                unit.CameraId,
                unit.SceneRevisionId,
                unit.AnalyticsAlgorithmVersion,
                result.CatalogueVersion,
                item.RuleId,
                item.RuleVersion,
                item.PrimaryTrackId,
                item.ObjectClass,
                item.ZoneId,
                item.LineId,
                item.Direction,
                item.StartOffsetMs,
                item.EndOffsetMs,
                item.StartUtc,
                item.EndUtc,
                item.Provenance.Participants.Count,
                item.ProvenanceJson,
                item.InputSha256));
        }

        try
        {
            await db.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
        }
        catch (DbUpdateException exception) when (exception.InnerException is PostgresException
                                                 {
                                                     SqlState: UniqueViolation,
                                                     ConstraintName: DerivationUniqueIndex,
                                                 })
        {
            // Another writer won; its derivation is the same deterministic answer.
            db.ChangeTracker.Clear();
            return EventDerivationOutcome.AlreadyDerived;
        }
        finally
        {
            db.ChangeTracker.Clear();
        }

        return EventDerivationOutcome.Derived;
    }

    public async Task<EventDerivationInput?> ReadDerivationInputAsync(
        Guid sceneAnalysisId,
        CancellationToken cancellationToken) =>
        (await ReadInputAsync(sceneAnalysisId, cancellationToken)).Input;

    private async Task<(EventDerivationOutcome Outcome, EventDerivationInput? Input)> ReadInputAsync(
        Guid sceneAnalysisId,
        CancellationToken cancellationToken)
    {
        var unit = await db.SceneAnalyses.AsNoTracking()
            .Where(candidate => candidate.Id == sceneAnalysisId)
            .Select(candidate => new
            {
                candidate.Id,
                candidate.ProcessingRunId,
                candidate.RevisionId,
                candidate.AlgorithmVersion,
                candidate.Status,
                candidate.VisibilitySequence,
            })
            .SingleOrDefaultAsync(cancellationToken);
        if (unit is null)
            return (EventDerivationOutcome.NotFound, null);
        if (unit.Status is not (SceneAnalysisStatus.Completed or SceneAnalysisStatus.Superseded) || unit.VisibilitySequence is null)
            return (EventDerivationOutcome.NotFactBearing, null);

        var run = await (from processingRun in db.ProcessingRuns.AsNoTracking()
                         join video in db.VideoAssets.AsNoTracking() on processingRun.VideoAssetId equals video.Id
                         where processingRun.Id == unit.ProcessingRunId
                         select new { processingRun.Id, VideoAssetId = video.Id, video.CameraId, video.RecordingStartUtc })
            .SingleAsync(cancellationToken);

        var revision = await db.SceneConfigurationRevisions.AsNoTracking()
            .Include(candidate => candidate.Zones)
            .Include(candidate => candidate.TripLines)
            .SingleAsync(candidate => candidate.Id == unit.RevisionId, cancellationToken);

        // Analysed Tracks only: an unavailable outcome produced no facts, and nothing an
        // event says may rest on a Track the unit could not read.
        var tracks = await (from outcome in db.TrackAnalysisOutcomes.AsNoTracking()
                            join track in db.Tracks.AsNoTracking() on outcome.TrackId equals track.Id
                            where outcome.AnalysisId == unit.Id && outcome.Outcome == TrackAnalysisOutcomeKind.Analysed
                            select new EventTrack(track.Id, track.ObjectClass, track.EntityId))
            .ToListAsync(cancellationToken);

        var visits = await db.TrackZoneVisits.AsNoTracking()
            .Where(visit => visit.AnalysisId == unit.Id)
            .Select(visit => new EventZoneVisit(
                visit.Id, visit.TrackId, visit.ZoneId, visit.VisitIndex, visit.EntryOffsetMs, visit.ExitOffsetMs, visit.DwellMs))
            .ToListAsync(cancellationToken);

        var summaries = await db.TrackZoneSummaries.AsNoTracking()
            .Where(summary => summary.AnalysisId == unit.Id)
            .Select(summary => new EventZoneSummary(
                summary.TrackId,
                summary.ZoneId,
                summary.VisitCount,
                summary.TotalDwellMs,
                summary.Loitering,
                summary.LoiteringThresholdSeconds))
            .ToListAsync(cancellationToken);

        var crossings = await db.TrackLineCrossings.AsNoTracking()
            .Where(crossing => crossing.AnalysisId == unit.Id)
            .Select(crossing => new EventLineCrossing(
                crossing.Id, crossing.TrackId, crossing.LineId, crossing.CrossingIndex, crossing.OffsetMs, crossing.Direction, crossing.TimestampUtc))
            .ToListAsync(cancellationToken);

        var motions = await db.TrackMotionSummaries.AsNoTracking()
            .Where(motion => motion.AnalysisId == unit.Id)
            .ToListAsync(cancellationToken);
        var intervals = motions
            .SelectMany(motion => motion.StationaryIntervals.Select((interval, index) =>
                new EventStationaryInterval(motion.TrackId, index, interval.StartOffsetMs, interval.EndOffsetMs)))
            .ToList();

        return (EventDerivationOutcome.Derived, new EventDerivationInput(
            new EventUnitIdentity(
                unit.Id,
                run.Id,
                run.VideoAssetId,
                run.CameraId,
                revision.Id,
                revision.RevisionNumber,
                unit.AlgorithmVersion,
                run.RecordingStartUtc),
            [.. revision.Zones.Select(zone => new EventZone(zone.ZoneId, zone.Name, zone.Kind, zone.Enabled))],
            [.. revision.TripLines.Select(line => new EventLine(
                line.LineId, line.Name, line.Enabled, line.AToBLabel, line.BToALabel, line.PermittedDirection))],
            tracks,
            visits,
            summaries,
            crossings,
            intervals));
    }

    public async Task<AnalyticEventTimelineResult> ReadTimelineAsync(
        AnalyticEventTimelineQuery query,
        RuleCatalogueDefinition catalogue,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);
        ArgumentNullException.ThrowIfNull(catalogue);
        var catalogueVersion = catalogue.CatalogueVersion;

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        // ADR-011 decision 8: the shared barrier before any snapshot-defining read.
        await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(db, cancellationToken);
        var snapshotVisibilitySequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);

        if (!await db.Cameras.AsNoTracking().AnyAsync(camera => camera.Id == query.CameraId, cancellationToken))
            return AnalyticEventTimelineResult.NotFound(catalogueVersion);

        var scope = await AnalyticsScopeQuery.ResolveRevisionAsync(db, query.CameraId, null, cancellationToken);
        if (scope is null)
            return AnalyticEventTimelineResult.NotFound(catalogueVersion);

        var algorithmVersion = SceneAnalyticsAlgorithm.Version;
        var identity = new AnalyticsResolvedIdentity(
            query.CameraId,
            scope.Revision?.Id,
            scope.Revision?.RevisionNumber,
            algorithmVersion,
            snapshotVisibilitySequence);

        var candidates = AnalyticsScopeQuery.BaseCandidates(
            db,
            AnalyticsScopeRequest.ForCameraWindow(query.CameraId, query.FromUtc, query.ToUtc, null),
            snapshotVisibilitySequence);
        var coverage = await AnalyticsScopeQuery.ComputeCoverageAsync(
            db,
            candidates,
            new Mavi.Application.Modules.Intelligence.TrackAnalyticsPinnedIdentity(query.CameraId, scope.Revision?.Id, algorithmVersion),
            scope,
            snapshotVisibilitySequence,
            cancellationToken);

        if (scope.Revision is null || !scope.AnalyticsEnabled)
        {
            await transaction.CommitAsync(cancellationToken);
            return new AnalyticEventTimelineResult(
                true, identity, catalogueVersion, coverage, 0, 0, [], [], [], new Dictionary<string, int>(), [], false);
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

        var inWindow = db.AnalyticEvents.AsNoTracking()
            .Where(item => derivedUnitIds.Contains(item.SceneAnalysisId) &&
                           item.CatalogueVersion == catalogueVersion &&
                           item.StartUtc < query.ToUtc &&
                           // Half-open [from, to): a span that ended exactly at "from" is outside;
                           // a point event at "from" is inside.
                           (item.EndUtc > query.FromUtc || item.StartUtc >= query.FromUtc));
        if (query.RuleIds is { } ruleIds)
        {
            var allowed = ruleIds.ToList();
            inWindow = inWindow.Where(item => allowed.Contains(item.RuleId));
        }

        var page = await inWindow
            .OrderBy(item => item.StartUtc)
            .ThenBy(item => item.Id)
            .Take(query.Limit + 1)
            .Select(item => new AnalyticEventRow(
                item.Id,
                item.RuleId,
                item.RuleVersion,
                item.StartUtc,
                item.EndUtc,
                item.StartOffsetMs,
                item.EndOffsetMs,
                item.VideoAssetId,
                item.ProcessingRunId,
                item.PrimaryTrackId,
                item.ObjectClass,
                item.ZoneId,
                item.LineId,
                item.Direction,
                item.ParticipantCount))
            .ToListAsync(cancellationToken);

        var ruleCounts = await inWindow
            .GroupBy(item => item.RuleId)
            .Select(group => new { RuleId = group.Key, Count = group.Count() })
            .ToDictionaryAsync(group => group.RuleId, group => group.Count, cancellationToken);

        // The same half-open window the Stage-3 crossing aggregate counts in.
        var crossings = await inWindow
            .Where(item => item.RuleId == EventRuleIds.LineCrossing &&
                           item.LineId != null &&
                           item.StartUtc >= query.FromUtc)
            .Select(item => new EventCrossingPoint(item.LineId!.Value, item.StartUtc, item.Direction == CrossingDirection.AToB))
            .ToListAsync(cancellationToken);

        await transaction.CommitAsync(cancellationToken);

        var truncated = page.Count > query.Limit;
        return new AnalyticEventTimelineResult(
            true,
            identity,
            catalogueVersion,
            coverage,
            derivedUnitIds.Count,
            unitIds.Count - derivedUnitIds.Count,
            [.. revision.Zones.Where(zone => zone.Enabled).Select(zone => new EventGeometryZone(zone.ZoneId, zone.Name))],
            [.. revision.TripLines.Where(line => line.Enabled)
                .Select(line => new EventGeometryLine(line.LineId, line.Name, line.AToBLabel, line.BToALabel))],
            truncated ? page.Take(query.Limit).ToList() : page,
            ruleCounts,
            crossings,
            truncated);
    }

    public async Task<AnalyticEventDetailView?> GetEventAsync(Guid eventId, CancellationToken cancellationToken)
    {
        var found = await (from candidate in db.AnalyticEvents.AsNoTracking()
                           join derivation in db.AnalyticEventDerivations.AsNoTracking() on candidate.DerivationId equals derivation.Id
                           join run in db.ProcessingRuns.AsNoTracking() on candidate.ProcessingRunId equals run.Id
                           join revision in db.SceneConfigurationRevisions.AsNoTracking() on candidate.SceneRevisionId equals revision.Id
                           where candidate.Id == eventId &&
                                 run.Status == ProcessingRunStatus.Completed &&
                                 run.VisibilitySequence != null
                           select new { item = candidate, derivation.CatalogueSha256, derivation.DerivedAtUtc, revision.RevisionNumber })
            .SingleOrDefaultAsync(cancellationToken);
        if (found is null)
            return null;

        var item = found.item;
        string? zoneName = null;
        if (item.ZoneId is { } zoneId)
        {
            zoneName = await db.SceneConfigurationRevisions.AsNoTracking()
                .Where(revision => revision.Id == item.SceneRevisionId)
                .SelectMany(revision => revision.Zones)
                .Where(zone => zone.ZoneId == zoneId)
                .Select(zone => zone.Name)
                .SingleOrDefaultAsync(cancellationToken);
        }

        EventGeometryLine? line = null;
        if (item.LineId is { } lineId)
        {
            line = await db.SceneConfigurationRevisions.AsNoTracking()
                .Where(revision => revision.Id == item.SceneRevisionId)
                .SelectMany(revision => revision.TripLines)
                .Where(candidate => candidate.LineId == lineId)
                .Select(candidate => new EventGeometryLine(candidate.LineId, candidate.Name, candidate.AToBLabel, candidate.BToALabel))
                .SingleOrDefaultAsync(cancellationToken);
        }

        var provenance = RuleCatalogueDefinition.ReadProvenance(item.ProvenanceJson);
        var participantIds = provenance.Participants.Select(participant => participant.TrackId).ToList();
        var tracks = await (from track in db.Tracks.AsNoTracking()
                            join observation in db.Observations.AsNoTracking()
                                on track.RepresentativeObservationId equals observation.Id into observations
                            from observation in observations.DefaultIfEmpty()
                            where participantIds.Contains(track.Id)
                            select new
                            {
                                track.Id,
                                track.VideoAssetId,
                                track.StartOffsetMs,
                                track.EndOffsetMs,
                                ThumbnailArtifactId = observation == null ? null : observation.ThumbnailArtifactId,
                            })
            .ToDictionaryAsync(track => track.Id, cancellationToken);

        var participants = provenance.Participants
            .Where(participant => tracks.ContainsKey(participant.TrackId))
            .Select(participant =>
            {
                var track = tracks[participant.TrackId];
                return new AnalyticEventParticipantView(
                    participant.TrackId,
                    participant.Role,
                    participant.ObjectClass,
                    track.VideoAssetId,
                    track.StartOffsetMs,
                    track.EndOffsetMs,
                    track.ThumbnailArtifactId);
            })
            .ToList();

        return new AnalyticEventDetailView(
            new AnalyticEventRow(
                item.Id,
                item.RuleId,
                item.RuleVersion,
                item.StartUtc,
                item.EndUtc,
                item.StartOffsetMs,
                item.EndOffsetMs,
                item.VideoAssetId,
                item.ProcessingRunId,
                item.PrimaryTrackId,
                item.ObjectClass,
                item.ZoneId,
                item.LineId,
                item.Direction,
                item.ParticipantCount),
            item.CameraId,
            item.SceneAnalysisId,
            item.SceneRevisionId,
            found.RevisionNumber,
            item.AnalyticsAlgorithmVersion,
            item.CatalogueVersion,
            found.CatalogueSha256,
            item.InputSha256,
            found.DerivedAtUtc,
            zoneName,
            line,
            provenance,
            participants);
    }
}
