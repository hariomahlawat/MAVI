namespace Mavi.Api.Startup;

/// <summary>
/// Keeps query values — plate text, cursors, every filter — out of MAVI's server and application logs
/// (Stage 4 plan §5.5; ADR-013 implementation amendment, item 20). That is the whole claim: the search is a
/// GET and the UI keeps its state in the URL, so plate text can be in the address bar and browser history;
/// <see cref="Middleware.ReferrerPolicyMiddleware"/> keeps it from being sent onward as a Referer.
/// </summary>
/// <remarks>
/// <para>
/// A MAVI request URL can carry plate text and cursors in its query string. Every surface that can write a
/// request's raw target is closed:
/// </para>
/// <list type="bullet">
/// <item><b>ASP.NET Core hosting diagnostics</b> (<see cref="RequestUrlCategory"/>): its request start and
/// finish lines carry the absolute URL. Suppressed below <c>Warning</c> here, in code, and replaced by
/// <see cref="Middleware.SafeRequestTelemetryMiddleware"/>, which records the method, the route template,
/// the status, the duration and the trace id only.</item>
/// <item><b>Kestrel bad-request diagnostics</b> (<see cref="KestrelBadRequestCategory"/>): a malformed
/// request is logged at <c>Debug</c> with its request target, query included. Suppressed below
/// <c>Warning</c> here.</item>
/// <item><b>IIS W3C request logs</b>: under the in-process IIS host, IIS writes its own log outside .NET,
/// whose default fields include <c>cs-uri-query</c> and <c>cs(Referer)</c>. MAVI Setup sets the MAVI
/// site's field set without the query, the Referer and cookies (<c>Set-MaviIisSiteLogging</c>), and
/// <c>Test-MaviEnvironment</c> fails if they are logged, including under server-wide central logging.</item>
/// </list>
/// <para>
/// MAVI's own messages never log a query string. The rules here are registered after the configuration's
/// rules and name the exact categories, so they win over any provider-agnostic configuration rule for
/// them; a provider-specific rule naming the exact category could still override them, which no shipped
/// configuration does.
/// </para>
/// </remarks>
public static class PlateTextLogPrivacy
{
    /// <summary>The ASP.NET Core category that writes full request URLs.</summary>
    public const string RequestUrlCategory = "Microsoft.AspNetCore.Hosting.Diagnostics";

    /// <summary>The Kestrel category that writes a malformed request's target, query included.</summary>
    public const string KestrelBadRequestCategory = "Microsoft.AspNetCore.Server.Kestrel.BadRequests";

    public static ILoggingBuilder AddPlateTextLogPrivacy(this ILoggingBuilder logging)
    {
        ArgumentNullException.ThrowIfNull(logging);
        return logging
            .AddFilter(RequestUrlCategory, level => level >= LogLevel.Warning)
            .AddFilter(KestrelBadRequestCategory, level => level >= LogLevel.Warning);
    }
}
