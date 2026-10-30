using System.Security.Claims;
using System.Text.Encodings.Web;
using Mavi.Api.Deployment;
using Mavi.Application.Deployment;
using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Identity;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Negotiate;
using Microsoft.AspNetCore.Authorization;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Identity;

/// <summary>The authorization policy an attributable endpoint requires (ADR-010 §1).</summary>
public static class OperatorPolicy
{
    public const string Name = "mavi-operator";
}

/// <summary>
/// ADR-010 wiring: one authentication scheme per identity mode, of which only the mode in effect is
/// visible; the operator policy; <see cref="ICurrentOperator"/> and the audit correlation. Existing
/// endpoints stay anonymous: there is no fallback authorization policy.
/// </summary>
public static class OperatorIdentityStartup
{
    public const string DevelopmentUnattributedScheme = "MaviDevelopmentUnattributed";
    public const string DisabledScheme = "MaviOperatorIdentityDisabled";

    public static IServiceCollection AddMaviOperatorIdentity(this IServiceCollection services, IConfiguration configuration)
    {
        ArgumentNullException.ThrowIfNull(configuration);
        services.Configure<OperatorIdentityOptions>(configuration.GetSection(OperatorIdentityOptions.SectionName));
        services.AddHttpContextAccessor();
        services.AddScoped<Mavi.Application.Modules.Query.IQueryEntityAccess, HttpQueryEntityAccess>();
        services.AddAuthentication()
            .AddNegotiate()
            .AddScheme<AuthenticationSchemeOptions, DevelopmentUnattributedHandler>(DevelopmentUnattributedScheme, null)
            .AddScheme<AuthenticationSchemeOptions, DisabledOperatorHandler>(DisabledScheme, null);
        // The mode is read when the options are first used, not here, so a host's later configuration
        // sources (and the test host's) decide it.
        services.AddOptions<AuthenticationOptions>().PostConfigure<IOptions<OperatorIdentityOptions>>((authentication, identity) =>
            authentication.DefaultScheme = SchemeFor(OperatorIdentityPolicy.EffectiveMode(identity.Value)));
        services.Replace(ServiceDescriptor.Singleton<IAuthenticationSchemeProvider, OperatorSchemeProvider>());
        services.AddSingleton<IAuthorizationHandler, OperatorAuthorizationHandler>();
        services.AddAuthorizationBuilder()
            .AddPolicy(OperatorPolicy.Name, policy => policy.AddRequirements(new OperatorRequirement()));
        services.AddScoped<ICurrentOperator, HttpCurrentOperator>();
        services.AddScoped<IAuditCorrelation, HttpAuditCorrelation>();
        return services;
    }

    /// <summary>Refuses to start with an unknown mode, or with the fallback outside Development / <c>poc-single-host</c>.</summary>
    public static void VerifyOperatorIdentity(this WebApplication app)
    {
        ArgumentNullException.ThrowIfNull(app);
        var identity = app.Services.GetRequiredService<IOptions<OperatorIdentityOptions>>().Value;
        var deployment = app.Services.GetRequiredService<IOptions<DeploymentOptions>>().Value;
        var profile = DeploymentDisclosureReader.ResolveProfile(deployment, DeploymentEndpoints.BuildProfile);
        OperatorIdentityPolicy.Verify(identity, app.Environment.EnvironmentName, profile);
    }

    internal static string SchemeFor(string mode) => mode switch
    {
        OperatorIdentityModes.WindowsNegotiate => NegotiateDefaults.AuthenticationScheme,
        OperatorIdentityModes.DevelopmentUnattributed => DevelopmentUnattributedScheme,
        _ => DisabledScheme,
    };

