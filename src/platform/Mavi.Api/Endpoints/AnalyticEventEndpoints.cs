using System.Globalization;
using Mavi.Application.Modules.Events;
using Mavi.Contracts.Api.Analytics;
using Mavi.Contracts.Api.Events;

namespace Mavi.Api.Endpoints;

/// <summary>
/// The read-only Events surface (ADR-025): the rule catalogue, one camera's event
/// timeline, and one event with its provenance envelope.
/// </summary>
/// <remarks>
/// Nothing here mutates. Events are derived by the background sweep from persisted
/// facts; there is deliberately no route that creates, edits or deletes one. Query keys
/// are whitelisted and singleton keys may appear once, as on the Stage-3 analytics routes.
/// </remarks>
public static class AnalyticEventEndpoints
{
    public static IEndpointRouteBuilder MapAnalyticEventEndpoints(this IEndpointRouteBuilder endpoints)
    {
        endpoints.MapGet("/api/events/catalogue", () => Results.Ok(AnalyticEventService.Catalogue(RuleCatalogue.Current)));
        endpoints.MapGet("/api/events/{eventId:guid}", DetailAsync);
        endpoints.MapGet("/api/cameras/{cameraId:guid}/events", TimelineAsync);
        return endpoints;
    }

    private static async Task<IResult> TimelineAsync(
        Guid cameraId,
        HttpContext context,
        AnalyticEventService service,
        CancellationToken cancellationToken)
    {
        var values = context.Request.Query;
        if (values.Keys.Any(key => !AnalyticEventQueryRules.TimelineQueryKeys.Contains(key, StringComparer.Ordinal)))
            return Invalid("An unsupported query parameter was supplied.");

        foreach (var key in new[] { AnalyticsQueryRules.FromUtcKey, AnalyticsQueryRules.ToUtcKey, AnalyticsQueryRules.BucketSecondsKey, AnalyticEventQueryRules.LimitKey })
        {
            if (values[key].Count > 1)
                return Invalid($"{key} may be supplied at most once.");
        }

        if (!TryUtc(values[AnalyticsQueryRules.FromUtcKey], out var fromUtc) ||
            !TryUtc(values[AnalyticsQueryRules.ToUtcKey], out var toUtc) ||
            !TryInt(values[AnalyticsQueryRules.BucketSecondsKey], out var bucketSeconds) ||
            !TryInt(values[AnalyticEventQueryRules.LimitKey], out var limit))
            return Invalid("Events query parameters are invalid.");

        if (fromUtc is null || toUtc is null || bucketSeconds is null)
            return Invalid("fromUtc, toUtc and bucketSeconds are required.");
        if (fromUtc >= toUtc)
            return Invalid("fromUtc must be earlier than toUtc.");
        if (!AnalyticsQueryRules.IsBucketSeconds(bucketSeconds.Value))
            return Invalid("bucketSeconds is outside the supported range.");
        if (AnalyticsQueryRules.BucketCount(fromUtc.Value, toUtc.Value, bucketSeconds.Value) > AnalyticsQueryRules.MaximumBuckets)
            return Invalid($"The window and bucket size would produce more than {AnalyticsQueryRules.MaximumBuckets} buckets.");

        var effectiveLimit = limit ?? AnalyticEventQueryRules.DefaultLimit;
        if (effectiveLimit < 1 || effectiveLimit > AnalyticEventQueryRules.MaximumLimit)
            return Invalid($"limit must be between 1 and {AnalyticEventQueryRules.MaximumLimit}.");

        HashSet<string>? ruleIds = null;
        if (values[AnalyticEventQueryRules.RuleIdKey].Count > 0)
        {
            ruleIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (var ruleId in values[AnalyticEventQueryRules.RuleIdKey])
            {
                if (ruleId is null || !EventRuleIds.All.Contains(ruleId, StringComparer.Ordinal))
                    return Invalid("ruleId is not a rule of the catalogue.");
                ruleIds.Add(ruleId);
            }
        }

        var response = await service.TimelineAsync(
            new AnalyticEventTimelineQuery(cameraId, fromUtc.Value, toUtc.Value, bucketSeconds.Value, ruleIds, effectiveLimit),
            cancellationToken);
        return response is null
            ? Problem(404, AnalyticEventQueryRules.CameraNotFoundCode, "Camera was not found.")
            : Results.Ok(response);
    }

    private static async Task<IResult> DetailAsync(
        Guid eventId,
        HttpContext context,
        AnalyticEventService service,
        CancellationToken cancellationToken)
    {
        if (context.Request.Query.Count > 0)
            return Invalid("This route takes no query parameters.");

        var response = await service.DetailAsync(eventId, cancellationToken);
        return response is null
            ? Problem(404, AnalyticEventQueryRules.EventNotFoundCode, "Event was not found.")
            : Results.Ok(response);
    }

    private static bool TryUtc(Microsoft.Extensions.Primitives.StringValues raw, out DateTimeOffset? value)
    {
        value = null;
        if (raw.Count == 0)
            return true;
        var text = raw[0];
        // Explicit UTC only, as on the Stage-3 analytics routes: an instant without an
        // offset, or with another one, is refused rather than reinterpreted.
        var explicitUtc = text is not null &&
            text.Contains('T', StringComparison.Ordinal) &&
            (text.EndsWith('Z') || text.EndsWith("+00:00", StringComparison.Ordinal));
        if (!explicitUtc ||
            !DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed) ||
            parsed.Offset != TimeSpan.Zero)
            return false;
        value = parsed;
        return true;
    }

    private static bool TryInt(Microsoft.Extensions.Primitives.StringValues raw, out int? value)
    {
        value = null;
        if (raw.Count == 0)
            return true;
        if (!int.TryParse(raw[0], NumberStyles.None, CultureInfo.InvariantCulture, out var parsed))
            return false;
        value = parsed;
        return true;
    }

    private static IResult Invalid(string detail) => Problem(400, AnalyticEventQueryRules.InvalidQueryCode, detail);

    private static IResult Problem(int statusCode, string code, string detail) =>
        Results.Problem(statusCode: statusCode, detail: detail, extensions: new Dictionary<string, object?> { ["code"] = code });
}
