using Mavi.Contracts.Api.Analytics;
using Mavi.Contracts.Api.Tracks;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>The outcome of a search, in the endpoint's terms.</summary>
/// <remarks>
/// <paramref name="Coverage"/> accompanies <see cref="IncompleteCoverage"/>: a caller
/// that demanded complete coverage is told exactly which buckets were not evaluated, in
/// the same structured block a partial answer would have carried (plan §H).
/// </remarks>
public sealed record TrackSearchServiceResult(
    bool IsSuccess,
    TrackSearchPage? Page,
    string? ErrorCode,
    TrackAnalyticsCoverage? Coverage = null)
{
    public static TrackSearchServiceResult Success(TrackSearchPage page) => new(true, page, null);
    public static TrackSearchServiceResult Invalid() => new(false, null, "track_search_invalid");
    public static TrackSearchServiceResult IncompleteCoverage(TrackAnalyticsCoverage coverage) =>
        new(false, null, SceneAnalyticsContractRules.IncompleteCoverageCode, coverage);
}

/// <summary>A Track's detail, with its analytics for the requested identity.</summary>
public sealed record TrackDetailServiceResult(
    bool IsSuccess,
    TrackDetailRow? Row,
    TrackEvidenceSet? EvidenceSet,
    TrackDetailAnalytics? Analytics,
    string? ErrorCode)
{
    public static TrackDetailServiceResult NotFound { get; } = new(true, null, null, null, null);
    public static TrackDetailServiceResult Invalid { get; } = new(false, null, null, null, "track_search_invalid");
    public static TrackDetailServiceResult Found(
        TrackDetailRow row,
        TrackEvidenceSet evidenceSet,
        TrackDetailAnalytics analytics) =>
        new(true, row, evidenceSet, analytics, null);
}

