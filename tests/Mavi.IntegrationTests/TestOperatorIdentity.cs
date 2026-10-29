using System.Security.Claims;
using System.Text.Encodings.Web;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Negotiate;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

/// <summary>
/// ADR-010 operator identity for API tests. A Windows token cannot be produced in-process (and CI runs on Linux), so
/// the tests keep the real <c>windows-negotiate</c> mode, scheme selection, operator policy and
/// <c>ICurrentOperator</c>, and swap only the handler that turns a token into a principal: request headers name the
/// Windows account. The real Negotiate handshake is exercised on the Development laptop (register row C10.1).
/// </summary>
internal static class TestOperatorIdentity
{
    public const string Operator = "HOST\\alice";
    public const string OperatorSid = "S-1-5-21-1-2-3-1001";
    public const string OperatorGroup = "HOST\\MAVI Operators";

    /// <summary><c>windows-negotiate</c> with one allow-listed account and one operator group.</summary>
    public static Dictionary<string, string?> WindowsMode() => new()
    {
        ["Identity:Mode"] = "windows-negotiate",
        ["Identity:Operators:AuthorizedUsers:0"] = Operator,
        ["Identity:Operators:AuthorizedGroups:0"] = OperatorGroup,
    };

    public static void UseTestWindowsHandler(IServiceCollection services) =>
        services.PostConfigure<AuthenticationOptions>(options =>
            options.SchemeMap[NegotiateDefaults.AuthenticationScheme].HandlerType = typeof(TestWindowsHandler));

    /// <summary>Names the Windows account the request is made as.</summary>
    public static void As(HttpRequestMessage request, string user, string? sid = null, string? groups = null)
    {
        request.Headers.Add(TestWindowsHandler.UserHeader, user);
        if (sid is not null)
            request.Headers.Add(TestWindowsHandler.SidHeader, sid);
        if (groups is not null)
            request.Headers.Add(TestWindowsHandler.GroupsHeader, groups);
    }
}

/// <summary>Stands in for the Negotiate token exchange only: a header names the Windows account.</summary>
internal sealed class TestWindowsHandler(IOptionsMonitor<AuthenticationSchemeOptions> options, ILoggerFactory logger, UrlEncoder encoder)
    : AuthenticationHandler<AuthenticationSchemeOptions>(options, logger, encoder)
{
    public const string UserHeader = "X-Test-Windows-User";
    public const string SidHeader = "X-Test-Windows-Sid";
    public const string GroupsHeader = "X-Test-Windows-Groups";

    protected override Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        var user = Request.Headers[UserHeader].ToString();
        if (string.IsNullOrEmpty(user))
            return Task.FromResult(AuthenticateResult.NoResult());
        var claims = new List<Claim> { new(ClaimTypes.Name, user) };
        var sid = Request.Headers[SidHeader].ToString();
        if (!string.IsNullOrEmpty(sid))
            claims.Add(new Claim(ClaimTypes.PrimarySid, sid));
        claims.AddRange(Request.Headers[GroupsHeader].ToString()
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(group => new Claim(ClaimTypes.Role, group)));
        var principal = new ClaimsPrincipal(new ClaimsIdentity(claims, NegotiateDefaults.AuthenticationScheme));
        return Task.FromResult(AuthenticateResult.Success(new AuthenticationTicket(principal, Scheme.Name)));
    }

    protected override Task HandleChallengeAsync(AuthenticationProperties properties)
    {
        Response.StatusCode = StatusCodes.Status401Unauthorized;
        Response.Headers.WWWAuthenticate = NegotiateDefaults.AuthenticationScheme;
        return Task.CompletedTask;
    }
}
