using System.Diagnostics;
using Mavi.Contracts.Api.Tracks;

namespace Mavi.Api.Middleware;

/// <summary>
/// Request start and finish telemetry that can never carry a query value (Stage 4 plan §5.5; ADR-013
/// implementation amendment, item 20).
/// </summary>
/// <remarks>
/// <para>
/// ASP.NET Core's own request lines ("Request starting GET" followed by the absolute request URL) write the
/// raw URL, query string included, and a query string may carry plate text, cursor values or any other
/// filter. Those framework lines are suppressed (<see cref="Startup.PlateTextLogPrivacy"/>) and replaced
/// by these two events, which record exactly: the HTTP method, the matched route template (never the
/// request path, which may carry identifiers), the status code, the elapsed time and the trace id.
/// </para>
/// <para>
/// A Track search adds only <c>plateFilterPresent</c> and, when the request's match mode is one of the
/// closed vocabulary, <c>plateMatch</c> (an absent mode beside a plate text is the default
/// <c>contains</c>). The plate value is never logged, not even hashed: a hash of a 3–15 character text
/// from 36 symbols is reversible by enumeration.
/// </para>
/// </remarks>
public static partial class SafeRequestTelemetryMiddleware
{
    public const string CategoryName = "Mavi.Api.RequestTelemetry";
    public const int RequestStartingEventId = 1430;
    public const int RequestFinishedEventId = 1431;

    /// <summary>The template recorded for a request that matched no endpoint (static files, the SPA shell).</summary>
    public const string UnmatchedRoute = "(no endpoint)";

    /// <summary>The value of a plate field the request does not have (not a Track search, or no valid mode).</summary>
    public const string NotApplicable = "none";

    public static IApplicationBuilder UseSafeRequestTelemetry(this IApplicationBuilder app)
    {
        ArgumentNullException.ThrowIfNull(app);
        var logger = app.ApplicationServices.GetRequiredService<ILoggerFactory>().CreateLogger(CategoryName);
        return app.Use(async (context, next) =>
        {
            var started = Stopwatch.GetTimestamp();
            var method = context.Request.Method;
            var route = RouteTemplate(context);
            var traceId = Activity.Current?.TraceId.ToString() ?? context.TraceIdentifier;
            var (present, match) = PlateFields(context, route);
            var plateFilterPresent = present switch { true => "true", false => "false", null => NotApplicable };
            var plateMatch = match ?? NotApplicable;
            LogStarting(logger, method, route, traceId, plateFilterPresent, plateMatch);

            var failed = false;
            try
            {
                await next(context);
            }
            catch
            {
                failed = true;
                throw;
            }
            finally
            {
                // The route is read again: endpoint selection may have happened inside the pipeline.
                var finalRoute = RouteTemplate(context);
                var status = failed && !context.Response.HasStarted ? StatusCodes.Status500InternalServerError : context.Response.StatusCode;
                var elapsedMilliseconds = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
                LogFinished(logger, method, finalRoute, status, elapsedMilliseconds, traceId, plateFilterPresent, plateMatch);
            }
        });
    }

    /// <summary>The matched endpoint's route template, never the request path.</summary>
    public static string RouteTemplate(HttpContext context)
    {
        ArgumentNullException.ThrowIfNull(context);
        return context.GetEndpoint() is RouteEndpoint { RoutePattern.RawText: { } template }
            ? (template.StartsWith('/') ? template : "/" + template)
            : UnmatchedRoute;
    }

    /// <summary>
    /// For the Track search only: whether a plate filter is present, and its match mode when it is one of
    /// the closed vocabulary. Every other request carries neither field (null).
    /// </summary>
    public static (bool? PlateFilterPresent, string? PlateMatch) PlateFields(HttpContext context, string route)
    {
        ArgumentNullException.ThrowIfNull(context);
        if (!string.Equals(route.TrimEnd('/'), "/api/tracks", StringComparison.Ordinal))
            return (null, null);

        var query = context.Request.Query;
        var present = query.ContainsKey(TrackSearchContractRules.PlateTextKey);
        if (!present)
            return (false, null);

        if (!query.TryGetValue(TrackSearchContractRules.PlateMatchKey, out var raw))
            return (true, TrackSearchContractRules.DefaultPlateMatch);
        // Only a vocabulary word is ever echoed; anything else a caller sent is not logged.
        return (true, raw.Count == 1 && TrackSearchContractRules.IsPlateMatch(raw[0]) ? raw[0] : null);
    }

    [LoggerMessage(EventId = RequestStartingEventId, EventName = "request_starting", Level = LogLevel.Information,
        Message = "Request starting {Method} {RouteTemplate} (trace {TraceId}, plateFilterPresent {PlateFilterPresent}, plateMatch {PlateMatch})")]
    private static partial void LogStarting(ILogger logger, string method, string routeTemplate, string traceId,
        string plateFilterPresent, string plateMatch);

    [LoggerMessage(EventId = RequestFinishedEventId, EventName = "request_finished", Level = LogLevel.Information,
        Message = "Request finished {Method} {RouteTemplate} {StatusCode} in {ElapsedMilliseconds:F1} ms (trace {TraceId}, plateFilterPresent {PlateFilterPresent}, plateMatch {PlateMatch})")]
    private static partial void LogFinished(ILogger logger, string method, string routeTemplate, int statusCode, double elapsedMilliseconds,
        string traceId, string plateFilterPresent, string plateMatch);
}