/// <summary>Track search and detail.</summary>
/// <remarks>
/// The plate collaborators (Stage 4) are optional so that a host without the plate plane — and the
/// pre-Stage-4 unit tests — construct the service exactly as before. Without them a plate query is a
/// programming error, never a silently empty result, and the detail carries no <c>plates</c> block.
/// </remarks>
public sealed class TrackSearchService(
    ITrackSearchRepository repository,
    TimeProvider timeProvider,
    TrackCursorSigningKey signingKey,
    ITrackPlateSearchRepository? plateRepository = null,
    Plates.IPlateRelease? plateRelease = null,
    Plates.PlateReadinessService? plateReadiness = null)
{
    private static readonly TimeSpan MaximumCursorAge = TimeSpan.FromHours(1);
    private static readonly TimeSpan MaximumFutureSkew = TimeSpan.FromMinutes(1);

    public async Task<TrackSearchServiceResult> SearchAsync(
        TrackSearchQuery query,
        CancellationToken cancellationToken)
    {
        if (!IsValid(query))
            return TrackSearchServiceResult.Invalid();

        // One semantic search, one fingerprint, one repository query.
        query = query.Canonical;

        var nowUtc = timeProvider.GetUtcNow().ToUniversalTime();
        if (query.IsPlate)
            return await SearchPlateAsync(query, nowUtc, cancellationToken);
        if (query.IsAnalytic)
            return await SearchAnalyticAsync(query, nowUtc, cancellationToken);

        var filterFingerprint = TrackCursorCodec.ComputeFilterFingerprint(query);

        TrackCursorPosition? cursor = null;
        if (query.Cursor is not null)
        {
            if (!TrackCursorCodec.TryDecode(query.Cursor, out cursor) ||
                cursor is null ||
                !string.Equals(
                    cursor.FilterFingerprint,
                    filterFingerprint,
                    StringComparison.Ordinal) ||
                !IsWithinValidity(cursor.SnapshotUtc, nowUtc))
            {
                return TrackSearchServiceResult.Invalid();
            }
        }

        var repositoryPage = await repository.SearchAsync(
            query,
            cursor,
            checked(query.Limit + 1),
            cancellationToken);
        var snapshotUtc = repositoryPage.SnapshotUtc;
        var snapshotVisibilitySequence = repositoryPage.SnapshotVisibilitySequence;
        var rows = repositoryPage.Items;

        var hasMore = rows.Count > query.Limit;
        var items = hasMore ? rows.Take(query.Limit).ToArray() : rows;
        var nextCursor = hasMore && items.Count > 0
            ? TrackCursorCodec.Encode(new TrackCursorPosition(
                snapshotUtc,
                snapshotVisibilitySequence,
                items[^1].StartTimestampUtc,
                items[^1].Id,
                filterFingerprint))
            : null;

        return TrackSearchServiceResult.Success(new TrackSearchPage(items, nextCursor));
    }

    /// <summary>
    /// An analytics-dependent search (plan §S). The first page lets the repository resolve
    /// the identity as one operation and then fingerprints the canonical keys <i>plus</i>
    /// that identity into a v3 cursor; a continuation authenticates the cursor, checks the
    /// fingerprint against the pinned pair and evaluates as pinned.
    /// </summary>
    private async Task<TrackSearchServiceResult> SearchAnalyticAsync(
        TrackSearchQuery query,
        DateTimeOffset nowUtc,
        CancellationToken cancellationToken)
    {
        TrackAnalyticsCursorPosition? cursor = null;
        if (query.Cursor is not null)
        {
            // Authenticated before anything in it is read; the codec refuses a forged or
            // tampered envelope without parsing it.
            if (!TrackCursorCodec.TryDecodeAnalytic(query.Cursor, signingKey, out cursor) ||
                cursor is null ||
                !IsWithinValidity(cursor.Position.SnapshotUtc, nowUtc) ||
                !string.Equals(
                    cursor.Position.FilterFingerprint,
                    TrackCursorCodec.ComputeAnalyticFilterFingerprint(query, cursor.Identity),
                    StringComparison.Ordinal))
            {
                return TrackSearchServiceResult.Invalid();
            }
        }

        var result = await repository.SearchAnalyticsAsync(
            query,
            cursor,
            checked(query.Limit + 1),
            cancellationToken);
        if (result.Page is not { } page)
            return TrackSearchServiceResult.Invalid();

        // The complete-coverage demand is judged on the first page, where coverage is
        // computed; a continuation carries the same block and the same verdict.
        if (query.Analytics!.RequireCompleteCoverage && !page.Coverage.Complete)
            return TrackSearchServiceResult.IncompleteCoverage(page.Coverage);

        var fingerprint = cursor?.Position.FilterFingerprint
            ?? TrackCursorCodec.ComputeAnalyticFilterFingerprint(query, page.Identity);

        var hasMore = page.Items.Count > query.Limit;
        var items = hasMore ? page.Items.Take(query.Limit).ToArray() : page.Items;
        var nextCursor = hasMore && items.Count > 0
            ? TrackCursorCodec.EncodeAnalytic(
                new TrackAnalyticsCursorPosition(
                    new TrackCursorPosition(
                        page.SnapshotUtc,
                        page.SnapshotVisibilitySequence,
                        items[^1].StartTimestampUtc,
                        items[^1].Id,
                        fingerprint),
                    page.Identity,
                    page.Coverage),
                signingKey)
            : null;

        return TrackSearchServiceResult.Success(new TrackSearchPage(items, nextCursor, page.Coverage, page.ItemAnalytics));
    }

    /// <summary>
    /// A search carrying a plate predicate (plan §5.4), alone or with analytic predicates. The first
    /// page pins the release's preferred plate identity (null when plates are not configured: nothing
    /// can match, and coverage says why); a continuation authenticates the v4 cursor, checks its
    /// fingerprint against the pinned identities and evaluates as pinned, never re-resolving the
    /// release.
    /// </summary>
    private async Task<TrackSearchServiceResult> SearchPlateAsync(
        TrackSearchQuery query,
        DateTimeOffset nowUtc,
        CancellationToken cancellationToken)
    {
        if (plateRepository is null)
            throw new InvalidOperationException("Plate search is not wired into this host.");

        TrackPlateCursorPosition? cursor = null;
        if (query.Cursor is not null)
        {
            if (!TrackCursorCodec.TryDecodePlate(query.Cursor, signingKey, out cursor) ||
                cursor is null ||
                cursor.IsAnalytic != query.IsAnalytic ||
                !IsWithinValidity(cursor.Position.SnapshotUtc, nowUtc) ||
                !string.Equals(
                    cursor.Position.FilterFingerprint,
                    TrackCursorCodec.ComputePlateFilterFingerprint(query, cursor.PlateIdentityFingerprint, cursor.AnalyticsIdentity, signingKey),
                    StringComparison.Ordinal))
            {
                return TrackSearchServiceResult.Invalid();
            }
        }

        var preferred = cursor?.PlateIdentityFingerprint ?? plateRelease?.Resolution.Definition?.Identity.Fingerprint;
        var result = await plateRepository.SearchPlatesAsync(
            query,
            preferred,
            cursor,
            checked(query.Limit + 1),
            cancellationToken);
        if (result.Page is not { } page)
            return TrackSearchServiceResult.Invalid();

        if (query.Analytics is { RequireCompleteCoverage: true } && page.AnalyticsCoverage is { Complete: false } incomplete)
            return TrackSearchServiceResult.IncompleteCoverage(incomplete);

        var hasMore = page.Items.Count > query.Limit;
        var items = hasMore ? page.Items.Take(query.Limit).ToArray() : page.Items;
        string? nextCursor = null;
        if (hasMore && items.Count > 0)
        {
            // A row can match only under a pinned identity, so a page with rows always has one.
            var plateFingerprint = page.PlateCoverage.IdentityFingerprint
                ?? throw new InvalidOperationException("A plate match was returned without a plate identity.");
            var fingerprint = cursor?.Position.FilterFingerprint
                ?? TrackCursorCodec.ComputePlateFilterFingerprint(query, plateFingerprint, page.AnalyticsIdentity, signingKey);
            nextCursor = TrackCursorCodec.EncodePlate(
                new TrackPlateCursorPosition(
                    new TrackCursorPosition(
                        page.SnapshotUtc,
                        page.SnapshotVisibilitySequence,
                        items[^1].StartTimestampUtc,
                        items[^1].Id,
                        fingerprint),
                    plateFingerprint,
                    page.PlateCoverage,
                    page.AnalyticsIdentity,
                    page.AnalyticsCoverage),
                signingKey);
        }

        return TrackSearchServiceResult.Success(new TrackSearchPage(
            items,
            nextCursor,
            page.AnalyticsCoverage,
            page.ItemAnalytics,
            page.PlateCoverage,
            page.ItemPlates));
    }

    /// <summary>
    /// A Vehicle Track's plate detail (plan §5.4): its run's readiness by the PR-3 rule and, when
    /// Ready, the default analysis's facts. Null for a Person Track, or when the host has no plate
    /// plane wired.
    /// </summary>
    public async Task<TrackPlateDetail?> GetPlateDetailAsync(TrackDetailRow row, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(row);
        if (row.ObjectClass != Domain.Intelligence.ObjectClass.Vehicle || plateReadiness is null || plateRepository is null)
            return null;

        var readiness = await plateReadiness.GetAsync(row.ProcessingRunId, cancellationToken);
        if (readiness is null)
            return null;
        if (readiness.State != Domain.Plates.PlateReadinessState.Ready || readiness.DefaultAnalysisId is not { } analysisId)
            return new TrackPlateDetail(readiness.State, null);

        var facts = await plateRepository.GetTrackPlateFactsAsync(row.Id, analysisId, cancellationToken);
        return new TrackPlateDetail(readiness.State, facts);
    }

    public async Task<TrackDetailServiceResult> GetDetailAsync(
        Guid trackId,
        TrackAnalyticsDetailRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (trackId == Guid.Empty)
            return TrackDetailServiceResult.NotFound;

        // The same dependency the search grammar imposes: a historical engine version
        // means nothing without the revision it was computed against.
        if (request.SceneRevisionId == Guid.Empty ||
            (request.AlgorithmVersion is { } version &&
             (request.SceneRevisionId is null || !TrackSearchContractRules.IsAlgorithmVersion(version))))
            return TrackDetailServiceResult.Invalid;

        var row = await repository.GetDetailAsync(trackId, cancellationToken);
        if (row is null)
            return TrackDetailServiceResult.NotFound;

        var analytics = await repository.GetDetailAnalyticsAsync(trackId, request, cancellationToken);
        if (analytics is null)
            return TrackDetailServiceResult.NotFound;
        if (analytics.Analytics is not { } resolved)
            return TrackDetailServiceResult.Invalid;

        // The raw Evidence Set: the second of the two bounded raw-evidence reads. It is
        // read only once the request is known to be answerable, so every 404 and 400 stays
        // exactly what it was. A completed run's Observations are immutable and committed
        // with its completion, so no transaction is needed. A persisted set that breaks the
        // contract throws TrackEvidenceSetInvariantException here; nothing is repaired or
        // dropped.
        var evidenceSet = TrackEvidenceSet.FromPersisted(
            row.RepresentativeObservationId,
            await repository.GetEvidenceSetAsync(trackId, cancellationToken));

        return TrackDetailServiceResult.Found(row, evidenceSet, resolved);
    }

    private static bool IsWithinValidity(DateTimeOffset snapshotUtc, DateTimeOffset nowUtc) =>
        snapshotUtc >= nowUtc - MaximumCursorAge && snapshotUtc <= nowUtc + MaximumFutureSkew;

    private static bool IsValid(TrackSearchQuery query)
    {
        if (query.Limit is < 1 or > 100 ||
            query.CameraId == Guid.Empty ||
            query.VideoAssetId == Guid.Empty ||
            query.ProcessingRunId == Guid.Empty ||
            query.MinimumDurationMs is < 0)
            return false;

        if (query.MinimumConfidence is { } confidence &&
            (!double.IsFinite(confidence) || confidence is < 0 or > 1))
            return false;

        if ((query.FromUtc is { } fromValue && fromValue.Offset != TimeSpan.Zero) ||
            (query.ToUtc is { } toValue && toValue.Offset != TimeSpan.Zero))
            return false;

        if (query.FromUtc is { } from &&
            query.ToUtc is { } to &&
            from >= to)
            return false;

        if (query.Analytics is { } analytics && !TrackAnalyticsQueryRules.IsValid(analytics))
            return false;

        // Only an operator-facing subclass may be searched for, and only among Vehicles:
        // a hidden value is refused, never coerced to an empty result.
        if (query.ObjectSubclass is { } subclass &&
            (!VehicleSubclassExposurePolicy.IsExposable(subclass) ||
             (query.ObjectClass is { } objectClass && objectClass != Domain.Intelligence.ObjectClass.Vehicle)))
            return false;

        // A plate text is read only from Vehicle Tracks, and only a normalised 3–15 character text
        // can be searched: a Person class or an unnormalised text is refused, never an empty page.
        if (query.Plate is { } plate &&
            ((query.ObjectClass is { } plateClass && plateClass != Domain.Intelligence.ObjectClass.Vehicle) ||
             !TrackPlateQueryRules.TryNormalise(plate.Text, out var normalised) ||
             !string.Equals(normalised, plate.Text, StringComparison.Ordinal) ||
             !Enum.IsDefined(plate.Match)))
            return false;

        return true;
    }
}
