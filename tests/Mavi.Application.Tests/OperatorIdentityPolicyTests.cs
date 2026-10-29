using System.Security.Claims;
using Mavi.Application.Deployment;
using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Identity;

namespace Mavi.Application.Tests;

/// <summary>ADR-010 §1–§2: the identity mode, the fallback's confinement and who is an operator.</summary>
public sealed class OperatorIdentityPolicyTests
{
    [Fact]
    public void AnUnsetModeIsDisabledAndAnUnknownOneIsRefused()
    {
        Assert.Equal(OperatorIdentityModes.Disabled, OperatorIdentityPolicy.EffectiveMode(new OperatorIdentityOptions()));
        Assert.Throws<OperatorIdentityConfigurationException>(() =>
            OperatorIdentityPolicy.EffectiveMode(new OperatorIdentityOptions { Mode = "anonymous" }));
        Assert.Throws<OperatorIdentityConfigurationException>(() =>
            OperatorIdentityPolicy.EffectiveMode(new OperatorIdentityOptions { Mode = "Windows-Negotiate" }));
    }

    [Theory]
    [InlineData("Development", DeploymentProfiles.Unspecified)]
    [InlineData("PoC", DeploymentProfiles.PocSingleHost)]
    [InlineData("Development", DeploymentProfiles.PocSingleHost)]
    public void TheFallbackStartsOnlyInDevelopmentOrUnderThePocProfile(string environment, string profile) =>
        OperatorIdentityPolicy.Verify(Fallback(), environment, profile);

    [Theory]
    [InlineData("Production", DeploymentProfiles.Unspecified)]
    [InlineData("Production", DeploymentProfiles.PocSingleHost)]
    [InlineData("Testing", DeploymentProfiles.Unspecified)]
    [InlineData("Staging", DeploymentProfiles.Unspecified)]
    [InlineData("PoC", DeploymentProfiles.Unspecified)]
    public void TheFallbackIsRefusedEverywhereElse(string environment, string profile) =>
        Assert.Throws<OperatorIdentityConfigurationException>(() => OperatorIdentityPolicy.Verify(Fallback(), environment, profile));

    [Theory]
    [InlineData(OperatorIdentityModes.Disabled)]
    [InlineData(OperatorIdentityModes.WindowsNegotiate)]
    public void TheOtherModesStartUnderProduction(string mode) =>
        OperatorIdentityPolicy.Verify(new OperatorIdentityOptions { Mode = mode }, "Production", DeploymentProfiles.Unspecified);

    [Fact]
    public void AnAllowListedWindowsAccountIsAnOperatorIdentifiedBySid()
    {
        var options = Windows(users: ["HOST\\alice"]);
        var principal = WindowsPrincipal("host\\ALICE", sid: "S-1-5-21-1-2-3-1001");

        var identity = OperatorIdentityPolicy.Resolve(principal, options);

        Assert.NotNull(identity);
        Assert.Equal("S-1-5-21-1-2-3-1001", identity!.OperatorId);
        Assert.Equal("host\\ALICE", identity.DisplayName);
        Assert.Equal(OperatorIdentityModes.WindowsNegotiate, identity.IdentitySource);
    }

    [Fact]
    public void AGroupMemberIsAnOperatorAndAnOutsiderIsNot()
    {
        var options = Windows(groups: ["HOST\\MAVI Operators"]);

        Assert.NotNull(OperatorIdentityPolicy.Resolve(WindowsPrincipal("HOST\\bob", roles: ["HOST\\MAVI Operators"]), options));
        Assert.Null(OperatorIdentityPolicy.Resolve(WindowsPrincipal("HOST\\carol", roles: ["HOST\\Guests"]), options));
    }

    [Fact]
    public void AWindowsAccountWithoutASidIsIdentifiedByName()
    {
        var identity = OperatorIdentityPolicy.Resolve(WindowsPrincipal("HOST\\dave"), Windows(users: ["HOST\\dave"]));
        Assert.Equal("HOST\\dave", identity!.OperatorId);
    }

    [Fact]
    public void NobodyIsAnOperatorWhenNoGroupOrAccountIsConfigured()
    {
        Assert.Null(OperatorIdentityPolicy.Resolve(WindowsPrincipal("HOST\\alice", roles: ["BUILTIN\\Users"]), Windows()));
        Assert.False(OperatorIdentityPolicy.Disclose(Windows(), null).OperatorsConfigured);
        Assert.False(OperatorIdentityPolicy.Disclose(Windows(), null).Attributable);
    }