    /// <summary>
    /// Hides every operator scheme but the one in effect. Negotiate in particular must not be visible
    /// unless chosen: under IIS without Windows Authentication its handler fails every request.
    /// </summary>
    private sealed class OperatorSchemeProvider(IOptions<AuthenticationOptions> options, IOptions<OperatorIdentityOptions> identity)
        : AuthenticationSchemeProvider(options)
    {
        private static readonly string[] OperatorSchemes =
            [NegotiateDefaults.AuthenticationScheme, DevelopmentUnattributedScheme, DisabledScheme];

        private readonly Lazy<string> _active = new(() => SchemeFor(OperatorIdentityPolicy.EffectiveMode(identity.Value)));

        private bool Hidden(string name) =>
            OperatorSchemes.Contains(name, StringComparer.Ordinal) && !string.Equals(name, _active.Value, StringComparison.Ordinal);

        public override async Task<AuthenticationScheme?> GetSchemeAsync(string name) =>
            Hidden(name) ? null : await base.GetSchemeAsync(name);

        public override async Task<IEnumerable<AuthenticationScheme>> GetAllSchemesAsync() =>
            (await base.GetAllSchemesAsync()).Where(scheme => !Hidden(scheme.Name)).ToArray();

        public override async Task<IEnumerable<AuthenticationScheme>> GetRequestHandlerSchemesAsync() =>
            (await base.GetRequestHandlerSchemesAsync()).Where(scheme => !Hidden(scheme.Name)).ToArray();
    }

    /// <summary>The labelled fallback: every request is the one unattributed Development operator.</summary>
    private sealed class DevelopmentUnattributedHandler(IOptionsMonitor<AuthenticationSchemeOptions> options, ILoggerFactory logger,
        UrlEncoder encoder) : AuthenticationHandler<AuthenticationSchemeOptions>(options, logger, encoder)
    {
        protected override Task<AuthenticateResult> HandleAuthenticateAsync()
        {
            var identity = new ClaimsIdentity(
                [
                    new Claim(ClaimTypes.Name, OperatorIdentityPolicy.FallbackOperatorId),
                    new Claim(OperatorIdentityPolicy.IdentitySourceClaim, OperatorIdentityModes.DevelopmentUnattributed),
                ],
                DevelopmentUnattributedScheme);
            return Task.FromResult(AuthenticateResult.Success(new AuthenticationTicket(new ClaimsPrincipal(identity), Scheme.Name)));
        }
    }

    /// <summary>Mode <c>disabled</c>: nobody is authenticated; a challenge is a plain 401.</summary>
    private sealed class DisabledOperatorHandler(IOptionsMonitor<AuthenticationSchemeOptions> options, ILoggerFactory logger,
        UrlEncoder encoder) : AuthenticationHandler<AuthenticationSchemeOptions>(options, logger, encoder)
    {
        protected override Task<AuthenticateResult> HandleAuthenticateAsync() => Task.FromResult(AuthenticateResult.NoResult());
    }
}

public sealed class OperatorRequirement : IAuthorizationRequirement;

/// <summary>
/// Succeeds when the principal is an operator under the mode in effect (ADR-010 §1). A state-changing
/// request must also carry a JSON body: browsers send Windows credentials automatically, and a
/// cross-site page cannot send <c>application/json</c> without a CORS preflight, which MAVI never grants.
/// </summary>
public sealed class OperatorAuthorizationHandler(IOptions<OperatorIdentityOptions> options) : AuthorizationHandler<OperatorRequirement>
{
    protected override Task HandleRequirementAsync(AuthorizationHandlerContext context, OperatorRequirement requirement)
    {
        ArgumentNullException.ThrowIfNull(context);
        if (OperatorIdentityPolicy.Resolve(context.User, options.Value) is null)
            return Task.CompletedTask;
        if (context.Resource is HttpContext http && !IsSafeOrJson(http.Request))
        {
            context.Fail(new AuthorizationFailureReason(this, "An operator mutation must be an application/json request."));
            return Task.CompletedTask;
        }

        context.Succeed(requirement);
        return Task.CompletedTask;
    }

    private static bool IsSafeOrJson(HttpRequest request) =>
        HttpMethods.IsGet(request.Method) || HttpMethods.IsHead(request.Method) || HttpMethods.IsOptions(request.Method) ||
        request.HasJsonContentType();
}

internal sealed class HttpCurrentOperator(IHttpContextAccessor accessor, IOptions<OperatorIdentityOptions> options) : ICurrentOperator
{
    public OperatorIdentity? Current => OperatorIdentityPolicy.Resolve(accessor.HttpContext?.User, options.Value);
}

internal sealed class HttpAuditCorrelation(IHttpContextAccessor accessor) : IAuditCorrelation
{
    private readonly Lazy<string> _fallback = new(() => Guid.NewGuid().ToString("N"));

    public string CorrelationId => accessor.HttpContext?.TraceIdentifier is { Length: > 0 and <= 128 } trace ? trace : _fallback.Value;
}
