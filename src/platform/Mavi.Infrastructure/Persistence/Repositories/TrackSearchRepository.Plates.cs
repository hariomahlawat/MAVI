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

        var (plateCoverage, integrityFaults) = await ComputePlateCoverageAsync(
            query, preferredFingerprint, snapshotVisibilitySequence, cancellationToken);

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
        return new TrackPlateSearchRepositoryResult(page with { IntegrityFaults = integrityFaults });
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

        var (rows, _) = await PlatePageAsync(
            query, plate, fingerprint, snapshotVisibilitySequence, keyset, take,
            async (ids, from, count) => (
                await BuildQuery(query, snapshotVisibilitySequence, from, candidates => WhereTrackIn(candidates, ids))
                    .Take(count)
                    .ToArrayAsync(cancellationToken),
                (IReadOnlyDictionary<Guid, TrackItemAnalytics>?)null),
            cancellationToken);
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

        var (rows, itemAnalytics) = await PlatePageAsync(
            query, plate, fingerprint, snapshotVisibilitySequence, keyset, take,
            async (ids, from, count) =>
            {
                var (page, explained) = await FetchPageAsync(
                    query, analytics, identity, scope, snapshotVisibilitySequence, from, count, cancellationToken,
                    candidates => WhereTrackIn(candidates, ids));
                return (page, (IReadOnlyDictionary<Guid, TrackItemAnalytics>?)explained);
            },
            cancellationToken);
        var itemPlates = await ExplainPlatesAsync(rows, plate, fingerprint, snapshotVisibilitySequence, cancellationToken);
        return new TrackPlateSearchRepositoryPage(
            rows, snapshotUtc, snapshotVisibilitySequence, plateCoverage, itemPlates, identity, analyticsCoverage,
            itemAnalytics ?? new Dictionary<Guid, TrackItemAnalytics>());
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

    /// <summary>The first walk batch: also the density sample that chooses the strategy.</summary>
    internal int FirstWalkBatch { get; init; } = 256;

    /// <summary>The largest walk batch; batches double from <see cref="FirstWalkBatch"/> up to it.</summary>
    internal int MaximumWalkBatch { get; init; } = 4096;

    /// <summary>
    /// The most in-scope matching Track ids the sparse path may hold. A text with more matches in scope is
    /// paged by the walk instead, so no statement ever carries more than this many ids. Tests shrink these
    /// three to drive every path over a small corpus; production uses the defaults, fixed before measuring.
    /// </summary>
    internal int MaximumScopedMatchIds { get; init; } = 4096;

    private delegate Task<(IReadOnlyList<TrackSearchRow> Rows, IReadOnlyDictionary<Guid, TrackItemAnalytics>? Analytics)> RestrictedPage(
        Guid[] trackIds, TrackCursorPosition? keyset, int take);

    /// <summary>
    /// One page of a plate search, bounded by the page and the scope rather than by how many Tracks of the
    /// whole installation match (cold review P1-1; plan §2.8). Results and ordering are exactly those of the
    /// plate predicate ANDed with the base chain, ordered <c>StartTimestampUtc DESC, Id DESC</c>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// <b>Walk.</b> The scope's Tracks are read in page order from the keyset in batches (256, doubling to
    /// 4 096); each batch's Track ids are checked against the plate predicate in one keyed statement
    /// (run → analysis → (analysis, Track) text), and the matching ones go through the page's own query
    /// (every other predicate, keyset and order) restricted to them. It stops as soon as the page is full or
    /// the scope is exhausted, so a text common in the scope costs a few batches however many Tracks of the
    /// installation it matches.
    /// </para>
    /// <para>
    /// <b>Sparse path.</b> When the first batch holds no match, the text is rare where the page starts, and
    /// walking could read the whole scope. The plate predicate is then evaluated from the text index, but only
    /// over the scope's runs (<see cref="RunsInScope"/>) and capped at <see cref="MaximumScopedMatchIds"/>
    /// + 1 ids: within the cap those ids go through the page's own query; over it the text is common in
    /// scope after all and the walk continues. The id list is never the installation's.
    /// </para>
    /// <para>
    /// The strategy changes only cost: every path returns exactly the matching rows after the keyset, in
    /// page order. The constants are fixed before measurement and are not tuned to it.
    /// </para>
    /// </remarks>
    private async Task<(IReadOnlyList<TrackSearchRow> Rows, IReadOnlyDictionary<Guid, TrackItemAnalytics>? Analytics)> PlatePageAsync(
        TrackSearchQuery query,
        TrackPlateQuery plate,
        string fingerprint,
        long snapshotVisibilitySequence,
        TrackCursorPosition? keyset,
        int take,
        RestrictedPage restricted,
        CancellationToken cancellationToken)
    {
        var rows = new List<TrackSearchRow>(take);
        Dictionary<Guid, TrackItemAnalytics>? analytics = null;

        async Task AddAsync(Guid[] ids, TrackCursorPosition? from)
        {
            if (ids.Length == 0 || rows.Count >= take) return;
            var (page, explained) = await restricted(ids, from, take - rows.Count);
            rows.AddRange(page);
            if (explained is not null)
            {
                analytics ??= [];
                foreach (var (id, value) in explained) analytics[id] = value;
            }
        }

        var position = keyset;
        var batch = FirstWalkBatch;
        var sampled = false;
        while (rows.Count < take)
        {
            var chunk = await BuildQuery(query, snapshotVisibilitySequence, position)
                .Select(row => new { row.Id, row.StartTimestampUtc })
                .Take(batch)
                .ToArrayAsync(cancellationToken);
            if (chunk.Length == 0)
                break;

            var chunkIds = chunk.Select(row => row.Id).ToArray();
            var matched = await MatchingTrackIdsAmongAsync(plate, fingerprint, snapshotVisibilitySequence, chunkIds, cancellationToken);
            await AddAsync(matched, position);
            if (rows.Count >= take || chunk.Length < batch)
                break;

            var last = chunk[^1];
            var next = new TrackCursorPosition(DateTimeOffset.MinValue, snapshotVisibilitySequence, last.StartTimestampUtc, last.Id, string.Empty);

            if (!sampled)
            {
                sampled = true;
                if (matched.Length == 0)
                {
                    var runIds = await RunsInScope(query, snapshotVisibilitySequence).ToArrayAsync(cancellationToken);
                    var scoped = await ScopedMatchingTrackIdsAsync(plate, fingerprint, snapshotVisibilitySequence, runIds, cancellationToken);
                    if (scoped.Length <= MaximumScopedMatchIds)
                    {
                        await AddAsync(scoped, next);
                        break;
                    }
                }
            }

            position = next;
            batch = Math.Min(batch * 2, MaximumWalkBatch);
        }

        return (rows, analytics);
    }

    /// <summary>Which of these Tracks match the plate predicate under the pinned, snapshot-visible analysis of their own run.</summary>
    private Task<Guid[]> MatchingTrackIdsAmongAsync(
        TrackPlateQuery plate,
        string fingerprint,
        long snapshotVisibilitySequence,
        Guid[] trackIds,
        CancellationToken cancellationToken) =>
        (from track in db.Tracks.AsNoTracking()
         where trackIds.Contains(track.Id)
         join analysis in VisiblePlateAnalyses(fingerprint, snapshotVisibilitySequence) on track.ProcessingRunId equals analysis.ProcessingRunId
         join text in MatchingTexts(plate) on new { AnalysisId = analysis.Id, TrackId = track.Id } equals new { text.AnalysisId, text.TrackId }
         select track.Id)
        .Distinct()
        .ToArrayAsync(cancellationToken);

    /// <summary>
    /// The sparse path: matching Tracks of the scope's runs only, from the text index, at most
    /// <see cref="MaximumScopedMatchIds"/> + 1 (one more tells the caller the cap was exceeded).
    /// </summary>
    private Task<Guid[]> ScopedMatchingTrackIdsAsync(
        TrackPlateQuery plate,
        string fingerprint,
        long snapshotVisibilitySequence,
        Guid[] runIds,
        CancellationToken cancellationToken) =>
        (from text in MatchingTexts(plate)
         join analysis in VisiblePlateAnalyses(fingerprint, snapshotVisibilitySequence) on text.AnalysisId equals analysis.Id
         where runIds.Contains(analysis.ProcessingRunId)
         join track in db.Tracks.AsNoTracking() on text.TrackId equals track.Id
         where track.ProcessingRunId == analysis.ProcessingRunId
         select text.TrackId)
        .Distinct()
        .Take(MaximumScopedMatchIds + 1)
        .ToArrayAsync(cancellationToken);

    /// <summary>Step two: the base chain, every other filter, keyset and ordering, over those Tracks only.</summary>
    private static IQueryable<TrackCandidate> WhereTrackIn(IQueryable<TrackCandidate> candidates, Guid[] trackIds) =>
        candidates.Where(x => trackIds.Contains(x.track.Id));

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
    /// <summary>
    /// The authoritative Vehicle Track count of each completed, visible run, once read. A completed run's
    /// Tracks are immutable, so the count never changes; caching it is what keeps coverage off a 10^6-Track
    /// scan on every first page (measured ≈ 230–290 ms; plan §2.8). Bounded: cleared when it outgrows
    /// <see cref="MaximumCachedRunCounts"/>. It holds counts only, never a plate value.
    /// </summary>
    private static readonly System.Collections.Concurrent.ConcurrentDictionary<Guid, int> RunVehicleCounts = new();

    internal const int MaximumCachedRunCounts = 200_000;

    private async Task<(TrackPlateCoverage Coverage, IReadOnlyList<PlateCoverageIntegrityFault> Faults)> ComputePlateCoverageAsync(
        TrackSearchQuery query,
        string? fingerprint,
        long snapshotVisibilitySequence,
        CancellationToken cancellationToken)
    {
        var runIds = await RunsInScope(query, snapshotVisibilitySequence).ToArrayAsync(cancellationToken);
        if (runIds.Length == 0)
            return (TrackPlateCoverage.Empty(fingerprint), []);

        // Every count is the authoritative one — the scope's Vehicle Tracks per run, from the Tracks
        // themselves. Without a Track-level filter it is the run's whole Vehicle count, read once and cached;
        // with one, it is counted for this query. No analysis header is ever trusted as a count.
        var filtered = HasTrackLevelFilter(query);
        var counts = filtered
            ? (await VehicleTrackCounts(query, runIds).ToListAsync(cancellationToken)).ToDictionary(row => row.RunId, row => row.Tracks)
            : await RunVehicleCountsAsync(runIds, cancellationToken);
        if (fingerprint is null)
        {
            var all = counts.Values.Sum();
            return (new TrackPlateCoverage(null, all, 0, 0, 0, 0, all), []);
        }

        var analyses = (await db.PlateAnalyses.AsNoTracking()
                .Where(analysis => runIds.Contains(analysis.ProcessingRunId))
                .Select(analysis => new
                {
                    analysis.Id,
                    analysis.ProcessingRunId,
                    analysis.IdentityFingerprint,
                    analysis.Status,
                    analysis.VisibilitySequence,
                    Tracks = analysis.TracksAnalysed + analysis.TracksUnavailable,
                })
                .ToListAsync(cancellationToken))
            .ToLookup(analysis => analysis.ProcessingRunId);

        var faults = new List<PlateCoverageIntegrityFault>();
        int ready = 0, pending = 0, failed = 0, stale = 0, notConfigured = 0;
        foreach (var runId in runIds)
        {
            var tracks = counts.GetValueOrDefault(runId);
            if (tracks == 0) continue;
            var state = PlateCoverageRule.Classify(
                runId,
                fingerprint,
                analyses[runId]
                    .Select(analysis => new PlateCoverageAnalysis(analysis.Id, analysis.IdentityFingerprint, analysis.Status, analysis.VisibilitySequence))
                    .ToArray(),
                snapshotVisibilitySequence);
            if (state == PlateReadinessState.Ready && !filtered)
            {
                // A published analysis accounts for every Vehicle Track of its run (PR-3's completion
                // invariant). A header that disagrees with the Tracks is an integrity fault: the count used is
                // still the Tracks' own, and the fault is reported (ids and counts only).
                var pinned = analyses[runId].First(analysis => analysis.IdentityFingerprint == fingerprint);
                if (pinned.Tracks != tracks)
                    faults.Add(new PlateCoverageIntegrityFault(pinned.Id, runId, pinned.Tracks, tracks));
            }

            switch (state)
            {
                case PlateReadinessState.Ready:
                    ready += tracks;
                    break;
                case PlateReadinessState.Failed:
                    failed += tracks;
                    break;
                case PlateReadinessState.Stale:
                    stale += tracks;
                    break;
                case PlateReadinessState.NotConfigured:
                    notConfigured += tracks;
                    break;
                default:
                    // Pending; NotApplicable cannot occur for a run with a Vehicle Track in scope.
                    pending += tracks;
                    break;
            }
        }

        return (new TrackPlateCoverage(fingerprint, ready + pending + failed + stale + notConfigured, ready, pending, failed, stale, notConfigured),
            faults);
    }

    /// <summary>The whole Vehicle Track count of each run, from the cache or counted once for those not in it.</summary>
    private async Task<Dictionary<Guid, int>> RunVehicleCountsAsync(Guid[] runIds, CancellationToken cancellationToken)
    {
        var result = new Dictionary<Guid, int>(runIds.Length);
        var missing = new List<Guid>();
        foreach (var runId in runIds)
        {
            if (RunVehicleCounts.TryGetValue(runId, out var cached)) result[runId] = cached;
            else missing.Add(runId);
        }

        if (missing.Count == 0)
            return result;

        var missingIds = missing.ToArray();
        var counted = (await db.Tracks.AsNoTracking()
                .Where(track => track.ObjectClass == Domain.Intelligence.ObjectClass.Vehicle && missingIds.Contains(track.ProcessingRunId))
                .GroupBy(track => track.ProcessingRunId)
                .Select(group => new { RunId = group.Key, Tracks = group.Count() })
                .ToListAsync(cancellationToken))
            .ToDictionary(row => row.RunId, row => row.Tracks);
        if (RunVehicleCounts.Count + missingIds.Length > MaximumCachedRunCounts)
            RunVehicleCounts.Clear();
        foreach (var runId in missingIds)
        {
            var tracks = counted.GetValueOrDefault(runId);
            RunVehicleCounts[runId] = tracks;
            result[runId] = tracks;
        }

        return result;
    }

    private static bool HasTrackLevelFilter(TrackSearchQuery query) =>
        query.FromUtc is not null || query.ToUtc is not null || query.MinimumDurationMs is not null ||
        query.MinimumConfidence is not null || query.ObjectSubclass is not null;

    public sealed record RunTrackCount(Guid RunId, int Tracks);

    /// <summary>The Vehicle Tracks of the base candidate scope per run (<see cref="RunsInScope"/> then <see cref="VehicleTrackCounts"/>).</summary>
    internal async Task<List<RunTrackCount>> VehicleTracksByRunAsync(TrackSearchQuery query, long snapshotVisibilitySequence) =>
        await VehicleTrackCounts(query, await RunsInScope(query, snapshotVisibilitySequence).ToArrayAsync()).ToListAsync();

    /// <summary>
    /// The Vehicle Tracks of the base candidate scope, counted per run, without joining each Track to
    /// its run, video and camera. It is the same scope as <see cref="AnalyticsScopeQuery.BaseCandidates"/>
    /// decomposed into its two levels: the runs it admits (completed, visible inside the snapshot, the
    /// latest of their video, and the run, video and camera filters), and the Track-level filters over
    /// those runs' Tracks. Measured (plan §2.8): counting 10^6 Tracks through the per-Track joins and the
    /// per-Track latest-run anti-join cost ~435 ms; this shape scans the Tracks once. A test pins its
    /// counts to the base chain's for every filter.
    /// </summary>
    internal IQueryable<Guid> RunsInScope(TrackSearchQuery query, long snapshotVisibilitySequence)
    {
        var scope = AnalyticsScopeRequest.From(query);
        var visible = db.ProcessingRuns.AsNoTracking().Where(run =>
            run.Status == Domain.Processing.ProcessingRunStatus.Completed &&
            run.CompletedAtUtc != null &&
            run.VisibilitySequence != null &&
            run.VisibilitySequence <= snapshotVisibilitySequence);
        var runs =
            from run in visible
            join video in db.VideoAssets.AsNoTracking() on run.VideoAssetId equals video.Id
            select new { run, video };
        if (scope.ProcessingRunId is { } runId)
        {
            runs = runs.Where(x => x.run.Id == runId);
        }
        else
        {
            runs = runs.Where(x => !visible.Any(other =>
                other.VideoAssetId == x.video.Id && other.VisibilitySequence > x.run.VisibilitySequence));
        }

        if (scope.CameraId is { } cameraId)
            runs = runs.Where(x => x.video.CameraId == cameraId);
        if (scope.VideoAssetId is { } videoId)
            runs = runs.Where(x => x.video.Id == videoId);
        return runs.Select(x => x.run.Id);
    }

    /// <summary>The Track-level half: the Vehicle Tracks of the given runs that pass every Track filter, per run.</summary>
    internal IQueryable<RunTrackCount> VehicleTrackCounts(TrackSearchQuery query, Guid[] runIds)
    {
        var scope = AnalyticsScopeRequest.From(query);
        var tracks = db.Tracks.AsNoTracking().Where(track =>
            track.ObjectClass == Domain.Intelligence.ObjectClass.Vehicle && runIds.Contains(track.ProcessingRunId));
        if (scope.FromUtc is { } fromUtc)
            tracks = tracks.Where(track => track.EndTimestampUtc >= fromUtc);
        if (scope.ToUtc is { } toUtc)
            tracks = tracks.Where(track => track.StartTimestampUtc < toUtc);
        if (scope.MinimumDurationMs is { } minimumDurationMs)
            tracks = tracks.Where(track => track.DurationMs >= minimumDurationMs);
        if (scope.MinimumConfidence is { } minimumConfidence)
            tracks = tracks.Where(track => track.MeanConfidence >= minimumConfidence);
        if (scope.ObjectSubclass is { } subclass)
        {
            var approvedSource = VehicleSubclassExposurePolicy.ApprovedSource;
            tracks = tracks.Where(track => track.ObjectSubclass == subclass && track.ObjectSubclassSource == approvedSource);
        }

        return tracks
            .GroupBy(track => track.ProcessingRunId)
            .Select(group => new RunTrackCount(group.Key, group.Count()));
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
            // Null, never defaulted: a missing outcome is an integrity fault the caller reports and logs.
            outcome?.Outcome,
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
