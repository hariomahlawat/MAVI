using Mavi.Application.Modules.VisualAttributes;

namespace Mavi.Api.Startup;

/// <summary>
/// Resolves the attribute release at startup and refuses a Development-only definition —
/// the S2b fixture — outside Development and Testing (S2b plan §5: Production refuses the
/// fixture; enabling fixture support never makes a Production registry accept it).
/// </summary>
/// <remarks>
/// A malformed overlay fails the host here, before it serves or leases anything, instead of
/// on the first reconciler cycle. An attributes pack that is unavailable does not stop the
/// vision role (ADR-014 §9): nothing here involves the vision plane.
/// </remarks>
public static class VisualAttributeReleaseStartup
{
    public const string FixtureForbiddenCode = "visual_attribute_development_definition_forbidden";

    private static readonly Action<ILogger, string, Exception?> LogConfigured =
        LoggerMessage.Define<string>(LogLevel.Information, new EventId(1960, "VisualAttributeReleaseConfigured"),
            "Visual attribute analysis is configured for identity {Fingerprint}.");

    private static readonly Action<ILogger, string, Exception?> LogNotConfigured =
        LoggerMessage.Define<string>(LogLevel.Information, new EventId(1961, "VisualAttributeReleaseNotConfigured"),
            "Visual attribute analysis is not configured ({Reason}).");

    public static void VerifyVisualAttributeRelease(this WebApplication app)
    {
        ArgumentNullException.ThrowIfNull(app);
        var resolution = app.Services.GetRequiredService<IVisualAttributeRelease>().Resolution;
        var logger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("Mavi.VisualAttributes");
        if (resolution.Definition is not { } definition)
        {
            LogNotConfigured(logger, resolution.NotConfiguredReason!, null);
            return;
        }

        RequireAllowed(definition, app.Environment);
        LogConfigured(logger, definition.Identity.Fingerprint, null);
    }

    /// <summary>A Development-only definition (the S2b fixture) starts only in Development or Testing.</summary>
    public static void RequireAllowed(Mavi.Application.Modules.VisualAttributes.Release.VisualAttributeReleaseDefinition definition, IHostEnvironment environment)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(environment);
        if (definition.DevelopmentOnly && !environment.IsDevelopment() && !environment.IsEnvironment("Testing"))
            throw new InvalidOperationException(FixtureForbiddenCode);
    }
}
