using System.Globalization;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Tracks;
using Mavi.Domain.Intelligence;

namespace Mavi.Api.Endpoints;

public static class TrackEndpoints
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
            return Problem(400, result.ErrorCode!, "Track search parameters are invalid.");

        var response = new TrackSearchResponse(
            result.Page!.Items.Select(ToSearchItem).ToArray(),
            result.Page.NextCursor);
        return Results.Ok(response);
    }

    private static async Task<IResult> GetAsync(
        Guid id,
        TrackSearchService service,
        CancellationToken cancellationToken)
    {
        var result = await service.GetDetailAsync(id, TrackAnalyticsDetailRequest.Current, cancellationToken);
        if (!result.IsSuccess)
            return Problem(400, result.ErrorCode!, "Track detail parameters are invalid.");
        return result.Row is null
            ? Problem(404, "track_not_found", "Track was not found.")
            : Results.Ok(ToDetail(result.Row));
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

    private static TrackSearchItemResponse ToSearchItem(TrackSearchRow row) => new(
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
        $"/api/videos/{row.VideoAssetId:D}/content");

    private static TrackDetailResponse ToDetail(TrackDetailRow row)
    {
        TrackRepresentativeResponse? representative = null;
        if (row.RepresentativeObservationId is { } observationId)
        {
            representative = new TrackRepresentativeResponse(
                observationId,
                row.RepresentativeSourceFrameNumber!.Value,
                row.RepresentativeVideoOffsetMs!.Value,
                row.RepresentativeTimestampUtc!.Value,
                row.RepresentativeConfidence!.Value,
                row.RepresentativeQualityScore!.Value,
                new TrackBoundingBoxResponse(
                    row.BoundingBoxX!.Value,
                    row.BoundingBoxY!.Value,
                    row.BoundingBoxWidth!.Value,
                    row.BoundingBoxHeight!.Value),
                row.ThumbnailArtifactId,
                row.ThumbnailArtifactId is { } thumbnailId
                    ? $"/api/artifacts/{thumbnailId:D}/content"
                    : null);
        }

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
            row.TrajectoryArtifactId,
            row.TrajectoryArtifactId is { } trajectoryId
                ? $"/api/artifacts/{trajectoryId:D}/content"
                : null);
    }

    private static IResult Problem(int statusCode, string code, string detail) =>
        Results.Problem(
            statusCode: statusCode,
            detail: detail,
            extensions: new Dictionary<string, object?> { ["code"] = code });
}
