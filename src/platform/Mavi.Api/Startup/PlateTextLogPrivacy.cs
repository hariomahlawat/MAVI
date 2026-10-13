namespace Mavi.Api.Startup;

/// <summary>
/// Keeps query values — plate text, cursors, every filter — out of the platform's logs (Stage 4 plan §5.5;
/// ADR-013 implementation amendment, item 20).
/// </summary>
/// <remarks>
/// <para>
/// The only framework source of raw request URLs is ASP.NET Core's hosting diagnostics: its request
/// start and finish lines ("Request starting … ?plateText=…", "Request finished …"), written at
/// <c>Information</c> and <c>Debug</c>. This filter suppresses exactly that category below
/// <c>Warning</c>, in code, so raising <c>Microsoft.AspNetCore</c> for diagnosis can never write a query
/// string. Request observability is not lost: <see cref="Middleware.SafeRequestTelemetryMiddleware"/>
/// emits its own start and finish events with the method, the matched route template, the status, the
/// duration and the trace id, and nothing taken from the query beyond two closed-vocabulary plate fields.
/// </para>
/// <para>
/// The rule is registered after the configuration's rules and names the exact category, so it wins over
/// any provider-agnostic configuration rule for it. A provider-specific rule naming that exact category
/// could still override it; that is configuration the runbook does not ship.
/// </para>
/// </remarks>
public static class PlateTextLogPrivacy
{
    /// <summary>The ASP.NET Core category that writes full request URLs.</summary>
    public const string RequestUrlCategory = "Microsoft.AspNetCore.Hosting.Diagnostics";

    public static ILoggingBuilder AddPlateTextLogPrivacy(this ILoggingBuilder logging)
    {
        ArgumentNullException.ThrowIfNull(logging);
        return logging.AddFilter(RequestUrlCategory, level => level >= LogLevel.Warning);
    }
}
