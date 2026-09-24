using System.Globalization;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Analytics;
using Mavi.Contracts.Api.Tracks;
using Mavi.Domain.Intelligence;
using Mavi.Domain.SceneAnalytics;

namespace Mavi.Api.Endpoints;

public static partial class TrackEndpoints
{
    public static IEndpointRouteBuilder MapTrackEndpoints(this IEndpointRouteBuilder endpoints)
    {
        var tracks = endpoints.MapGroup("/api/tracks");
        tracks.MapGet("/", SearchAsync);
        tracks.MapGet("/{id:guid}", GetAsync);
        return endpoints;
    }

    private static async Task<IResult> SearchAsync(
        HttpContext context,
        TrackSearchService service,
        CancellationToken cancellationToken)
    {
        if (!TryParseQuery(context.Request.Query, out var query))
            return Problem(400, "track_search_invalid", "Track search parameters are invalid.");

        var result = await service.SearchAsync(query!, cancellationToken);
        if (!result.IsSuccess)
        {
            // A caller that demanded complete coverage is told, in the same structured
            // block a partial answer carries, exactly which runs went unevaluated (plan §H).
            if (result.Coverage is { } incomplete)
                return Results.Problem(
                    statusCode: 409,
                    detail: "Analytics coverage is incomplete for this search scope.",
                    extensions: new Dictionary<string, object?>
                    {
                        ["code"] = result.ErrorCode,
                        ["analyticsCoverage"] = ToCoverage(incomplete),
                    });
            return Problem(400, result.ErrorCode!, "Track search parameters are invalid.");
        }

        var page = result.Page!;
        var response = new TrackSearchResponse(
            page.Items.Select(row => ToSearchItem(row, page.ItemAnalytics)).ToArray(),
            page.NextCursor,
            page.Coverage is { } coverage ? ToCoverage(coverage) : null);
        return Results.Ok(response);
    }

    private static readonly HashSet<string> SupportedDetailQueryKeys =
        new(StringComparer.Ordinal)
        {
            TrackSearchContractRules.SceneRevisionIdKey,
            TrackSearchContractRules.AnalyticsAlgorithmVersionKey,
        };

    private static async Task<IResult> GetAsync(
        Guid id,
        HttpContext context,
        TrackSearchService service,
        ILoggerFactory loggerFactory,
        CancellationToken cancellationToken)
    {
        // The detail accepts the two identity keys and nothing else, so a link out of a
        // historical analytic search reads the facts that search was showing (plan §S).
        var values = context.Request.Query;
        if (values.Keys.Any(key => !SupportedDetailQueryKeys.Contains(key)) ||
            !TryGuid(values, TrackSearchContractRules.SceneRevisionIdKey, out var revisionId) ||
            !SingleOrMissing(values, TrackSearchContractRules.AnalyticsAlgorithmVersionKey, out var version))
            return Problem(400, "track_search_invalid", "Track detail parameters are invalid.");

        TrackDetailServiceResult result;
        try
        {
            result = await service.GetDetailAsync(
                id,
                new TrackAnalyticsDetailRequest(revisionId, version),
                cancellationToken);
        }
        catch (TrackEvidenceSetInvariantException exception)
        {
            // Persisted evidence that breaks the Evidence Set contract is an integrity
            // failure of the platform's own data: a 500, never a 404 or a 400, and never a
            // repaired or partial answer (S1.3 plan §5.3). The client gets no detail; the
            // violated rule is logged for the operator.
            LogEvidenceIntegrityFailure(
                loggerFactory.CreateLogger(typeof(TrackEndpoints).FullName!),
                id,
                exception.Invariant);
            return Problem(
                StatusCodes.Status500InternalServerError,
                "track_evidence_integrity_failure",
                "The Track's persisted evidence is invalid.");
        }

        if (!result.IsSuccess)
            return Problem(400, result.ErrorCode!, "Track detail parameters are invalid.");
        return result.Row is null
            ? Problem(404, "track_not_found", "Track was not found.")
            : Results.Ok(ToDetail(result.Row, result.EvidenceSet!, result.Analytics!));
    }

