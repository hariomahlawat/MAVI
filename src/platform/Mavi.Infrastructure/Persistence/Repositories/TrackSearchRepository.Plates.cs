using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Plates;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// The plate half of Track search and detail (Stage 4, plan §2.8, §5.4).
/// </summary>
/// <remarks>
/// <para>
/// <b>Predicate.</b> A Track matches when a fact-bearing plate analysis of its run, of the pinned
/// identity and published inside the snapshot, has a <c>plate_track_texts</c> row for the Track whose
/// <c>normalised_text</c> matches literally: a correlated EXISTS beside the analytic predicates, ANDed
/// with every other filter before keyset and ordering, which are unchanged. The fingerprint pins one
/// analysis per run (it is unique per run), so a superseding analysis published mid-pagination has
/// another fingerprint and cannot change what an open result set means; the superseded analysis stays
/// fact-bearing for the pinned one (ADR-013 §16).
/// </para>
/// <para>
/// <b>First page.</b> One linearisation point, as an analytic search: the shared visibility barrier
/// first (plate publication takes the exclusive one), then the snapshot, the analytic scope when
/// analytic predicates are combined, both coverage blocks over the base candidate scope, and the page.
/// A continuation evaluates against the pinned identities and snapshot and returns the pinned coverage.
/// </para>
/// <para>
/// <b>Privacy.</b> Nothing here logs; the plate text reaches PostgreSQL only as a bound parameter.
/// </para>
/// </remarks>
public sealed partial class TrackSearchRepository : ITrackPlateSearchRepository
{
    public async Task<TrackPlateSearchRepositoryResult> SearchPlatesAsync(
        TrackSearchQuery query,
        string? preferredFingerprint,
        TrackPlateCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);
        if (query.Plate is not { } plate)
            throw new ArgumentException("A plate search needs a plate query.", nameof(query));
        if (query.IsAnalytic != (cursor?.IsAnalytic ?? query.IsAnalytic))
            throw new ArgumentException("The cursor was minted for a different query kind.", nameof(cursor));

