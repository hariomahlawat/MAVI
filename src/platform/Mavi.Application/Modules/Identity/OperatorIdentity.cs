using System.Security.Claims;
using Mavi.Application.Deployment;

namespace Mavi.Application.Modules.Identity;

/// <summary>
/// The operator an attributable action is recorded against (ADR-010 §2). Always taken from the
/// server-side principal, never from a request body.
/// </summary>
public sealed record OperatorIdentity(string OperatorId, string DisplayName, string IdentitySource);

/// <summary>The current request's operator, for endpoints that require <c>OperatorPolicy</c>.</summary>
public interface ICurrentOperator
{
    /// <summary>The operator, or <see langword="null"/> when the request carries none that is authorized.</summary>
    OperatorIdentity? Current { get; }

    /// <summary>The operator; throws when called outside an operator-authorized request.</summary>
    OperatorIdentity Required =>
        Current ?? throw new InvalidOperationException("No authorized operator: the endpoint must require the operator policy.");
}

/// <summary>ADR-010 §1: exactly one identity mode per process.</summary>
public static class OperatorIdentityModes
{
    /// <summary>No authentication: every attributable endpoint refuses. The default, so P1–P3 are unchanged.</summary>
    public const string Disabled = "disabled";

    /// <summary>Windows principal via Negotiate (Kestrel) or IIS Windows Authentication.</summary>
    public const string WindowsNegotiate = "windows-negotiate";

    /// <summary>The labelled fallback: Development, or <c>poc-single-host</c>; never Production.</summary>
    public const string DevelopmentUnattributed = "development-unattributed";
}

public sealed class OperatorIdentityOptions
{
    public const string SectionName = "Identity";

    /// <summary>One of <see cref="OperatorIdentityModes"/>; empty means <see cref="OperatorIdentityModes.Disabled"/>.</summary>
    public string? Mode { get; set; }

    public OperatorAuthorizationOptions Operators { get; set; } = new();
}

public sealed class OperatorAuthorizationOptions
{
    /// <summary>Windows groups whose members are operators (for example <c>BUILTIN\Users</c>).</summary>
    public List<string> AuthorizedGroups { get; set; } = [];

    /// <summary>Windows accounts (<c>DOMAIN\user</c>) that are operators.</summary>
    public List<string> AuthorizedUsers { get; set; } = [];
}

public sealed class OperatorIdentityConfigurationException(string message) : Exception(message);

/// <summary>The identity block of the deployment disclosure (ADR-010 §3).</summary>
public sealed record OperatorIdentityDisclosure(
    string Mode,
    bool Attributable,
    bool OperatorsConfigured,
    string Statement,
    string? InstalledMode);

/// <summary>
/// The rules of ADR-010 as pure functions: which mode is in effect, whether the host may start
/// with it, and which principal is an operator. The API host wires them to ASP.NET Core.
/// </summary>
public static class OperatorIdentityPolicy
{
    /// <summary>The claim the fallback principal carries, so its identity source cannot be mistaken.</summary>
    public const string IdentitySourceClaim = "mavi:identity-source";

    public const string FallbackOperatorId = "development-unattributed";
    public const string FallbackDisplayName = "Development operator (unattributed)";

    public static string EffectiveMode(OperatorIdentityOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        if (string.IsNullOrWhiteSpace(options.Mode))
            return OperatorIdentityModes.Disabled;
        var mode = options.Mode.Trim();
        return mode switch
        {
            OperatorIdentityModes.Disabled or OperatorIdentityModes.WindowsNegotiate or OperatorIdentityModes.DevelopmentUnattributed => mode,
            _ => throw new OperatorIdentityConfigurationException(
                $"{OperatorIdentityOptions.SectionName}:Mode '{mode}' is not an identity mode; use {OperatorIdentityModes.Disabled}, " +
                $"{OperatorIdentityModes.WindowsNegotiate} or {OperatorIdentityModes.DevelopmentUnattributed}."),
        };
    }

