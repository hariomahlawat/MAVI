using System.Net;
using System.Net.Http.Json;
using System.Security.Claims;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using Mavi.Application.Deployment;
using Mavi.Application.Modules.Identity;
using Mavi.Infrastructure.Persistence;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Negotiate;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

/// <summary>
/// ADR-010 at the HTTP boundary: the operator policy, the three identity modes, the fallback's
/// start-up refusal, the audit row a policy-gated mutation writes, and the disclosure.
/// </summary>
/// <remarks>
/// A Windows token cannot be produced in-process (and CI runs on Linux), so the Negotiate tests keep
/// the real scheme, mode selection, policy and <see cref="ICurrentOperator"/> and swap only the
/// handler that turns a token into a principal. The real Negotiate handshake is exercised on the
/// Development laptop (register row C10.1).
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class OperatorIdentityApiTests : IDisposable
{
    private static readonly DateTimeOffset ServerNow = new(2026, 10, 29, 9, 30, 0, TimeSpan.Zero);
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"mavi-identity-api-{Guid.NewGuid():N}");

    public OperatorIdentityApiTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); }
        catch (IOException) { }
    }

    [Fact]
    public async Task ByDefaultNobodyIsAnOperatorAndExistingEndpointsStayAnonymous()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();

        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/api/cameras")).StatusCode);
        using var challenged = await client.GetAsync("/api/system/operator");
        Assert.Equal(HttpStatusCode.Unauthorized, challenged.StatusCode);
        // Negotiate is never built in this mode (under IIS without Windows Authentication it would fail every request).
        Assert.DoesNotContain("Negotiate", challenged.Headers.WwwAuthenticate.Select(header => header.Scheme));
        var schemes = factory.Services.GetRequiredService<IAuthenticationSchemeProvider>();
        Assert.Null(await schemes.GetSchemeAsync(NegotiateDefaults.AuthenticationScheme));
        Assert.DoesNotContain(await schemes.GetRequestHandlerSchemesAsync(), scheme => scheme.Name == NegotiateDefaults.AuthenticationScheme);
        using var mutation = await client.PostAsJsonAsync("/api/system/disclosure-acknowledgements", new { statement = "x" });
        Assert.Equal(HttpStatusCode.Unauthorized, mutation.StatusCode);

        var identity = await DisclosedIdentityAsync(client);
        Assert.Equal("disabled", identity.GetProperty("mode").GetString());
        Assert.False(identity.GetProperty("attributable").GetBoolean());
        Assert.Equal(0, await AuditCountAsync(factory));
    }

    [Fact]
    public async Task TheRealNegotiateHandlerUnderKestrelChallengesAnAnonymousRequest()
    {
        using var factory = new ApiTestFactory { AdditionalConfiguration = WindowsMode() };
        factory.UseKestrel(0);
        await factory.ResetAndMigrateAsync();
        using var client = KestrelClient(factory, defaultCredentials: false);

        using var response = await client.GetAsync("/api/system/operator");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Contains("Negotiate", response.Headers.WwwAuthenticate.Select(header => header.Scheme));
        // Anonymous endpoints are not challenged.
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/api/cameras")).StatusCode);
    }

    [WindowsFact]
    public async Task TheRealNegotiateHandshakeResolvesTheSignedInWindowsAccount()
    {
        if (!OperatingSystem.IsWindows())
            return;
        using var current = System.Security.Principal.WindowsIdentity.GetCurrent();
        var configuration = WindowsMode();
        // Authorized through the group the PoC installer configures, so WindowsPrincipal.IsInRole is exercised.
        configuration["Identity:Operators:AuthorizedGroups:1"] = "BUILTIN\\Users";
        using var factory = new ApiTestFactory { AdditionalConfiguration = configuration };
        factory.UseKestrel(0);
        await factory.ResetAndMigrateAsync();
        using var client = KestrelClient(factory, defaultCredentials: true);

        using var response = await client.GetAsync("/api/system/operator");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal(current.User!.Value, document.RootElement.GetProperty("operatorId").GetString());
        Assert.Equal(current.Name, document.RootElement.GetProperty("displayName").GetString());
        Assert.Equal("windows-negotiate", document.RootElement.GetProperty("identitySource").GetString());
    }

    [Fact]
    public async Task TheNegotiatePathResolvesTheWindowsOperatorAndAttributesTheMutation()
    {
        using var factory = WindowsFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();

        using var whoAmI = Request(HttpMethod.Get, "/api/system/operator", "HOST\\alice", sid: "S-1-5-21-1-2-3-1001");
        using var operatorResponse = await client.SendAsync(whoAmI);
        Assert.Equal(HttpStatusCode.OK, operatorResponse.StatusCode);
        using (var document = JsonDocument.Parse(await operatorResponse.Content.ReadAsStringAsync()))
        {
            Assert.Equal("S-1-5-21-1-2-3-1001", document.RootElement.GetProperty("operatorId").GetString());
            Assert.Equal("HOST\\alice", document.RootElement.GetProperty("displayName").GetString());
            Assert.Equal("windows-negotiate", document.RootElement.GetProperty("identitySource").GetString());
        }

        var statement = (await DisclosedIdentityAsync(client)).GetProperty("statement").GetString();
        using var acknowledge = Request(HttpMethod.Post, "/api/system/disclosure-acknowledgements", "HOST\\alice",
            sid: "S-1-5-21-1-2-3-1001", body: new { statement });
        // A client-supplied operator is ignored: the actor comes from the principal only.
        acknowledge.Headers.Add("X-Operator-Id", "HOST\\mallory");
        using var created = await client.SendAsync(acknowledge);

        Assert.Equal(HttpStatusCode.Created, created.StatusCode);
        await using var db = Db(factory);
        var entry = await db.AuditEntries.SingleAsync();
        Assert.Equal("S-1-5-21-1-2-3-1001", entry.OperatorId);
        Assert.Equal("HOST\\alice", entry.OperatorDisplayName);
        Assert.Equal("windows-negotiate", entry.IdentitySource);
        Assert.Equal(DisclosureAcknowledgement.Action, entry.Action);
        Assert.Equal(ServerNow, entry.RecordedAtUtc);
        Assert.False(string.IsNullOrWhiteSpace(entry.CorrelationId));
    }

    [Fact]
    public async Task ThePolicyDeniesAnonymousOutsidersAndCrossSiteShapedMutations()
    {
        using var factory = WindowsFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();
        var statement = (await DisclosedIdentityAsync(client)).GetProperty("statement").GetString();

        using var anonymous = await client.PostAsJsonAsync("/api/system/disclosure-acknowledgements", new { statement });
        Assert.Equal(HttpStatusCode.Unauthorized, anonymous.StatusCode);
        Assert.Contains("Negotiate", anonymous.Headers.WwwAuthenticate.Select(header => header.Scheme));

        using var outsider = await client.SendAsync(Request(HttpMethod.Post, "/api/system/disclosure-acknowledgements", "HOST\\carol",
            groups: "HOST\\Guests", body: new { statement }));
        Assert.Equal(HttpStatusCode.Forbidden, outsider.StatusCode);

        // Mutations a cross-site page could send without a CORS preflight are refused for an operator too:
        // a text/plain body by the endpoint's JSON contract (415), a body-less one by the operator policy (403).
        using var formShaped = Request(HttpMethod.Post, "/api/system/disclosure-acknowledgements", "HOST\\bob", groups: "HOST\\MAVI Operators");
        formShaped.Content = new StringContent($"statement={statement}", Encoding.UTF8, "text/plain");
        Assert.Equal(HttpStatusCode.UnsupportedMediaType, (await client.SendAsync(formShaped)).StatusCode);
        using var bodyless = Request(HttpMethod.Post, "/api/system/disclosure-acknowledgements", "HOST\\bob", groups: "HOST\\MAVI Operators");
        Assert.Equal(HttpStatusCode.Forbidden, (await client.SendAsync(bodyless)).StatusCode);

        // A group member may act, but only on the statement the host serves.
        using var mismatch = await client.SendAsync(Request(HttpMethod.Post, "/api/system/disclosure-acknowledgements", "HOST\\bob",
            groups: "HOST\\MAVI Operators", body: new { statement = "something else" }));
        Assert.Equal(HttpStatusCode.Conflict, mismatch.StatusCode);
        Assert.Equal(0, await AuditCountAsync(factory));

        using var member = await client.SendAsync(Request(HttpMethod.Post, "/api/system/disclosure-acknowledgements", "HOST\\bob",
            groups: "HOST\\MAVI Operators", body: new { statement }));
        Assert.Equal(HttpStatusCode.Created, member.StatusCode);
        Assert.Equal(1, await AuditCountAsync(factory));
    }

    [Fact]
    public async Task TheDevelopmentFallbackIsLabelledInTheAuditRowAndTheDisclosure()
    {
        // Under the PoC profile; the Development environment is covered by OperatorIdentityPolicyTests
        // (a test host outside Testing would need the bundled media tools).
        using var factory = new ApiTestFactory
        {
            Clock = new FixedClock(),
            AdditionalConfiguration = new Dictionary<string, string?>
            {
                ["Identity:Mode"] = "development-unattributed",
                ["Deployment:Profile"] = DeploymentProfiles.PocSingleHost,
                ["Deployment:ReleaseMetadataPath"] = WriteMetadata(),
            },
        };
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();

        var identity = await DisclosedIdentityAsync(client);
        Assert.Equal("development-unattributed", identity.GetProperty("mode").GetString());
        Assert.False(identity.GetProperty("attributable").GetBoolean());
        Assert.Contains("not attributable to a person", identity.GetProperty("statement").GetString(), StringComparison.Ordinal);

        // Under a profile the operator acknowledges the profile's statement.
        string? statement;
        using (var deployment = JsonDocument.Parse(await client.GetStringAsync("/api/system/deployment")))
            statement = deployment.RootElement.GetProperty("statement").GetString();
        Assert.Contains("Not Production-qualified", statement, StringComparison.Ordinal);
        using var created = await client.PostAsJsonAsync("/api/system/disclosure-acknowledgements", new { statement });
        Assert.Equal(HttpStatusCode.Created, created.StatusCode);

        await using var db = Db(factory);
        var entry = await db.AuditEntries.SingleAsync();
        Assert.Equal("development-unattributed", entry.OperatorId);
        Assert.Equal("development-unattributed", entry.IdentitySource);
        Assert.Equal("Development operator (unattributed)", entry.OperatorDisplayName);
    }

    [Fact]
    public void TheFallbackIsRefusedAtStartOutsideDevelopmentAndThePocProfile()
    {
        // The full environment/profile matrix, Production included, is OperatorIdentityPolicyTests; this proves
        // the host runs the check before serving anything.
        using var factory = new ApiTestFactory
        {
            AdditionalConfiguration = new Dictionary<string, string?> { ["Identity:Mode"] = "development-unattributed" },
        };

        var exception = Assert.ThrowsAny<Exception>(() => factory.CreateClient());
        Assert.Contains("development-unattributed identity is allowed only", exception.ToString(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task ThePocProfileDisclosesTheInstalledModeBesideTheOneInEffect()
    {
        using var factory = new ApiTestFactory
        {
            AdditionalConfiguration = new Dictionary<string, string?>
            {
                ["Identity:Mode"] = "development-unattributed",
                ["Deployment:Profile"] = DeploymentProfiles.PocSingleHost,
                ["Deployment:ReleaseMetadataPath"] = WriteMetadata(),
            },
        };
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();

        var identity = await DisclosedIdentityAsync(client);
        Assert.Equal("development-unattributed", identity.GetProperty("mode").GetString());
        Assert.Equal("windows-negotiate", identity.GetProperty("installedMode").GetString());
    }

    /// <summary>
    /// A real HTTP client against the factory's host on Kestrel (the Negotiate handler needs a real
    /// connection); the factory must have been switched to Kestrel before its services were first used.
    /// </summary>
    private static HttpClient KestrelClient(ApiTestFactory factory, bool defaultCredentials)
    {
        factory.StartServer();
        var address = factory.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!.Addresses.First();
        return new HttpClient(new HttpClientHandler { UseDefaultCredentials = defaultCredentials }) { BaseAddress = new Uri(address) };
    }

    private static Dictionary<string, string?> WindowsMode() => new()
    {
        ["Identity:Mode"] = "windows-negotiate",
        ["Identity:Operators:AuthorizedUsers:0"] = "HOST\\alice",
        ["Identity:Operators:AuthorizedGroups:0"] = "HOST\\MAVI Operators",
    };

    private static ApiTestFactory WindowsFactory() => new()
    {
        Clock = new FixedClock(),
        AdditionalConfiguration = WindowsMode(),
        OverrideServices = services => services.PostConfigure<AuthenticationOptions>(options =>
            options.SchemeMap[NegotiateDefaults.AuthenticationScheme].HandlerType = typeof(TestWindowsHandler)),
    };

    private static HttpRequestMessage Request(HttpMethod method, string path, string user, string? sid = null, string? groups = null,
        object? body = null)
    {
        var request = new HttpRequestMessage(method, path);
        request.Headers.Add(TestWindowsHandler.UserHeader, user);
        if (sid is not null)
            request.Headers.Add(TestWindowsHandler.SidHeader, sid);
        if (groups is not null)
            request.Headers.Add(TestWindowsHandler.GroupsHeader, groups);
        if (body is not null)
            request.Content = JsonContent.Create(body);
        return request;
    }

    private static async Task<JsonElement> DisclosedIdentityAsync(HttpClient client)
    {
        using var response = await client.GetAsync("/api/system/deployment");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.GetProperty("identity").Clone();
    }

    private static MaviDbContext Db(ApiTestFactory factory)
    {
        var options = new DbContextOptionsBuilder<MaviDbContext>()
            .UseNpgsql(factory.ConnectionString, npgsql => npgsql.UseVector())
            .Options;
        return new MaviDbContext(options);
    }

    private static async Task<int> AuditCountAsync(ApiTestFactory factory)
    {
        await using var db = Db(factory);
        return await db.AuditEntries.CountAsync();
    }

    private string WriteMetadata()
    {
        var path = Path.Combine(_root, $"release-{Guid.NewGuid():N}.json");
        File.WriteAllText(path, $$"""
            {
              "schemaVersion": "mavi-poc-release-metadata-v1",
              "profile": "poc-single-host",
              "productionQualified": false,
              "evidenceClass": "Development",
              "identityMode": "windows-negotiate",
              "application": { "revision": "{{new string('b', 40)}}" },
              "packs": []
            }
            """);
        return path;
    }

    private sealed class FixedClock : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => ServerNow;
    }

    /// <summary>Stands in for the Negotiate token exchange only: a header names the Windows account.</summary>
    private sealed class TestWindowsHandler(IOptionsMonitor<AuthenticationSchemeOptions> options, ILoggerFactory logger, UrlEncoder encoder)
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
}

/// <summary>A fact that needs a Windows logon (the real Negotiate handshake); skipped elsewhere.</summary>
public sealed class WindowsFactAttribute : FactAttribute
{
    public WindowsFactAttribute()
    {
        if (!OperatingSystem.IsWindows())
            Skip = "Needs a Windows logon for a real Negotiate handshake.";
    }
}
