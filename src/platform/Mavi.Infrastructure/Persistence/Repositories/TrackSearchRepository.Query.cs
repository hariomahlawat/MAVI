using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Query;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Contracts.Api.Analytics;
using Mavi.Contracts.Api.Query;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The Track unit of the structured query contract (ADR-024 §5), over Track search's own machinery: the base chain,
/// the Stage 3 analytic predicates, the S5 attribute predicate, the Stage 4 plate predicate and each one's coverage.
/// A query here is the same set Track search would page through for the same filters; it is read whole (up to the
/// contract's bound) so the evaluator can count it.
/// </summary>
public sealed partial class TrackSearchRepository
{
    internal async Task<QueryRead<QueryTrackRecord>> ReadQueryTracksAsync(
        QueryPredicates where,
        IReadOnlyList<QueryReadWindow> windows,
        QueryCapabilityIdentities identities,
        CancellationToken cancellationToken)
    {
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        if (where.Plate is not null)
            await db.Database.ExecuteSqlRawAsync(NoParallelWorkers, cancellationToken);

        // ADR-011 decision 8: the barrier before a byte of scope is read, so every window, every coverage block and
        // every record below belongs to one world.
        await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(db, cancellationToken);
        var snapshotVisibilitySequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);

        var cameras = await StructuredQueryScope.ResolveCamerasAsync(db, where.CameraIds, cancellationToken);
        if (cameras.Refusal is { } unknownCamera)
            return QueryRead.Refused<QueryTrackRecord>(unknownCamera);

        TrackAnalyticsQuery? analytics = null;
        ResolvedScope? scope = null;
        TrackAnalyticsPinnedIdentity? identity = null;
        var cameraIdentities = new List<QueryCameraIdentityResponse>();
        if (where.IsGeometric)
        {
            var camera = cameras.Cameras[0];
            analytics = new TrackAnalyticsQuery(
                null,
                null,
                where.Zone?.ZoneId,
                where.Zone?.Relation,
                where.Zone?.MinDwellMs,
                where.Line?.LineId,
                where.Line?.Direction,
                where.Motion?.Direction,
                where.Motion?.MinStationaryMs,
                where.Zone?.Loitering ?? false,
                false);
            scope = await ResolveRevisionAsync(camera.Id, null, cancellationToken)
                ?? throw new InvalidOperationException("A camera's active revision always resolves.");
            if (where.Zone is { } zone && (scope.Revision is null || scope.Revision.Zones.All(item => item.ZoneId != zone.ZoneId)))
                return QueryRead.Refused<QueryTrackRecord>(StructuredQueryScope.NotInRevision("/where/zone/zoneId", "zone"));
            if (where.Line is { } line && (scope.Revision is null || scope.Revision.TripLines.All(item => item.LineId != line.LineId)))
                return QueryRead.Refused<QueryTrackRecord>(StructuredQueryScope.NotInRevision("/where/line/lineId", "line"));
            identity = new TrackAnalyticsPinnedIdentity(camera.Id, scope.Revision?.Id, SceneAnalyticsAlgorithm.Version);
            cameraIdentities.Add(new QueryCameraIdentityResponse(
                camera.Id, camera.Code, camera.Name, scope.Revision?.Id, scope.Revision?.RevisionNumber, identity.AlgorithmVersion));
        }

        var reads = new List<QueryWindowRead<QueryTrackRecord>>(windows.Count);
        foreach (var window in windows)
        {
            var query = new TrackSearchQuery(
                where.CameraIds.Count == 1 ? where.CameraIds[0] : null,
                null,
                null,
                where.ObjectClass,
                window.Window.FromUtc,
                window.Window.ToUtc,
                where.MinDurationMs,
                where.MinConfidence,
                null,
                1,
                analytics,
                where.ObjectSubclass,
                where.Plate,
                where.Attributes);

            var coverage = new List<QueryCoverageComponentResponse>();
            if (analytics is not null)
            {
                var analyticsCoverage = await ComputeCoverageAsync(query, identity!, scope!, snapshotVisibilitySequence, cancellationToken);
                coverage.Add(new QueryCoverageComponentResponse(
                    "sceneAnalytics", window.Name, analyticsCoverage.Complete, identity!.CameraId, SceneAnalytics: ToResponse(analyticsCoverage)));
            }

            if (where.Attributes is { } attributes)
                coverage.Add(await AttributeCoverageAsync(query, where.CameraIds, attributes, identities, snapshotVisibilitySequence, window.Name, cancellationToken));
            if (where.Plate is not null)
                coverage.Add(await PlateCoverageAsync(query, where.CameraIds, identities.PlateFingerprint, snapshotVisibilitySequence, window.Name, cancellationToken));

            var records = await MatchingTracksAsync(
                query, where.CameraIds, identities, scope, identity, snapshotVisibilitySequence, cancellationToken);
            if (records.Count > QueryContract.MaximumMatchedRecords)
                return QueryRead.Refused<QueryTrackRecord>(StructuredQueryScope.TooLarge(window.Name));
            reads.Add(new QueryWindowRead<QueryTrackRecord>(records, coverage));
        }

