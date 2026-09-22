using System.Globalization;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Contracts.Api.Analytics;
using Mavi.Domain.Intelligence;

namespace Mavi.Api.Endpoints;

/// <summary>
/// The two read-only Slice-6 analytics routes.
/// </summary>
/// <remarks>
/// Deliberately separate from <c>SceneAnalyticsEndpoints</c>, which owns lifecycle
/// mutation. Nothing here changes state, and this slice adds no mutation route.
/// <para>
/// Query parameters are strictly whitelisted and every singleton key must appear at
/// most once, so a caller cannot smuggle behaviour past validation with an unknown or
/// repeated parameter.
/// </para>
/// </remarks>
public static class AnalyticsEndpoints
{
    public static IEndpointRouteBuilder MapAnalyticsEndpoints(this IEndpointRouteBuilder endpoints)
    {
        var analytics = endpoints.MapGroup("/api/cameras/{cameraId:guid}/analytics");
        analytics.MapGet("/aggregates", AggregatesAsync);
        analytics.MapGet("/heatmap", HeatmapAsync);
        return endpoints;
    }

    private static async Task<IResult> AggregatesAsync(
        Guid cameraId,
        HttpContext context,
        AnalyticsAggregateService service,
        CancellationToken cancellationToken)
    {
        var values = context.Request.Query;
        if (values.Keys.Any(key => !AnalyticsQueryRules.AggregateQueryKeys.Contains(key, StringComparer.Ordinal)))
            return Invalid("An unsupported query parameter was supplied.");

        if (!TryUtc(values, AnalyticsQueryRules.FromUtcKey, out var fromUtc) ||
            !TryUtc(values, AnalyticsQueryRules.ToUtcKey, out var toUtc) ||
            !TryInt(values, AnalyticsQueryRules.BucketSecondsKey, out var bucketSeconds) ||
            !TryObjectClass(values, out var objectClass))
            return Invalid("Analytics query parameters are invalid.");

        if (fromUtc is null || toUtc is null || bucketSeconds is null)
            return Invalid("fromUtc, toUtc and bucketSeconds are required.");
        if (fromUtc >= toUtc)
            return Invalid("fromUtc must be earlier than toUtc.");
        if (!AnalyticsQueryRules.IsBucketSeconds(bucketSeconds.Value))
            return Invalid("bucketSeconds is outside the supported range.");

        // A response-shape bound, refused before any work: the window and bucket size
        // are both individually legal and would still produce an untransportable body.
        var bucketCount = AnalyticsQueryRules.BucketCount(fromUtc.Value, toUtc.Value, bucketSeconds.Value);
        if (bucketCount > AnalyticsQueryRules.MaximumBuckets)
        {
            return Results.Problem(
                statusCode: 400,
                title: "Too many buckets",
                detail: $"The window and bucket size would produce {bucketCount} buckets; the maximum is {AnalyticsQueryRules.MaximumBuckets}.",
                extensions: new Dictionary<string, object?>
                {
                    ["code"] = AnalyticsQueryRules.BucketCountInvalidCode,
                    ["maximumBuckets"] = AnalyticsQueryRules.MaximumBuckets,
                });
        }

        var response = await service.AggregateAsync(
            new AnalyticsAggregateQuery(cameraId, fromUtc.Value, toUtc.Value, bucketSeconds.Value, objectClass),
            cancellationToken);

        return response is null
            ? Problem(404, AnalyticsQueryRules.CameraNotFoundCode, "Camera was not found.")
            : Results.Ok(response);
    }