    private static readonly HashSet<string> SupportedQueryKeys =
        new(StringComparer.Ordinal)
        {
            "cameraId",
            "videoAssetId",
            "processingRunId",
            "objectClass",
            "fromUtc",
            "toUtc",
            "minimumDurationMs",
            "minimumConfidence",
            "cursor",
            "limit",
            // Slice 4 analytics grammar (plan §S). The whitelist is closed: a key not
            // named here is a 400, as it always was.
            TrackSearchContractRules.SceneRevisionIdKey,
            TrackSearchContractRules.AnalyticsAlgorithmVersionKey,
            TrackSearchContractRules.ZoneIdKey,
            TrackSearchContractRules.ZoneRelationKey,
            TrackSearchContractRules.MinDwellMsKey,
            TrackSearchContractRules.LineIdKey,
            TrackSearchContractRules.CrossingDirectionKey,
            TrackSearchContractRules.MotionDirectionKey,
            TrackSearchContractRules.MinStationaryMsKey,
            TrackSearchContractRules.LoiteringKey,
            TrackSearchContractRules.AnalyticsCoverageKey,
        };

    private static bool TryParseQuery(
        IQueryCollection values,
        out TrackSearchQuery? query)
    {
        query = null;
        if (values.Keys.Any(key => !SupportedQueryKeys.Contains(key)))
            return false;

        if (!TryGuid(values, "cameraId", out var cameraId) ||
            !TryGuid(values, "videoAssetId", out var videoId) ||
            !TryGuid(values, "processingRunId", out var runId) ||
            !TryObjectClass(values, out var objectClass) ||
            !TryUtc(values, "fromUtc", out var fromUtc) ||
            !TryUtc(values, "toUtc", out var toUtc) ||
            !TryLong(values, "minimumDurationMs", out var duration) ||
            !TryDouble(values, "minimumConfidence", out var confidence) ||
            !TryInt(values, "limit", 50, out var limit) ||
            !SingleOrMissing(values, "cursor", out var cursor) ||
            !TryAnalytics(values, out var analytics))
            return false;

        query = new TrackSearchQuery(
            cameraId,
            videoId,
            runId,
            objectClass,
            fromUtc,
            toUtc,
            duration,
            confidence,
            cursor,
            limit,
            analytics);
        return true;
    }

    /// <summary>
    /// The analytic half of the query, or null when no analytics-dependent key was
    /// supplied. Syntax only: each value must be well-formed and in its closed
    /// vocabulary. The dependency matrix between keys is the Application's rule
    /// (<see cref="TrackAnalyticsQueryRules.IsValid"/>), applied by the service.
    /// </summary>
    private static bool TryAnalytics(IQueryCollection values, out TrackAnalyticsQuery? analytics)
    {
        analytics = null;
        if (!TryGuid(values, TrackSearchContractRules.SceneRevisionIdKey, out var revisionId) ||
            !SingleOrMissing(values, TrackSearchContractRules.AnalyticsAlgorithmVersionKey, out var version) ||
            !TryGuid(values, TrackSearchContractRules.ZoneIdKey, out var zoneId) ||
            !SingleOrMissing(values, TrackSearchContractRules.ZoneRelationKey, out var relationRaw) ||
            !TryLong(values, TrackSearchContractRules.MinDwellMsKey, out var minDwellMs) ||
            !TryGuid(values, TrackSearchContractRules.LineIdKey, out var lineId) ||
            !SingleOrMissing(values, TrackSearchContractRules.CrossingDirectionKey, out var directionRaw) ||
            !SingleOrMissing(values, TrackSearchContractRules.MotionDirectionKey, out var heading) ||
            !TryLong(values, TrackSearchContractRules.MinStationaryMsKey, out var minStationaryMs) ||
            !SingleOrMissing(values, TrackSearchContractRules.LoiteringKey, out var loiteringRaw) ||
            !SingleOrMissing(values, TrackSearchContractRules.AnalyticsCoverageKey, out var coverageRaw))
            return false;

        if (version is not null && !TrackSearchContractRules.IsAlgorithmVersion(version))
            return false;

        TrackZoneRelation? relation = null;
        if (relationRaw is not null)
        {
            if (!TrackAnalyticsQueryRules.TryParseZoneRelation(relationRaw, out var parsedRelation))
                return false;
            relation = parsedRelation;
        }

        TrackCrossingDirection? direction = null;
        if (directionRaw is not null)
        {
            if (!TrackAnalyticsQueryRules.TryParseCrossingDirection(directionRaw, out var parsedDirection))
                return false;
            direction = parsedDirection;
        }

        if (heading is not null && !TrackSearchContractRules.IsMotionDirection(heading))
            return false;

        // Only `true`; false is represented by omission, so `loitering=false` is a
        // malformed request rather than a no-op.
        if (loiteringRaw is not null &&
            !string.Equals(loiteringRaw, TrackSearchContractRules.LoiteringTrue, StringComparison.Ordinal))
            return false;

        if (coverageRaw is not null && !TrackSearchContractRules.IsCoverageMode(coverageRaw))
            return false;

        var candidate = new TrackAnalyticsQuery(
            revisionId,
            version,
            zoneId,
            relation,
            minDwellMs,
            lineId,
            direction,
            heading,
            minStationaryMs,
            loiteringRaw is not null,
            string.Equals(coverageRaw, TrackSearchContractRules.CompleteCoverageMode, StringComparison.Ordinal));

        if (!candidate.HasAnalyticsDependentKey)
        {
            // Either value of the control flag without a dependent key is a rejection,
            // not a silent promotion to an analytic query (plan §S).
            return coverageRaw is null;
        }

        analytics = candidate;
        return true;
    }