        await transaction.CommitAsync(cancellationToken);
        return new QueryRead<QueryTrackRecord>(null, snapshotVisibilitySequence, cameraIdentities, reads);
    }

    /// <summary>
    /// The matching Tracks: the base chain (narrowed to the cameras named), each derived predicate, then the analytic
    /// predicates against the resolved revision's visible units. At most one more than the contract's bound.
    /// </summary>
    private async Task<IReadOnlyList<QueryTrackRecord>> MatchingTracksAsync(
        TrackSearchQuery query,
        IReadOnlyList<Guid> cameraIds,
        QueryCapabilityIdentities identities,
        ResolvedScope? scope,
        TrackAnalyticsPinnedIdentity? identity,
        long snapshotVisibilitySequence,
        CancellationToken cancellationToken)
    {
        var candidates = BaseCandidates(query, snapshotVisibilitySequence);
        if (cameraIds.Count > 1)
        {
            var ids = cameraIds.ToArray();
            candidates = candidates.Where(x => ids.Contains(x.camera.Id));
        }

        if (query.Attributes is { } attributes)
        {
            // No attribute capability: nothing can match, and coverage already says NotConfigured.
            if (identities.AttributeFingerprint is not { } attributeFingerprint)
                return [];
            candidates = WhereAttributesObserved(candidates, attributes, attributeFingerprint, snapshotVisibilitySequence);
        }

        if (query.Plate is { } plate)
        {
            if (identities.PlateFingerprint is not { } plateFingerprint)
                return [];
            var texts = MatchingTexts(plate);
            var visible = VisiblePlateAnalyses(plateFingerprint, snapshotVisibilitySequence);
            candidates = candidates.Where(x => texts.Any(text =>
                text.TrackId == x.track.Id &&
                visible.Any(analysis => analysis.Id == text.AnalysisId && analysis.ProcessingRunId == x.track.ProcessingRunId)));
        }

        if (query.Analytics is { } analytics)
        {
            if (scope?.Revision is null || !scope.AnalyticsEnabled)
                return [];
            var revisionId = scope.Revision.Id;
            var algorithmVersion = identity!.AlgorithmVersion;
            var evaluated = candidates.Join(
                AnalyticsScopeQuery.VisibleUnits(db, revisionId, algorithmVersion, snapshotVisibilitySequence),
                x => x.run.Id,
                unit => unit.ProcessingRunId,
                (x, unit) => new EvaluatedCandidate { Candidate = x, Unit = unit });
            candidates = ApplyPredicates(evaluated, analytics).Select(x => x.Candidate);
        }

        var rows = await candidates
            .Select(x => new
            {
                x.track.Id,
                CameraId = x.camera.Id,
                x.camera.Code,
                x.camera.Name,
                x.track.VideoAssetId,
                x.track.ProcessingRunId,
                x.track.ObjectClass,
                x.track.ObjectSubclass,
                x.track.ObjectSubclassSource,
                x.track.StartTimestampUtc,
                x.track.EndTimestampUtc,
                x.track.StartOffsetMs,
                x.track.DurationMs,
                x.track.MeanConfidence,
                ThumbnailArtifactId = x.observation == null ? null : x.observation.ThumbnailArtifactId,
            })
            .OrderBy(x => x.Id)
            .Take(QueryContract.MaximumMatchedRecords + 1)
            .ToListAsync(cancellationToken);

        return [.. rows.Select(x => new QueryTrackRecord(
            x.Id,
            x.CameraId,
            x.Code,
            x.Name,
            x.VideoAssetId,
            x.ProcessingRunId,
            x.ObjectClass,
            VehicleSubclassExposurePolicy.Expose(x.ObjectClass, x.ObjectSubclass, x.ObjectSubclassSource),
            x.StartTimestampUtc,
            x.EndTimestampUtc,
            x.StartOffsetMs,
            x.DurationMs,
            x.MeanConfidence,
            x.ThumbnailArtifactId))];
    }

    /// <summary>
    /// Attribute coverage of the scope, from S5's own computation. Several cameras are summed camera by camera: the
    /// computation is over one camera or all, and its buckets are counts of Tracks, so they add.
    /// </summary>
    private async Task<QueryCoverageComponentResponse> AttributeCoverageAsync(
        TrackSearchQuery query,
        IReadOnlyList<Guid> cameraIds,
        TrackAttributeQuery attributes,
        QueryCapabilityIdentities identities,
        long snapshotVisibilitySequence,
        string window,
        CancellationToken cancellationToken)
    {
        TrackAttributeCoverage coverage;
        if (cameraIds.Count <= 1)
        {
            coverage = await ComputeAttributeCoverageAsync(
                query, attributes, identities.AttributeFingerprint, identities.AttributeDisclosure, snapshotVisibilitySequence, cancellationToken);
        }
        else
        {
            var parts = new List<TrackAttributeCoverage>(cameraIds.Count);
            foreach (var cameraId in cameraIds)
            {
                parts.Add(await ComputeAttributeCoverageAsync(
                    query with { CameraId = cameraId }, attributes, identities.AttributeFingerprint, identities.AttributeDisclosure,
                    snapshotVisibilitySequence, cancellationToken));
            }

            coverage = new TrackAttributeCoverage(
                identities.AttributeFingerprint,
                identities.AttributeDisclosure,
                parts.Sum(part => part.TracksInScope),
                parts.Sum(part => part.Analysed),
                parts.Sum(part => part.Unavailable),
                parts.Sum(part => part.NotAnalysed),
                [.. Enumerable.Range(0, attributes.Predicates.Count).Select(index => parts.Sum(part => part.Unknown[index]))]);
        }

        var configured = identities.AttributeFingerprint is not null;
        return new QueryCoverageComponentResponse(
            "attributes",
            window,
            configured && coverage.NotAnalysed == 0,
            Attributes: new QueryAttributeCoverageResponse(
                coverage.TracksInScope,
                coverage.Analysed,
                coverage.Unavailable,
                coverage.NotAnalysed,
                [.. attributes.Predicates.Select((predicate, index) =>
                    new QueryAttributeAbstentionResponse(predicate.AttributeType, predicate.Value, coverage.Unknown[index]))]),
            Reason: configured ? null : "attributes_not_configured");
    }

    /// <summary>Plate coverage from Stage 4's own computation, summed camera by camera as attribute coverage is.</summary>
    private async Task<QueryCoverageComponentResponse> PlateCoverageAsync(
        TrackSearchQuery query,
        IReadOnlyList<Guid> cameraIds,
        string? fingerprint,
        long snapshotVisibilitySequence,
        string window,
        CancellationToken cancellationToken)
    {
        var parts = new List<TrackPlateCoverage>();
        var integrityFaults = 0;
        IEnumerable<TrackSearchQuery> scopes = cameraIds.Count <= 1
            ? [query]
            : cameraIds.Select(cameraId => query with { CameraId = cameraId });
        foreach (var scoped in scopes)
        {
            var (part, faults) = await ComputePlateCoverageAsync(scoped, fingerprint, snapshotVisibilitySequence, cancellationToken);
            parts.Add(part);
            integrityFaults += faults.Count;
        }

        var coverage = new QueryPlateCoverageResponse(
            parts.Sum(part => part.VehicleTracksInScope),
            parts.Sum(part => part.Ready),
            parts.Sum(part => part.Pending),
            parts.Sum(part => part.Failed),
            parts.Sum(part => part.Stale),
            parts.Sum(part => part.NotConfigured));
        var complete = fingerprint is not null && integrityFaults == 0 &&
            coverage.Pending == 0 && coverage.Failed == 0 && coverage.Stale == 0 && coverage.NotConfigured == 0;
        return new QueryCoverageComponentResponse(
            "plates",
            window,
            complete,
            Plates: coverage,
            Reason: fingerprint is null ? "plates_not_configured" : integrityFaults > 0 ? "plate_coverage_integrity_fault" : null);
    }

    internal static AnalyticsCoverageResponse ToResponse(TrackAnalyticsCoverage coverage) => new(
        coverage.SceneRevisionId,
        coverage.AlgorithmVersion,
        coverage.EvaluatedRuns,
        coverage.PendingRuns,
        coverage.FailedRuns,
        coverage.NotConfiguredRuns,
        coverage.DisabledRuns,
        coverage.StaleRuns,
        coverage.AnalysedTracks,
        coverage.UnavailableTracks);
}
