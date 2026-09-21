using Mavi.Application.Modules.Intelligence;

namespace Mavi.Api.Startup;

/// <summary>
/// Refuses to serve analytic cursors under a key the operator never provisioned.
/// </summary>
/// <remarks>
/// An ephemeral key is a convenience for a workstation or a test host: cursors die with
/// the process and nobody is surprised. In Production the same behaviour would look like
/// a key rotation on every restart, invalidating operators' open result sets for no
/// reason they could see, so a Production host without a configured key does not start.
/// The check lives here, not in the options validator, because only the host knows its
/// environment; the same pattern guards <c>MediaProcessing:VerifyOnStartup</c>.
/// </remarks>
public static class TrackCursorSigningStartup
{
    private static readonly Action<ILogger, Exception?> LogEphemeralKey =
        LoggerMessage.Define(
            LogLevel.Warning,
            new EventId(1950, "TrackCursorSigningKeyEphemeral"),
            "TrackSearch:CursorSigningKey is not configured; analytic search cursors are signed with a per-process key and will not survive a restart. Run setup to provision the installation key.");

    public static void VerifyTrackCursorSigning(this WebApplication app)
    {
        ArgumentNullException.ThrowIfNull(app);

        // Resolving the singleton here is also what surfaces a malformed configured key
        // at start-up rather than on the first analytic search.
        var key = app.Services.GetRequiredService<TrackCursorSigningKey>();
        if (!key.IsEphemeral)
            return;

        if (!app.Environment.IsDevelopment() && !app.Environment.IsEnvironment("Testing"))
        {
            throw new InvalidOperationException(
                $"{TrackSearchOptions.SectionName}:AllowEphemeralCursorSigningKey may be set only in the Development or Testing environment; " +
                $"provision {TrackSearchOptions.SectionName}:CursorSigningKey through setup.");
        }

        LogEphemeralKey(
            app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("Mavi.TrackSearch"),
            null);
    }
}
