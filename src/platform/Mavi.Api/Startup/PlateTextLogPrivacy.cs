namespace Mavi.Api.Startup;

/// <summary>
/// Keeps plate text out of the platform's logs (Stage 4 plan §5.5).
/// </summary>
/// <remarks>
/// <para>
/// A plate search carries its text in the query string (<c>plateText</c>), and so may any request
/// URL. MAVI's own messages never log a query string, and the plate search logs only that a plate
/// predicate was present, its match mode and counts. The one framework source of request URLs is
/// ASP.NET Core's hosting diagnostics ("Request starting … ?plateText=…", "Request finished …"), which
/// the shipped configuration already holds at <c>Warning</c> through <c>Microsoft.AspNetCore</c>.
/// </para>
/// <para>
/// This filter makes that floor a code invariant rather than a configuration default, so an operator
/// raising <c>Microsoft.AspNetCore</c> to <c>Information</c> for diagnosis does not start writing plate
/// text to disk. The rule is registered after the configuration's rules and names the exact category,
/// so it wins over any provider-agnostic configuration rule for that category. <i>Trade-off:</i> the
/// per-request start/finish lines are not available at any level; request outcomes remain visible
/// through MAVI's own messages and every warning or error the framework raises.
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