    [Fact]
    public void AnUnauthenticatedPrincipalIsNeverAnOperator()
    {
        var anonymous = new ClaimsPrincipal(new ClaimsIdentity([new Claim(ClaimTypes.Name, "HOST\\alice")]));
        Assert.Null(OperatorIdentityPolicy.Resolve(anonymous, Windows(users: ["HOST\\alice"])));
        Assert.Null(OperatorIdentityPolicy.Resolve(anonymous, Fallback()));
        Assert.Null(OperatorIdentityPolicy.Resolve(null, Fallback()));
    }

    [Fact]
    public void TheFallbackPrincipalIsLabelledAndIsNeverAWindowsOperator()
    {
        var fallback = FallbackPrincipal();

        var identity = OperatorIdentityPolicy.Resolve(fallback, Fallback());
        Assert.Equal(new OperatorIdentity("development-unattributed", "Development operator (unattributed)", "development-unattributed"), identity);

        // Even if its name were allow-listed, a fallback principal is not a Windows operator.
        Assert.Null(OperatorIdentityPolicy.Resolve(fallback, Windows(users: ["development-unattributed"])));
        // And a Windows principal is not the fallback.
        Assert.Null(OperatorIdentityPolicy.Resolve(WindowsPrincipal("HOST\\alice"), Fallback()));
    }

    [Fact]
    public void DisabledAuthorizesNobody()
    {
        var options = new OperatorIdentityOptions { Operators = { AuthorizedUsers = { "HOST\\alice" } } };
        Assert.Null(OperatorIdentityPolicy.Resolve(WindowsPrincipal("HOST\\alice"), options));
        Assert.Null(OperatorIdentityPolicy.Resolve(FallbackPrincipal(), options));
    }

    [Fact]
    public void OnlyTheWindowsModeIsDisclosedAsAttributable()
    {
        Assert.True(OperatorIdentityPolicy.Disclose(Windows(groups: ["BUILTIN\\Users"]), null).Attributable);
        Assert.False(OperatorIdentityPolicy.Disclose(Fallback(), null).Attributable);
        Assert.False(OperatorIdentityPolicy.Disclose(new OperatorIdentityOptions(), null).Attributable);
    }

    [Fact]
    public void ThePayloadHashIsCanonicalAndDeterministic()
    {
        var first = AuditPayload.Sha256(new { Profile = "poc-single-host", Count = 2 });
        Assert.Equal(first, AuditPayload.Sha256(new { Profile = "poc-single-host", Count = 2 }));
        Assert.NotEqual(first, AuditPayload.Sha256(new { Profile = "poc-single-host", Count = 3 }));
        Assert.True(Mavi.Domain.Common.CanonicalSha256.IsCanonical(first));
        Assert.True(Mavi.Domain.Common.CanonicalSha256.IsCanonical(AuditPayload.Sha256(null)));
    }

    private static OperatorIdentityOptions Fallback() => new() { Mode = OperatorIdentityModes.DevelopmentUnattributed };

    private static OperatorIdentityOptions Windows(string[]? groups = null, string[]? users = null) => new()
    {
        Mode = OperatorIdentityModes.WindowsNegotiate,
        Operators = new OperatorAuthorizationOptions { AuthorizedGroups = [.. groups ?? []], AuthorizedUsers = [.. users ?? []] },
    };

    private static ClaimsPrincipal WindowsPrincipal(string name, string? sid = null, string[]? roles = null)
    {
        var claims = new List<Claim> { new(ClaimTypes.Name, name) };
        if (sid is not null)
            claims.Add(new Claim(ClaimTypes.PrimarySid, sid));
        claims.AddRange((roles ?? []).Select(role => new Claim(ClaimTypes.Role, role)));
        return new ClaimsPrincipal(new ClaimsIdentity(claims, "Negotiate"));
    }

    private static ClaimsPrincipal FallbackPrincipal() => new(new ClaimsIdentity(
        [
            new Claim(ClaimTypes.Name, "development-unattributed"),
            new Claim(OperatorIdentityPolicy.IdentitySourceClaim, OperatorIdentityModes.DevelopmentUnattributed),
        ],
        "MaviDevelopmentUnattributed"));
}