    private static bool TryGuid(
        IQueryCollection values,
        string key,
        out Guid? result)
    {
        result = null;
        if (!SingleOrMissing(values, key, out var raw))
            return false;
        if (raw is null)
            return true;
        if (!Guid.TryParse(raw, out var value) || value == Guid.Empty)
            return false;
        result = value;
        return true;
    }

    private static bool TryObjectClass(
        IQueryCollection values,
        out ObjectClass? result)
    {
        result = null;
        if (!SingleOrMissing(values, "objectClass", out var raw))
            return false;
        if (raw is null)
            return true;
        if (!Enum.TryParse<ObjectClass>(raw, ignoreCase: true, out var value) ||
            !Enum.IsDefined(value) ||
            !string.Equals(raw, value.ToString(), StringComparison.OrdinalIgnoreCase))
            return false;
        result = value;
        return true;
    }

    private static bool TryUtc(
        IQueryCollection values,
        string key,
        out DateTimeOffset? result)
    {
        result = null;
        if (!SingleOrMissing(values, key, out var raw))
            return false;
        if (raw is null)
            return true;

        var explicitUtc =
            raw.Contains('T') &&
            (raw.EndsWith('Z') ||
             raw.EndsWith("+00:00", StringComparison.Ordinal));
        if (!explicitUtc ||
            !DateTimeOffset.TryParse(
                raw,
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                out var value) ||
            value.Offset != TimeSpan.Zero)
            return false;
        result = value;
        return true;
    }

    private static bool TryLong(
        IQueryCollection values,
        string key,
        out long? result)
    {
        result = null;
        if (!SingleOrMissing(values, key, out var raw))
            return false;
        if (raw is null)
            return true;
        if (!long.TryParse(raw, NumberStyles.None, CultureInfo.InvariantCulture, out var value))
            return false;
        result = value;
        return true;
    }

    private static bool TryDouble(
        IQueryCollection values,
        string key,
        out double? result)
    {
        result = null;
        if (!SingleOrMissing(values, key, out var raw))
            return false;
        if (raw is null)
            return true;
        if (!double.TryParse(
                raw,
                NumberStyles.AllowDecimalPoint,
                CultureInfo.InvariantCulture,
                out var value))
            return false;
        result = value;
        return true;
    }

    private static bool TryInt(
        IQueryCollection values,
        string key,
        int defaultValue,
        out int result)
    {
        result = defaultValue;
        if (!SingleOrMissing(values, key, out var raw))
            return false;
        if (raw is null)
            return true;
        return int.TryParse(raw, NumberStyles.None, CultureInfo.InvariantCulture, out result);
    }

    private static bool SingleOrMissing(
        IQueryCollection values,
        string key,
        out string? value)
    {
        value = null;
        if (!values.TryGetValue(key, out var raw))
            return true;
        if (raw.Count != 1 || string.IsNullOrWhiteSpace(raw[0]))
            return false;
        value = raw[0];
        return true;
    }

