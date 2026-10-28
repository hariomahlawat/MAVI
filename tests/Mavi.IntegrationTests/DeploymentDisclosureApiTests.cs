using System.Net;
using System.Text.Json;
using Mavi.Application.Deployment;

namespace Mavi.IntegrationTests;

/// <summary>
/// ADR-020 §3 at the HTTP boundary: a <c>poc-single-host</c> platform serves the fixed
/// disclosure whatever else is configured, and refuses to start on metadata that claims
/// another one.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class DeploymentDisclosureApiTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"mavi-deployment-api-{Guid.NewGuid():N}");

    public DeploymentDisclosureApiTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); }
        catch (IOException) { }
    }

    [Fact]
    public async Task PocHostServesTheDisclosureEvenWhenConfigurationTriesToHideIt()
    {
        var metadata = WriteMetadata(productionQualified: false);
        using var factory = new ApiTestFactory
        {
            AdditionalConfiguration = new Dictionary<string, string?>
            {
                ["Deployment:Profile"] = DeploymentProfiles.PocSingleHost,
                ["Deployment:ReleaseMetadataPath"] = metadata,
                // Keys an operator might try; the host has no such switch and ignores them.
                ["Deployment:Disclosure"] = "false",
                ["Deployment:HideBanner"] = "true",
                ["Deployment:ProductionQualified"] = "true",
                ["Deployment:EvidenceClass"] = "Production",
            },
        };
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();

        using var response = await client.GetAsync("/api/system/deployment");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var root = document.RootElement;
        Assert.Equal("mavi-deployment-disclosure-v1", root.GetProperty("schemaVersion").GetString());
        Assert.Equal("poc-single-host", root.GetProperty("profile").GetString());
        Assert.False(root.GetProperty("productionQualified").GetBoolean());
        Assert.Equal("Development", root.GetProperty("evidenceClass").GetString());
        Assert.Contains("Not Production-qualified", root.GetProperty("statement").GetString(), StringComparison.Ordinal);
        Assert.Equal("verified", root.GetProperty("metadataStatus").GetString());
        Assert.Equal("not-reported", root.GetProperty("deviceStatus").GetString());
        Assert.Equal(1, root.GetProperty("packs").GetArrayLength());
    }

    [Fact]
    public void PocHostRefusesToStartOnMetadataClaimingProductionQualification()
    {
        var metadata = WriteMetadata(productionQualified: true);
        using var factory = new ApiTestFactory
        {
            AdditionalConfiguration = new Dictionary<string, string?>
            {
                ["Deployment:Profile"] = DeploymentProfiles.PocSingleHost,
                ["Deployment:ReleaseMetadataPath"] = metadata,
            },
        };

        var exception = Assert.ThrowsAny<Exception>(() => factory.CreateClient());
        Assert.Contains("productionQualified must be false", exception.ToString(), StringComparison.Ordinal);
    }

    private string WriteMetadata(bool productionQualified)
    {
        var path = Path.Combine(_root, $"release-{Guid.NewGuid():N}.json");
        File.WriteAllText(path, $$"""
            {
              "schemaVersion": "mavi-poc-release-metadata-v1",
              "profile": "poc-single-host",
              "productionQualified": {{(productionQualified ? "true" : "false")}},
              "evidenceClass": "Development",
              "application": { "revision": "{{new string('b', 40)}}" },
              "packs": [
                { "kind": "runtime", "role": "vision", "packId": "mavi-runtime-v2-cpu", "variant": "windows-x86_64-cpu", "verificationStatus": "qualified-development" }
              ]
            }
            """);
        return path;
    }
}