        if (cursor is not null)
            return await ContinuePlatesAsync(query, plate, cursor, take, cancellationToken);

        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        // As an analytic first page: the barrier before any scope is read, so the snapshot, the
        // plate analyses it admits and both coverage blocks describe one world.
        await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(db, cancellationToken);
        var snapshotVisibilitySequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);
        var snapshotUtc = timeProvider.GetUtcNow().ToUniversalTime();

        var plateCoverage = await ComputePlateCoverageAsync(
            BaseCandidates(query, snapshotVisibilitySequence), preferredFingerprint, snapshotVisibilitySequence, cancellationToken);

        TrackPlateSearchRepositoryPage page;
        if (query.Analytics is { } analytics)
        {
            var cameraId = await ResolveCameraAsync(query, cancellationToken);
            if (cameraId is null)
                return TrackPlateSearchRepositoryResult.Invalid;
            var scope = await ResolveRevisionAsync(cameraId.Value, analytics.SceneRevisionId, cancellationToken);
            if (scope is null)
                return TrackPlateSearchRepositoryResult.Invalid;
            var identity = new TrackAnalyticsPinnedIdentity(
                cameraId.Value,
                scope.Revision?.Id,
                analytics.AnalyticsAlgorithmVersion ?? SceneAnalyticsAlgorithm.Version);
            if (!OwnsGeometry(scope.Revision, analytics))
                return TrackPlateSearchRepositoryResult.Invalid;

            var analyticsCoverage = await ComputeCoverageAsync(query, identity, scope, snapshotVisibilitySequence, cancellationToken);
            page = await FetchAnalyticPlatePageAsync(
                query, plate, analytics, identity, analyticsCoverage, scope, preferredFingerprint, plateCoverage,
                snapshotUtc, snapshotVisibilitySequence, keyset: null, take, cancellationToken);
        }
        else
        {
            page = await FetchPlatePageAsync(
                query, plate, preferredFingerprint, plateCoverage, snapshotUtc, snapshotVisibilitySequence, keyset: null, take,
                cancellationToken);
        }

        await transaction.CommitAsync(cancellationToken);
        return new TrackPlateSearchRepositoryResult(page);
    }

    private async Task<TrackPlateSearchRepositoryResult> ContinuePlatesAsync(
        TrackSearchQuery query,
        TrackPlateQuery plate,
        TrackPlateCursorPosition cursor,
        int take,
        CancellationToken cancellationToken)
    {
        var position = cursor.Position;
        if (query.Analytics is not { } analytics)
        {
            return new TrackPlateSearchRepositoryResult(await FetchPlatePageAsync(
                query, plate, cursor.PlateIdentityFingerprint, cursor.PlateCoverage, position.SnapshotUtc,
                position.SnapshotVisibilitySequence, position, take, cancellationToken));
        }

        // The analytic half is continued exactly as an analytic continuation is: the supplied scope
        // must still resolve to the pinned camera, and the pinned revision is read as pinned.
        var identity = cursor.AnalyticsIdentity!;
        var cameraId = await ResolveCameraAsync(query, cancellationToken);
        if (cameraId is null || cameraId != identity.CameraId)
            return TrackPlateSearchRepositoryResult.Invalid;
        var scope = await ResolveRevisionAsync(cameraId.Value, identity.SceneRevisionId, cancellationToken, pinned: true);
        if (scope is null || !OwnsGeometry(scope.Revision, analytics))
            return TrackPlateSearchRepositoryResult.Invalid;

        return new TrackPlateSearchRepositoryResult(await FetchAnalyticPlatePageAsync(
            query, plate, analytics, identity, cursor.AnalyticsCoverage!, scope, cursor.PlateIdentityFingerprint,
            cursor.PlateCoverage, position.SnapshotUtc, position.SnapshotVisibilitySequence, position, take, cancellationToken));
    }

    private async Task<TrackPlateSearchRepositoryPage> FetchPlatePageAsync(
        TrackSearchQuery query,
        TrackPlateQuery plate,
        string? fingerprint,
        TrackPlateCoverage plateCoverage,
        DateTimeOffset snapshotUtc,
        long snapshotVisibilitySequence,
        TrackCursorPosition? keyset,
        int take,
        CancellationToken cancellationToken)
    {
        if (fingerprint is null)
        {
            // No plate capability is configured: nothing can match, and coverage says why.
            return new TrackPlateSearchRepositoryPage(
                [], snapshotUtc, snapshotVisibilitySequence, plateCoverage, new Dictionary<Guid, TrackItemPlate>());
        }

        var rows = await BuildQuery(
                query,
                snapshotVisibilitySequence,
                keyset,
                candidates => WherePlateMatches(candidates, plate, fingerprint, snapshotVisibilitySequence))
            .Take(take)
            .ToArrayAsync(cancellationToken);
        var itemPlates = await ExplainPlatesAsync(rows, plate, fingerprint, snapshotVisibilitySequence, cancellationToken);
        return new TrackPlateSearchRepositoryPage(rows, snapshotUtc, snapshotVisibilitySequence, plateCoverage, itemPlates);
    }

    private async Task<TrackPlateSearchRepositoryPage> FetchAnalyticPlatePageAsync(
        TrackSearchQuery query,
        TrackPlateQuery plate,
        TrackAnalyticsQuery analytics,
        TrackAnalyticsPinnedIdentity identity,
        TrackAnalyticsCoverage analyticsCoverage,
        ResolvedScope scope,
        string? fingerprint,
        TrackPlateCoverage plateCoverage,
        DateTimeOffset snapshotUtc,
        long snapshotVisibilitySequence,
        TrackCursorPosition? keyset,
        int take,
        CancellationToken cancellationToken)
    {
        if (fingerprint is null)
        {
            return new TrackPlateSearchRepositoryPage(
                [], snapshotUtc, snapshotVisibilitySequence, plateCoverage, new Dictionary<Guid, TrackItemPlate>(),
                identity, analyticsCoverage, new Dictionary<Guid, TrackItemAnalytics>());
        }

        var (rows, itemAnalytics) = await FetchPageAsync(
            query, analytics, identity, scope, snapshotVisibilitySequence, keyset, take, cancellationToken,
            candidates => WherePlateMatches(candidates, plate, fingerprint, snapshotVisibilitySequence));
        var itemPlates = await ExplainPlatesAsync(rows, plate, fingerprint, snapshotVisibilitySequence, cancellationToken);
        return new TrackPlateSearchRepositoryPage(
            rows, snapshotUtc, snapshotVisibilitySequence, plateCoverage, itemPlates, identity, analyticsCoverage, itemAnalytics);
    }

    // --- Predicate ---------------------------------------------------------------------------

    /// <summary>
    /// The fact-bearing plate analyses of one identity published inside the snapshot. Completed and
    /// Superseded both qualify: the identity is pinned, so admitting a superseded analysis widens
    /// nothing (the same rule as an analytic unit's).
    /// </summary>
    private IQueryable<PlateAnalysis> VisiblePlateAnalyses(string fingerprint, long snapshotVisibilitySequence) =>
        db.PlateAnalyses.AsNoTracking().Where(analysis =>
            analysis.IdentityFingerprint == fingerprint
            && (analysis.Status == PlateAnalysisStatus.Completed || analysis.Status == PlateAnalysisStatus.Superseded)
            && analysis.VisibilitySequence != null
            && analysis.VisibilitySequence <= snapshotVisibilitySequence);

    /// <summary>
    /// The Track texts that match literally. The text is <c>[A-Z0-9]</c> only and travels as a bound
    /// parameter: <c>LIKE '%T%'</c> for contains (served by the trigram index), <c>LIKE 'T%'</c> for
    /// prefix and equality for exact (served by the pattern b-tree).
    /// </summary>
    private IQueryable<PlateTrackText> MatchingTexts(TrackPlateQuery plate)
    {
        var texts = db.PlateTrackTexts.AsNoTracking();
        if (plate.Match == TrackPlateMatch.Exact)
        {
            var text = plate.Text;
            return texts.Where(row => row.NormalisedText == text);
        }

        var pattern = TrackPlateQueryRules.LikePattern(plate);
        return texts.Where(row => EF.Functions.Like(row.NormalisedText, pattern));
    }

    private IQueryable<TrackCandidate> WherePlateMatches(
        IQueryable<TrackCandidate> candidates,
        TrackPlateQuery plate,
        string fingerprint,
        long snapshotVisibilitySequence)
    {
        var texts = MatchingTexts(plate);
        var analyses = VisiblePlateAnalyses(fingerprint, snapshotVisibilitySequence);
        return candidates.Where(x => texts.Any(text =>
            text.TrackId == x.track.Id
            && analyses.Any(analysis => analysis.Id == text.AnalysisId && analysis.ProcessingRunId == x.run.Id)));
    }

    /// <summary>
    /// The bounded explanation for the rows of this page and no others: one query keyed on the page's
    /// Track ids. When several texts of a Track match, the best supported is shown — most support,
    /// then highest confidence, then ordinal text — deterministically.
    /// </summary>
    private async Task<IReadOnlyDictionary<Guid, TrackItemPlate>> ExplainPlatesAsync(
        IReadOnlyList<TrackSearchRow> rows,
        TrackPlateQuery plate,
        string fingerprint,
        long snapshotVisibilitySequence,
        CancellationToken cancellationToken)
    {
        var result = new Dictionary<Guid, TrackItemPlate>(rows.Count);
        if (rows.Count == 0)
            return result;

        var trackIds = rows.Select(row => row.Id).ToArray();
        var runIds = rows.Select(row => row.ProcessingRunId).Distinct().ToArray();
        var runByTrack = rows.ToDictionary(row => row.Id, row => row.ProcessingRunId);
        // Keyed run → analysis (the unique (run, identity) index) → texts (the (analysis, Track) key).
        var matches = await (
                from analysis in VisiblePlateAnalyses(fingerprint, snapshotVisibilitySequence)
                where runIds.Contains(analysis.ProcessingRunId)
                join text in MatchingTexts(plate) on analysis.Id equals text.AnalysisId
                join outcome in db.PlateTrackOutcomes.AsNoTracking()
                    on new { text.AnalysisId, text.TrackId } equals new { outcome.AnalysisId, outcome.TrackId }
                where trackIds.Contains(text.TrackId)
                select new
                {
                    text.TrackId,
                    analysis.ProcessingRunId,
                    text.NormalisedText,
                    text.SupportCount,
                    text.MaxConfidence,
                    text.BestPlateObservationId,
                    outcome.PlateObservationCount,
                    outcome.DistinctTextCount,
                })
            .ToListAsync(cancellationToken);

        foreach (var group in matches
                     .Where(match => runByTrack[match.TrackId] == match.ProcessingRunId)
                     .GroupBy(match => match.TrackId))
        {
            var best = group
                .OrderByDescending(match => match.SupportCount)
                .ThenByDescending(match => match.MaxConfidence)
                .ThenBy(match => match.NormalisedText, StringComparer.Ordinal)
                .First();
            result[group.Key] = new TrackItemPlate(
                best.NormalisedText,
                plate.Match,
                best.SupportCount,
                best.PlateObservationCount,
                best.DistinctTextCount,
                best.MaxConfidence,
                best.BestPlateObservationId);
        }

        // Every returned row matched by construction; a row without its explanation would mean the
        // page and the explanation read different worlds.
        if (result.Count != rows.Count)
            throw new InvalidOperationException("A plate search row has no matching Track text in its own snapshot.");
        return result;
    }

    // --- Coverage ----------------------------------------------------------------------------

    /// <summary>
    /// Plate coverage over the Vehicle Tracks of the base candidate scope (every ordinary filter and
    /// the latest-run scope, before the plate and analytic predicates): each run is classified once by
    /// the PR-3 readiness rule as of the snapshot, and its Tracks counted into that bucket.
    /// </summary>
    private async Task<TrackPlateCoverage> ComputePlateCoverageAsync(
        IQueryable<TrackCandidate> candidates,
        string? fingerprint,
        long snapshotVisibilitySequence,
        CancellationToken cancellationToken)
    {
        var tracksByRun = await candidates
            .Where(x => x.track.ObjectClass == Domain.Intelligence.ObjectClass.Vehicle)
            .GroupBy(x => x.run.Id)
            .Select(group => new { RunId = group.Key, Tracks = group.Count() })
            .ToListAsync(cancellationToken);
        var inScope = tracksByRun.Sum(run => run.Tracks);
        if (fingerprint is null)
            return new TrackPlateCoverage(null, inScope, 0, 0, 0, 0, inScope);
        if (tracksByRun.Count == 0)
            return TrackPlateCoverage.Empty(fingerprint);

        var runIds = tracksByRun.Select(run => run.RunId).ToArray();
        var analyses = (await db.PlateAnalyses.AsNoTracking()
                .Where(analysis => runIds.Contains(analysis.ProcessingRunId))
                .Select(analysis => new { analysis.Id, analysis.ProcessingRunId, analysis.IdentityFingerprint, analysis.Status, analysis.VisibilitySequence })
                .ToListAsync(cancellationToken))
            .ToLookup(analysis => analysis.ProcessingRunId);

        int ready = 0, pending = 0, failed = 0, stale = 0, notConfigured = 0;
        foreach (var run in tracksByRun)
        {
            var state = PlateCoverageRule.Classify(
                run.RunId,
                fingerprint,
                analyses[run.RunId]
                    .Select(analysis => new PlateCoverageAnalysis(analysis.Id, analysis.IdentityFingerprint, analysis.Status, analysis.VisibilitySequence))
                    .ToArray(),
                snapshotVisibilitySequence);
            switch (state)
            {
                case PlateReadinessState.Ready:
                    ready += run.Tracks;
                    break;
                case PlateReadinessState.Failed:
                    failed += run.Tracks;
                    break;
                case PlateReadinessState.Stale:
                    stale += run.Tracks;
                    break;
                case PlateReadinessState.NotConfigured:
                    notConfigured += run.Tracks;
                    break;
                default:
                    // Pending; NotApplicable cannot occur for a run with a Vehicle Track in scope.
                    pending += run.Tracks;
                    break;
            }
        }

        return new TrackPlateCoverage(fingerprint, inScope, ready, pending, failed, stale, notConfigured);
    }

    // --- Detail ------------------------------------------------------------------------------

    public async Task<TrackPlateFacts?> GetTrackPlateFactsAsync(
        Guid trackId,
        Guid analysisId,
        CancellationToken cancellationToken)
    {
        var header = await db.PlateAnalyses.AsNoTracking()
            .Where(analysis => analysis.Id == analysisId
                && (analysis.Status == PlateAnalysisStatus.Completed || analysis.Status == PlateAnalysisStatus.Superseded))
            .Select(analysis => new
            {
                analysis.Id,
                analysis.CapabilitiesCanonical,
                analysis.NormalisationId,
                analysis.NormalisationSha256,
                analysis.SummaryPolicyId,
                analysis.SummaryPolicyVersion,
                analysis.SummaryPolicySha256,
                analysis.CompletedAtUtc,
            })
            .SingleOrDefaultAsync(cancellationToken);
        if (header is null)
            return null;

        var outcome = await db.PlateTrackOutcomes.AsNoTracking()
            .Where(row => row.AnalysisId == analysisId && row.TrackId == trackId)
            .Select(row => new { row.Outcome, row.Reason })
            .SingleOrDefaultAsync(cancellationToken);

        var texts = await db.PlateTrackTexts.AsNoTracking()
            .Where(row => row.AnalysisId == analysisId && row.TrackId == trackId)
            .OrderByDescending(row => row.SupportCount)
            .ThenByDescending(row => row.MaxConfidence)
            .ThenBy(row => row.NormalisedText)
            .Select(row => new TrackPlateTextRow(row.NormalisedText, row.SupportCount, row.MaxConfidence, row.BestPlateObservationId))
            .ToListAsync(cancellationToken);

        var plates = await (
                from plate in db.PlateObservations.AsNoTracking()
                where plate.AnalysisId == analysisId && plate.TrackId == trackId
                join source in db.Observations.AsNoTracking() on plate.SourceObservationId equals source.Id
                orderby source.EvidenceRank, plate.PlateIndex, plate.Id
                select new
                {
                    plate.Id,
                    plate.SourceObservationId,
                    source.ObservationType,
                    source.EvidenceRank,
                    plate.PlateIndex,
                    source.VideoOffsetMs,
                    source.SourceFrameNumber,
                    source.TimestampUtc,
                    plate.BoxX,
                    plate.BoxY,
                    plate.BoxWidth,
                    plate.BoxHeight,
                    plate.CropWidth,
                    plate.CropHeight,
                    plate.DetectorConfidence,
                    plate.Outcome,
                })
            .ToListAsync(cancellationToken);

        var plateIds = plates.Select(plate => plate.Id).ToArray();
        var readings = plateIds.Length == 0
            ? []
            : await db.PlateReadings.AsNoTracking()
                .Where(reading => plateIds.Contains(reading.PlateObservationId))
                .OrderBy(reading => reading.PlateObservationId)
                .ThenBy(reading => reading.Rank)
                .ToListAsync(cancellationToken);
        var readingsByPlate = readings.ToLookup(reading => reading.PlateObservationId);

        var (detectorPack, ocrPack) = ModelPacks(header.CapabilitiesCanonical);
        return new TrackPlateFacts(
            outcome?.Outcome ?? PlateTrackOutcomeKind.Unavailable,
            outcome?.Reason,
            texts,
            plates.Select(plate => new TrackPlateObservationRow(
                    plate.Id,
                    plate.SourceObservationId,
                    plate.ObservationType,
                    plate.EvidenceRank,
                    plate.PlateIndex,
                    plate.VideoOffsetMs,
                    plate.SourceFrameNumber,
                    plate.TimestampUtc,
                    plate.BoxX,
                    plate.BoxY,
                    plate.BoxWidth,
                    plate.BoxHeight,
                    plate.CropWidth,
                    plate.CropHeight,
                    plate.DetectorConfidence,
                    plate.Outcome,
                    readingsByPlate[plate.Id]
                        .Select(reading => new TrackPlateReadingRow(
                            reading.Rank,
                            reading.RawText,
                            reading.RawLineCount,
                            reading.NormalisedText,
                            reading.NormalisationOutcome,
                            reading.Confidence,
                            reading.FormatClass))
                        .ToArray()))
                .ToArray(),
            new TrackPlateProvenance(
                header.Id,
                detectorPack,
                ocrPack,
                header.NormalisationId,
                header.NormalisationSha256,
                header.SummaryPolicyId,
                header.SummaryPolicyVersion,
                header.SummaryPolicySha256,
                header.CompletedAtUtc!.Value));
    }

    /// <summary>The two Model Pack ids of the identity's canonical capability list (its own encoding).</summary>
    private static (string PlateDetector, string Ocr) ModelPacks(string capabilitiesCanonical)
    {
        using var document = JsonDocument.Parse(capabilitiesCanonical);
        string? detector = null, ocr = null;
        foreach (var capability in document.RootElement.EnumerateArray())
        {
            var id = capability.GetProperty("capabilityId").GetString();
            var pack = capability.GetProperty("modelPackId").GetString();
            if (id == PlateContractRules.CapabilityOcr) ocr = pack;
            else if (id == PlateContractRules.CapabilityPlateDetector) detector = pack;
        }

        return (detector ?? throw new InvalidOperationException("The plate identity names no plate-detector pack."),
            ocr ?? throw new InvalidOperationException("The plate identity names no OCR pack."));
    }
}