    /// <summary>
    /// Fails closed at start-up: the fallback is refused unless the environment is Development or the
    /// effective deployment profile is <c>poc-single-host</c>, and always under the Production environment.
    /// </summary>
    public static void Verify(OperatorIdentityOptions options, string environmentName, string effectiveProfile)
    {
        var mode = EffectiveMode(options);
        if (mode != OperatorIdentityModes.DevelopmentUnattributed)
            return;
        if (string.Equals(environmentName, "Production", StringComparison.OrdinalIgnoreCase))
            throw new OperatorIdentityConfigurationException(
                $"The {OperatorIdentityModes.DevelopmentUnattributed} identity is refused under the Production environment.");
        var development = string.Equals(environmentName, "Development", StringComparison.OrdinalIgnoreCase);
        if (!development && effectiveProfile != DeploymentProfiles.PocSingleHost)
            throw new OperatorIdentityConfigurationException(
                $"The {OperatorIdentityModes.DevelopmentUnattributed} identity is allowed only in the Development environment or " +
                $"under the {DeploymentProfiles.PocSingleHost} profile (environment '{environmentName}', profile '{effectiveProfile}').");
    }

    /// <summary>
    /// The operator this principal is, under the mode in effect, or <see langword="null"/> when it is
    /// not one: unauthenticated, outside the configured groups and accounts, or from another mode's scheme.
    /// </summary>
    public static OperatorIdentity? Resolve(ClaimsPrincipal? principal, OperatorIdentityOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        if (principal?.Identity is not { IsAuthenticated: true } identity)
            return null;
        var source = principal.FindFirst(IdentitySourceClaim)?.Value;
        switch (EffectiveMode(options))
        {
            case OperatorIdentityModes.DevelopmentUnattributed:
                return source == OperatorIdentityModes.DevelopmentUnattributed
                    ? new OperatorIdentity(FallbackOperatorId, FallbackDisplayName, OperatorIdentityModes.DevelopmentUnattributed)
                    : null;
            case OperatorIdentityModes.WindowsNegotiate:
                // A fallback principal is never a Windows operator, whatever its name.
                if (source is not null || string.IsNullOrWhiteSpace(identity.Name))
                    return null;
                if (!IsAuthorizedWindowsOperator(principal, identity.Name, options.Operators))
                    return null;
                var sid = principal.FindFirst(ClaimTypes.PrimarySid)?.Value;
                return new OperatorIdentity(string.IsNullOrWhiteSpace(sid) ? identity.Name : sid, identity.Name,
                    OperatorIdentityModes.WindowsNegotiate);
            default:
                return null;
        }
    }

    public static OperatorIdentityDisclosure Disclose(OperatorIdentityOptions options, string? installedMode)
    {
        var mode = EffectiveMode(options);
        var configured = mode switch
        {
            OperatorIdentityModes.WindowsNegotiate => options.Operators.AuthorizedGroups.Any(value => !string.IsNullOrWhiteSpace(value)) ||
                                                      options.Operators.AuthorizedUsers.Any(value => !string.IsNullOrWhiteSpace(value)),
            OperatorIdentityModes.DevelopmentUnattributed => true,
            _ => false,
        };
        var statement = mode switch
        {
            OperatorIdentityModes.WindowsNegotiate when configured =>
                "Operators are identified by their Windows account; every recorded action names the account.",
            OperatorIdentityModes.WindowsNegotiate =>
                "Operators are identified by their Windows account, but no operator group or account is configured: attributable actions are refused.",
            OperatorIdentityModes.DevelopmentUnattributed =>
                "Development fallback identity: actions are recorded as 'development-unattributed' and are not attributable to a person.",
            _ => "Operator identity is not configured: attributable actions are unavailable.",
        };
        return new OperatorIdentityDisclosure(mode, mode == OperatorIdentityModes.WindowsNegotiate && configured, configured, statement,
            string.IsNullOrWhiteSpace(installedMode) ? null : installedMode);
    }

    private static bool IsAuthorizedWindowsOperator(ClaimsPrincipal principal, string name, OperatorAuthorizationOptions operators)
    {
        if (operators.AuthorizedUsers.Any(user => string.Equals(user?.Trim(), name, StringComparison.OrdinalIgnoreCase)))
            return true;
        foreach (var group in operators.AuthorizedGroups)
        {
            if (string.IsNullOrWhiteSpace(group))
                continue;
            try
            {
                if (principal.IsInRole(group.Trim()))
                    return true;
            }
            catch (SystemException)
            {
                // A Windows group name that does not resolve on this host authorizes nobody.
            }
        }

        return false;
    }
}