    private static TrackSearchItemResponse ToSearchItem(
        TrackSearchRow row,
        IReadOnlyDictionary<Guid, TrackItemAnalytics>? itemAnalytics) => new(
        row.Id,
        row.ProcessingRunId,
        row.VideoAssetId,
        row.CameraId,
        row.CameraCode,
        row.CameraName,
        row.ObjectClass.ToString(),
        row.StartTimestampUtc,
        row.EndTimestampUtc,
        row.StartOffsetMs,
        row.EndOffsetMs,
        row.DurationMs,
        row.DetectionCount,
        row.MeanConfidence,
        row.MaxConfidence,
        row.ReviewStatus.ToString(),
        row.ThumbnailArtifactId,
        row.ThumbnailArtifactId is { } thumbnailId
            ? $"/api/artifacts/{thumbnailId:D}/content"
            : null,
        $"/api/videos/{row.VideoAssetId:D}/content",
        itemAnalytics is not null && itemAnalytics.TryGetValue(row.Id, out var explained)
            ? ToItemAnalytics(explained)
            : null);

    // --- Analytics mapping -------------------------------------------------

    private static AnalyticsCoverageResponse ToCoverage(TrackAnalyticsCoverage coverage) => new(
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

    private static TrackItemAnalyticsResponse ToItemAnalytics(TrackItemAnalytics analytics) => new(
        analytics.SceneRevisionId,
        analytics.AlgorithmVersion,
        analytics.Zones.Select(zone => new TrackItemZoneAnalyticsResponse(
            zone.ZoneId, zone.VisitCount, zone.TotalDwellMs, zone.Loitering)).ToArray(),
        analytics.Lines.Select(line => new TrackItemLineAnalyticsResponse(
            line.LineId,
            line.CrossingCount,
            line.MatchedDirection is { } direction ? TrackAnalyticsQueryRules.PersistedDirectionToWire(direction) : null,
            line.FirstMatchedCrossingUtc)).ToArray(),
        analytics.Motion is { } motion
            ? new TrackItemMotionAnalyticsResponse(motion.Heading, motion.LongestStationaryMs)
            : null);

    private static TrackDetailAnalyticsResponse ToDetailAnalytics(TrackDetailAnalytics analytics) => new(
        analytics.SceneRevisionId,
        analytics.SceneRevisionNumber,
        analytics.AlgorithmVersion,
        analytics.Status,
        analytics.Outcome?.Reason,
        analytics.Outcome?.ReferencePoint,
        analytics.Outcome is { Outcome: TrackAnalysisOutcomeKind.Analysed } analysed ? analysed.SampleCount : null,
        analytics.Outcome is { Outcome: TrackAnalysisOutcomeKind.Analysed } analysedGaps ? analysedGaps.GapCount : null,
        analytics.Outcome is { Outcome: TrackAnalysisOutcomeKind.Analysed } analysedTotal ? analysedTotal.GapTotalMs : null,
        analytics.ZoneSummaries.Select(summary => new TrackDetailZoneSummaryResponse(
            summary.ZoneId,
            summary.VisitCount,
            summary.TotalDwellMs,
            summary.FirstEntryTimestampUtc,
            summary.LastExitTimestampUtc,
            summary.Loitering,
            summary.LoiteringThresholdSeconds,
            summary.LoiteringDwellMs)).ToArray(),
        analytics.ZoneVisits.Select(visit => new TrackDetailZoneVisitResponse(
            visit.ZoneId,
            visit.VisitIndex,
            visit.EntryOffsetMs,
            visit.ExitOffsetMs,
            visit.EntryTimestampUtc,
            visit.ExitTimestampUtc,
            visit.DwellMs,
            visit.BeganInside,
            visit.EndedInside,
            visit.ClosedByGap,
            visit.EntryHeading,
            visit.ExitHeading)).ToArray(),
        analytics.LineCrossings.Select(crossing => new TrackDetailLineCrossingResponse(
            crossing.LineId,
            crossing.CrossingIndex,
            crossing.OffsetMs,
            crossing.TimestampUtc,
            TrackAnalyticsQueryRules.PersistedDirectionToWire(crossing.Direction),
            crossing.PointX,
            crossing.PointY)).ToArray(),
        analytics.MotionSummary is { } motion
            ? new TrackDetailMotionSummaryResponse(
                motion.Heading,
                motion.PathLengthNormalised,
                motion.MeanDisplacementRate,
                motion.LongestStationaryMs,
                motion.TotalStationaryMs,
                motion.StationaryIntervals.Select(interval => new TrackStationaryIntervalResponse(
                    interval.StartOffsetMs, interval.EndOffsetMs)).ToArray(),
                motion.StationaryZoneIds)
            : null,
        analytics.OtherIdentities.Select(other => new TrackAnalyticsIdentitySummaryResponse(
            other.SceneRevisionId,
            other.SceneRevisionNumber,
            other.AlgorithmVersion,
            other.UnitStatus.ToString(),
            other.Outcome.ToString())).ToArray());

    private static TrackDetailResponse ToDetail(
        TrackDetailRow row,
        TrackEvidenceSet evidenceSet,
        TrackDetailAnalytics analytics)
    {
        // One source: the Evidence Set. The compatibility Representative is rank 0 of the
        // same list, so the two cannot disagree (S1.3 plan D1).
        var observations = evidenceSet.Observations.Select(ToObservation).ToArray();
        var representative = evidenceSet.Representative is { } rankZero
            ? ToRepresentative(rankZero)
            : null;

        return new TrackDetailResponse(
            row.Id,
            row.ProcessingRunId,
            row.VideoAssetId,
            new TrackCameraResponse(row.CameraId, row.CameraCode, row.CameraName),
            row.ObjectClass.ToString(),
            row.LocalTrackNumber,
            row.StartOffsetMs,
            row.EndOffsetMs,
            row.StartTimestampUtc,
            row.EndTimestampUtc,
            row.DurationMs,
            row.DetectionCount,
            row.MeanConfidence,
            row.MaxConfidence,
            row.ReviewStatus.ToString(),
            new TrackProcessingResponse(
                row.PipelineVersion,
                row.DetectorName,
                row.DetectorVersion,
                row.TrackerName,
                row.TrackerVersion,
                row.CompletedAtUtc),
            new TrackVideoResponse(
                row.RecordingStartUtc,
                row.RecordingEndUtc,
                row.VideoDurationMs,
                row.Width,
                row.Height,
                row.FrameRateNumerator,
                row.FrameRateDenominator,
                $"/api/videos/{row.VideoAssetId:D}/content"),
            representative,
            observations,
            row.TrajectoryArtifactId,
            ArtifactContentUrl(row.TrajectoryArtifactId),
            ToDetailAnalytics(analytics));
    }

    private static TrackEvidenceObservationResponse ToObservation(TrackEvidenceObservationRow observation) => new(
        observation.ObservationId,
        observation.Role.ToString(),
        observation.EvidenceRank,
        observation.SourceFrameNumber,
        observation.VideoOffsetMs,
        observation.TimestampUtc,
        observation.Confidence,
        observation.QualityScore,
        observation.SelectionScore,
        ToBoundingBox(observation),
        observation.EvidenceArtifactId,
        ArtifactContentUrl(observation.EvidenceArtifactId));

    private static TrackRepresentativeResponse ToRepresentative(TrackEvidenceObservationRow rankZero) => new(
        rankZero.ObservationId,
        rankZero.SourceFrameNumber,
        rankZero.VideoOffsetMs,
        rankZero.TimestampUtc,
        rankZero.Confidence,
        rankZero.QualityScore,
        ToBoundingBox(rankZero),
        rankZero.EvidenceArtifactId,
        ArtifactContentUrl(rankZero.EvidenceArtifactId));

    private static TrackBoundingBoxResponse ToBoundingBox(TrackEvidenceObservationRow observation) => new(
        observation.BoundingBoxX,
        observation.BoundingBoxY,
        observation.BoundingBoxWidth,
        observation.BoundingBoxHeight);

    /// <summary>
    /// The one server-authored route for a persisted artifact. It is built only from an id
    /// the platform's own relation supplied, never from a path. The accepted-evidence route
    /// then authorises the read (ContentCatalog: referenced by a Completed run).
    /// </summary>
    private static string? ArtifactContentUrl(Guid? artifactId) =>
        artifactId is { } id ? $"/api/artifacts/{id:D}/content" : null;

    [LoggerMessage(EventId = 1420, EventName = "track_evidence_integrity_failure", Level = LogLevel.Error,
        Message = "Track {TrackId} has a persisted Evidence Set that violates {Invariant}; its detail is refused.")]
    private static partial void LogEvidenceIntegrityFailure(
        ILogger logger,
        Guid trackId,
        TrackEvidenceSetInvariant invariant);

    private static IResult Problem(int statusCode, string code, string detail) =>
        Results.Problem(
            statusCode: statusCode,
            detail: detail,
            extensions: new Dictionary<string, object?> { ["code"] = code });
}
