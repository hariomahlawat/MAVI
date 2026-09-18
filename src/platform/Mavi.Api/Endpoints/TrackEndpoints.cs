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
        var row = await service.GetDetailAsync(id, cancellationToken);
        return row is null
            ? Problem(404, "track_not_found", "Track was not found.")
            : Results.Ok(ToDetail(row));
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
            !SingleOrMissing(values, "cursor", out var cursor))
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
            limit);
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
