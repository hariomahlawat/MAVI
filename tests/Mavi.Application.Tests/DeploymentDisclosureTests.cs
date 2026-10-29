using System.Text.Json;
using Mavi.Application.Deployment;
using Mavi.Application.Modules.Identity;

namespace Mavi.Application.Tests;

/// <summary>
/// ADR-020 §3: under <c>poc-single-host</c> the disclosure (profile, not Production-qualified,
/// evidence class Development) is machine-checked and cannot be configured away.
/// </summary>
public sealed class DeploymentDisclosureTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"mavi-deployment-{Guid.NewGuid():N}");

    public DeploymentDisclosureTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); }
        catch (IOException) { }
    }

    [Fact]
    public void PocProfileDisclosesTheFixedStatementPacksAndDevice()
    {
        var options = PocOptions(WriteMetadata(ValidMetadata()), WriteDevice());

        DeploymentDisclosureReader.Verify(options);
        var disclosure = DeploymentDisclosureReader.Read(options);

        Assert.Equal(DeploymentProfiles.PocSingleHost, disclosure.Profile);
        Assert.False(disclosure.ProductionQualified);
        Assert.Equal("Development", disclosure.EvidenceClass);
        Assert.Contains("Not Production-qualified", disclosure.Statement, StringComparison.Ordinal);
        Assert.Equal("verified", disclosure.MetadataStatus);
        Assert.Equal(new string('a', 40), disclosure.ApplicationRevision);
        var pack = Assert.Single(disclosure.Packs);
        Assert.Equal("mavi-model-v2-x", pack.PackId);
        Assert.Equal("unverified", pack.VerificationStatus);
        Assert.Equal("reported", disclosure.DeviceStatus);
        Assert.NotNull(disclosure.Device);
        Assert.Equal("auto", disclosure.Device!.RequestedPolicy);
        Assert.Equal("cpu", disclosure.Device.ResolvedPolicy);
        Assert.Equal("cuda_pack_absent", disclosure.Device.Reason);
    }

    [Theory]
    [InlineData("productionQualified", "true")]
    [InlineData("evidenceClass", "\"Production\"")]
    [InlineData("profile", "\"P3\"")]
    [InlineData("schemaVersion", "\"mavi-poc-release-metadata-v0\"")]
    public void PocHostRefusesMetadataThatClaimsAnotherDisclosure(string property, string json)
    {
        var metadata = ValidMetadata();
        metadata[property] = JsonDocument.Parse(json).RootElement.Clone();
        var options = PocOptions(WriteMetadata(metadata), null);

        Assert.Throws<DeploymentDisclosureException>(() => DeploymentDisclosureReader.Verify(options));

        // A file edited after start-up cannot remove the disclosure either: it is reported
        // as unavailable and the fixed statement is still served.
        var disclosure = DeploymentDisclosureReader.Read(options);
        Assert.False(disclosure.ProductionQualified);
        Assert.Equal("Development", disclosure.EvidenceClass);
        Assert.Equal(DeploymentProfiles.PocSingleHost, disclosure.Profile);
        Assert.Equal("unavailable", disclosure.MetadataStatus);
    }

    [Fact]
    public void PocHostRequiresReleaseMetadata()
    {
        var missing = PocOptions(Path.Combine(_root, "absent.json"), null);
        Assert.Throws<DeploymentDisclosureException>(() => DeploymentDisclosureReader.Verify(missing));
        Assert.Throws<DeploymentDisclosureException>(() =>
            DeploymentDisclosureReader.Verify(new DeploymentOptions { Profile = DeploymentProfiles.PocSingleHost }));

        var disclosure = DeploymentDisclosureReader.Read(missing);
        Assert.False(disclosure.ProductionQualified);
        Assert.NotNull(disclosure.Statement);
    }

    [Fact]
    public void MetadataMembersThatTryToHideTheDisclosureAreIgnored()
    {
        var metadata = ValidMetadata();
        metadata["disclosure"] = JsonDocument.Parse("false").RootElement.Clone();
        metadata["hideBanner"] = JsonDocument.Parse("true").RootElement.Clone();
        metadata["statement"] = JsonDocument.Parse("\"Production ready\"").RootElement.Clone();
        var options = PocOptions(WriteMetadata(metadata), null);

        DeploymentDisclosureReader.Verify(options);
        var disclosure = DeploymentDisclosureReader.Read(options);

        Assert.Equal(PocDisclosure.Statement, disclosure.Statement);
        Assert.False(disclosure.ProductionQualified);
    }

    [Fact]
    public void TheOptionsOfferNoSwitchThatCouldHideTheDisclosure()
    {
        // The only configurable inputs are where the profile and its records are. Adding a
        // member here (an "enabled", "hide" or "qualified" switch) must fail this test.
        var members = typeof(DeploymentOptions).GetProperties().Select(property => property.Name).Order(StringComparer.Ordinal);
        Assert.Equal(["DeviceResolutionPath", "Profile", "ReleaseMetadataPath", "RoleDeviceResolutionPaths"], members);
    }

    [Theory]
    [InlineData("P1")]
    [InlineData("P3")]
    [InlineData("Production")]
    [InlineData("POC-SINGLE-HOST")]
    public void AnUndeclarableProfileFailsClosed(string profile)
    {
        var options = new DeploymentOptions { Profile = profile };
        Assert.Throws<DeploymentDisclosureException>(() => DeploymentDisclosureReader.Verify(options));
        Assert.Throws<DeploymentDisclosureException>(() => DeploymentDisclosureReader.Read(options));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void APocBuildKeepsTheDisclosureWhenConfigurationClearsTheProfile(string? configured)
    {
        // The PoC bundle builds the platform with MaviDeploymentProfile=poc-single-host; an
        // empty Deployment__Profile environment variable or a deleted key cannot unprofile it.
        var options = new DeploymentOptions
        {
            Profile = configured,
            ReleaseMetadataPath = WriteMetadata(ValidMetadata()),
        };

        DeploymentDisclosureReader.Verify(options, DeploymentProfiles.PocSingleHost);
        var disclosure = DeploymentDisclosureReader.Read(options, DeploymentProfiles.PocSingleHost);

        Assert.Equal(DeploymentProfiles.PocSingleHost, disclosure.Profile);
        Assert.False(disclosure.ProductionQualified);
        Assert.Equal(PocDisclosure.Statement, disclosure.Statement);
        Assert.Throws<DeploymentDisclosureException>(() =>
            DeploymentDisclosureReader.Verify(new DeploymentOptions(), DeploymentProfiles.PocSingleHost));
    }

    [Fact]
    public void ConfigurationCannotContradictTheBuildProfile()
    {
        var options = new DeploymentOptions { Profile = "P3", ReleaseMetadataPath = WriteMetadata(ValidMetadata()) };
        Assert.Throws<DeploymentDisclosureException>(() => DeploymentDisclosureReader.Verify(options, DeploymentProfiles.PocSingleHost));
        Assert.Throws<DeploymentDisclosureException>(() => DeploymentDisclosureReader.Verify(new DeploymentOptions(), "P1"));
    }

    [Fact]
    public void AnUnprofiledHostMakesNoProfileClaim()
    {
        var disclosure = DeploymentDisclosureReader.Read(new DeploymentOptions());

        Assert.Equal(DeploymentProfiles.Unspecified, disclosure.Profile);
        Assert.False(disclosure.ProductionQualified);
        Assert.Null(disclosure.Statement);
        Assert.Equal("not-configured", disclosure.MetadataStatus);
        Assert.Equal("not-reported", disclosure.DeviceStatus);
    }

    [Fact]
    public void TheIdentityModeInEffectIsDisclosedBesideTheOneInstalled()
    {
        var metadata = ValidMetadata();
        metadata["identityMode"] = JsonDocument.Parse("\"windows-negotiate\"").RootElement.Clone();
        var identity = new OperatorIdentityOptions { Mode = OperatorIdentityModes.DevelopmentUnattributed };

        var disclosure = DeploymentDisclosureReader.Read(PocOptions(WriteMetadata(metadata), null), identity: identity);

        Assert.Equal(OperatorIdentityModes.DevelopmentUnattributed, disclosure.Identity.Mode);
        Assert.False(disclosure.Identity.Attributable);
        Assert.Contains("not attributable", disclosure.Identity.Statement, StringComparison.Ordinal);
        Assert.Equal(OperatorIdentityModes.WindowsNegotiate, disclosure.Identity.InstalledMode);
    }

    [Fact]
    public void AnUnconfiguredIdentityIsDisclosedAsDisabled()
    {
        var disclosure = DeploymentDisclosureReader.Read(new DeploymentOptions());

        Assert.Equal(OperatorIdentityModes.Disabled, disclosure.Identity.Mode);
        Assert.False(disclosure.Identity.Attributable);
        Assert.False(disclosure.Identity.OperatorsConfigured);
        Assert.Null(disclosure.Identity.InstalledMode);
    }

    [Fact]
    public void AMalformedDeviceRecordIsUnavailableNotAbsent()
    {
        var device = Path.Combine(_root, "device.json");
        File.WriteAllText(device, "{\"schemaVersion\":\"mavi-device-resolution-v1\",\"requestedDevicePolicy\":\"auto\"}");
        var disclosure = DeploymentDisclosureReader.Read(PocOptions(WriteMetadata(ValidMetadata()), device));

        Assert.Equal("unavailable", disclosure.DeviceStatus);
        Assert.Null(disclosure.Device);
    }

    [Fact]
    public void ARoleRuntimeDisclosesItsOwnDeviceAndReasonBesideTheVisionWorker()
    {
        // PoC S3 (C4.1): the plates runtime resolves its device itself; its record is shown as its own, with its
        // reason, and never replaces the Vision worker's.
        var plates = Path.Combine(_root, "plates-device-resolution.json");
        File.WriteAllText(plates, """
            {
              "schemaVersion": "mavi-device-resolution-v1",
              "role": "plates",
              "requestedDevicePolicy": "auto",
              "resolvedDevicePolicy": "cpu",
              "deviceResolutionReason": "plates_runtime_cpu_only",
              "runtimePackId": "mavi-runtime-v2-plates",
              "runtimeVariant": "windows-x86_64-cpu",
              "verifyOnly": false
            }
            """);
        var options = PocOptions(WriteMetadata(ValidMetadata()), WriteDevice());
        options.RoleDeviceResolutionPaths["plates"] = plates;
        options.RoleDeviceResolutionPaths["embeddings"] = Path.Combine(_root, "absent.json");
        // A record is only its own role's: the plates record named for another role is not shown as that role's.
        options.RoleDeviceResolutionPaths["faces"] = plates;

        var disclosure = DeploymentDisclosureReader.Read(options);

        Assert.Equal("cuda_pack_absent", disclosure.Device!.Reason);
        Assert.NotNull(disclosure.RoleDevices);
        Assert.Equal(["embeddings", "faces", "plates"], disclosure.RoleDevices!.Select(item => item.Role));
        Assert.Equal("not-reported", disclosure.RoleDevices[0].DeviceStatus);
        Assert.Equal(("unavailable", null), (disclosure.RoleDevices[1].DeviceStatus, disclosure.RoleDevices[1].Device));
        var role = disclosure.RoleDevices[2];
        Assert.Equal("reported", role.DeviceStatus);
        Assert.Equal("auto", role.Device!.RequestedPolicy);
        Assert.Equal("cpu", role.Device.ResolvedPolicy);
        Assert.Equal("plates_runtime_cpu_only", role.Device.Reason);
        Assert.Equal("mavi-runtime-v2-plates", role.Device.RuntimePackId);
    }

    [Fact]
    public void APackDisclosesTheLicenceItsInstallerReadFromTheLicenceFile()
    {
        var metadata = ValidMetadata();
        metadata["packs"] = JsonDocument.Parse("""
            [
              { "kind": "model", "role": "plates", "capabilityId": "ocr", "packId": "mavi-model-v2-ocr",
                "verificationStatus": "unverified", "licence": "MIT (LICENSE a953e626)" },
              { "kind": "model", "role": "vision", "packId": "mavi-model-v2-x", "verificationStatus": "unverified" }
            ]
            """).RootElement.Clone();

        var disclosure = DeploymentDisclosureReader.Read(PocOptions(WriteMetadata(metadata), null));

        Assert.Equal("MIT (LICENSE a953e626)", disclosure.Packs[0].Licence);
        Assert.Null(disclosure.Packs[1].Licence);
    }

    private static DeploymentOptions PocOptions(string metadataPath, string? devicePath) => new()
    {
        Profile = DeploymentProfiles.PocSingleHost,
        ReleaseMetadataPath = metadataPath,
        DeviceResolutionPath = devicePath,
    };

    private static Dictionary<string, JsonElement> ValidMetadata()
    {
        const string json = """
            {
              "schemaVersion": "mavi-poc-release-metadata-v1",
              "profile": "poc-single-host",
              "productionQualified": false,
              "evidenceClass": "Development",
              "installedAtUtc": "2026-10-28T00:00:00Z",
              "application": { "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" },
              "packs": [
                { "kind": "model", "role": "vision", "capabilityId": "detector", "packId": "mavi-model-v2-x", "verificationStatus": "unverified" }
              ]
            }
            """;
        return JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(json)!;
    }

    private string WriteMetadata(Dictionary<string, JsonElement> metadata)
    {
        var path = Path.Combine(_root, $"release-{Guid.NewGuid():N}.json");
        File.WriteAllText(path, JsonSerializer.Serialize(metadata));
        return path;
    }

    private string WriteDevice()
    {
        var path = Path.Combine(_root, "device-resolution.json");
        File.WriteAllText(path, """
            {
              "schemaVersion": "mavi-device-resolution-v1",
              "requestedDevicePolicy": "auto",
              "resolvedDevicePolicy": "cpu",
              "deviceResolutionReason": "cuda_pack_absent",
              "runtimePackId": "mavi-runtime-v2-cpu",
              "runtimeVariant": "windows-x86_64-cpu",
              "verifyOnly": true
            }
            """);
        return path;
    }
}