    private static async Task<IResult> HeatmapAsync(
        Guid cameraId,
        HttpContext context,
        AnalyticsAggregateService service,
        CancellationToken cancellationToken)
    {
        var values = context.Request.Query;
        if (values.Keys.Any(key => !AnalyticsQueryRules.HeatmapQueryKeys.Contains(key, StringComparer.Ordinal)))
            return Invalid("An unsupported query parameter was supplied.");

        if (!TryUtc(values, AnalyticsQueryRules.FromUtcKey, out var fromUtc) ||
            !TryUtc(values, AnalyticsQueryRules.ToUtcKey, out var toUtc) ||
            !TryInt(values, AnalyticsQueryRules.GridWidthKey, out var gridWidth) ||
            !TryGuid(values, AnalyticsQueryRules.ProcessingRunIdKey, out var runId) ||
            !TryObjectClass(values, out var objectClass))
            return Invalid("Analytics query parameters are invalid.");

        if (fromUtc is null || toUtc is null)
            return Invalid("fromUtc and toUtc are required.");
        if (fromUtc >= toUtc)
            return Invalid("fromUtc must be earlier than toUtc.");

        var width = gridWidth ?? AnalyticsQueryRules.DefaultGridWidth;
        if (!AnalyticsQueryRules.IsGridWidth(width))
            return Invalid("gridWidth is not a supported grid resolution.");

        var query = new AnalyticsHeatmapQuery(cameraId, fromUtc.Value, toUtc.Value, objectClass, width, runId);
        var result = await service.HeatmapAsync(query, cancellationToken);

        switch (result.Failure)
        {
            case AnalyticsFailure.NotFound:
                // The same answer for an unknown camera and for a run that is hidden,
                // unpublished or another camera's: the boundary does not enumerate.
                return Problem(404, AnalyticsQueryRules.CameraNotFoundCode, "Camera was not found.");

            case AnalyticsFailure.ScopeTooLarge:
                return Results.Problem(
                    statusCode: 422,
                    title: "Heatmap scope is too large",
                    detail: "The requested scope exceeds a bounded dimension. Narrow the time window or the run scope and try again.",
                    extensions: new Dictionary<string, object?>
                    {
                        ["code"] = AnalyticsQueryRules.HeatmapScopeTooLargeCode,
                        ["dimension"] = result.ExceededDimension,
                        ["limit"] = result.ExceededLimit,
                    });

            case AnalyticsFailure.EvidenceUnreadable:
                // Deliberately opaque: the operator is told the evidence could not be
                // read, never which artefact or where it lives.
                return Problem(
                    503,
                    AnalyticsQueryRules.EvidenceUnreadableCode,
                    "Trajectory evidence for an analysed Track could not be read.");

            default:
                return Results.Ok(AnalyticsAggregateService.ToResponse(query, result));
        }
    }

    private static IResult Invalid(string detail) =>
        Problem(400, AnalyticsQueryRules.InvalidQueryCode, detail);

    private static IResult Problem(int statusCode, string code, string detail) =>
        Results.Problem(
            statusCode: statusCode,
            detail: detail,
            extensions: new Dictionary<string, object?> { ["code"] = code });

    /// <summary>One value or none. A repeated singleton key is a malformed request.</summary>
    private static bool SingleOrMissing(IQueryCollection values, string key, out string? value)
    {
        value = null;
        if (!values.TryGetValue(key, out var raw))
            return true;
        if (raw.Count != 1 || string.IsNullOrWhiteSpace(raw[0]))
            return false;
        value = raw[0];
        return true;
    }

    /// <summary>
    /// A timestamp that names UTC explicitly, matching the existing Track-search rule.
    /// A local time without an offset is ambiguous and is refused rather than guessed.
    /// </summary>
    private static bool TryUtc(IQueryCollection values, string key, out DateTimeOffset? result)
    {
        result = null;
        if (!SingleOrMissing(values, key, out var raw))
            return false;
        if (raw is null)
            return true;

        var explicitUtc =
            raw.Contains('T', StringComparison.Ordinal) &&
            (raw.EndsWith('Z') || raw.EndsWith("+00:00", StringComparison.Ordinal));
        if (!explicitUtc ||
            !DateTimeOffset.TryParse(raw, CultureInfo.InvariantCulture, DateTimeStyles.None, out var value) ||
            value.Offset != TimeSpan.Zero)
            return false;

        result = value;
        return true;
    }

    private static bool TryInt(IQueryCollection values, string key, out int? result)
    {
        result = null;
        if (!SingleOrMissing(values, key, out var raw))
            return false;
        if (raw is null)
            return true;
        if (!int.TryParse(raw, NumberStyles.None, CultureInfo.InvariantCulture, out var value))
            return false;
        result = value;
        return true;
    }

    private static bool TryGuid(IQueryCollection values, string key, out Guid? result)
    {
        result = null;
        if (!SingleOrMissing(values, key, out var raw))
            return false;
        if (raw is null)
            return true;
        if (!Guid.TryParse(raw, CultureInfo.InvariantCulture, out var value))
            return false;
        result = value;
        return true;
    }

    private static bool TryObjectClass(IQueryCollection values, out ObjectClass? result)
    {
        result = null;
        if (!SingleOrMissing(values, AnalyticsQueryRules.ObjectClassKey, out var raw))
            return false;
        if (raw is null)
            return true;
        if (!AnalyticsQueryRules.IsObjectClass(raw) ||
            !Enum.TryParse<ObjectClass>(raw, ignoreCase: false, out var value))
            return false;
        result = value;
        return true;
    }
}
