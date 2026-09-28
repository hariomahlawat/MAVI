using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.VisualAttributes.Release;

namespace Mavi.Application.Tests.VisualAttributes;

/// <summary>
/// The platform's narrow read of the release overlay (ADR-013 implementation amendment
/// 2026-09-28): it derives the same identity as the worker from the same bytes, and refuses
/// anything malformed in what it reads.
/// </summary>
public sealed class VisualAttributeReleaseParserTests
{
    internal static readonly string Root = CompletionDigestGoldenTests.FindRepositoryRoot();
    internal static readonly string FixtureDirectory = Path.Combine(Root, "tests", "fixtures", "visual-attributes");
    internal static readonly string ShippedBinding = Path.Combine(Root, "src", "vision", "config", "components", "phase1-bindings-v2.json");
    internal static readonly string PersonPack = "mavi-model-v2-" + new string('1', 64);
    internal static readonly string VehiclePack = "mavi-model-v2-" + new string('2', 64);

    /// <summary>The shipped binding plus an <c>attributes</c> role, as a Development overlay adds it.</summary>
    internal static byte[] BindingWithAttributesRole(
        bool personEnabled = true,
        bool vehicleEnabled = true,
        Action<JsonObject>? mutate = null)
    {
        var binding = JsonNode.Parse(File.ReadAllText(ShippedBinding))!.AsObject();
        binding["roles"]!.AsArray().Add(new JsonObject
        {
            ["roleId"] = "attributes",
            ["runtimePackFamilyId"] = "mmdetection-phase1-v1",
            ["capabilityIds"] = new JsonArray("person-attributes", "vehicle-attributes"),
            ["entryPoint"] = "mavi_vision.attributes.main",
            ["readinessContract"] = "worker-health-v2",
            ["provenanceContract"] = "visual-attribute-complete-v1",
        });
        var bindings = binding["capabilityBindings"]!.AsArray();
        bindings.Add(Bound("person-attributes", PersonPack, personEnabled));
        bindings.Add(Bound("vehicle-attributes", VehiclePack, vehicleEnabled));
        mutate?.Invoke(binding);
        return Encoding.UTF8.GetBytes(binding.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n");
    }

    private static JsonObject Bound(string capabilityId, string modelPackId, bool enabled) => new()
    {
        ["capabilityId"] = capabilityId,
        ["roleId"] = "attributes",
        ["modelPackId"] = modelPackId,
        ["qualificationId"] = capabilityId + "-fixture",
        ["enabled"] = enabled,
    };

    internal static VisualAttributeReleaseResolution ParseFixture(byte[] binding, Func<string, byte[]>? sibling = null, byte[]? profile = null) =>
        VisualAttributeReleaseParser.Parse(
            binding,
            () => profile ?? File.ReadAllBytes(Path.Combine(FixtureDirectory, "fixture-pipeline-v1.json")),
            sibling ?? (name => File.ReadAllBytes(Path.Combine(FixtureDirectory, name))));

    [Fact]
    public void DerivesTheCrossLanguageIdentityVector()
    {
        using var vectors = JsonDocument.Parse(File.ReadAllText(
            Path.Combine(Root, "contracts", "test-vectors", "visual-attribute-identity-v1.json")));
        var vector = vectors.RootElement.GetProperty("vectors")[0];
        Assert.Equal(PersonPack, vector.GetProperty("capabilities").GetProperty("person-attributes").GetString());
        Assert.Equal(VehiclePack, vector.GetProperty("capabilities").GetProperty("vehicle-attributes").GetString());

        var resolution = ParseFixture(BindingWithAttributesRole());

        Assert.True(resolution.IsConfigured);
        var definition = resolution.Definition!;
        Assert.Equal(vector.GetProperty("canonicalIdentity").GetString(), VisualAttributeReleaseParser.CanonicalIdentity(definition.Identity));
        Assert.Equal(vector.GetProperty("fingerprint").GetString(), definition.Identity.Fingerprint);
        Assert.True(definition.DevelopmentOnly);
        Assert.Equal("attributes", definition.RoleId);
        Assert.Equal(["person-attributes", "vehicle-attributes"], definition.Identity.Capabilities.Select(item => item.CapabilityId));
        Assert.Equal(3, definition.Schema.Attributes.Count);
        Assert.Equal(2, definition.Schema.ForObjectClass("person").Count);
    }

    [Fact]
    public void TheShippedBindingConfiguresNoAttributeAnalysis()
    {
        // The release binding has no attributes role (plan §20: no binding identity change),
        // so a platform pointed at it expects nothing and reads no pipeline profile.
        var resolution = VisualAttributeReleaseParser.Parse(
            File.ReadAllBytes(ShippedBinding),
            () => throw new InvalidOperationException("The profile must not be read."),
            _ => throw new InvalidOperationException("No sibling must be read."));

        Assert.False(resolution.IsConfigured);
        Assert.Equal("attribute_role_not_bound", resolution.NotConfiguredReason);
    }

    [Theory]
    [InlineData(false, true)]
    [InlineData(true, false)]
    public void ADisabledBindingConfiguresNothing(bool person, bool vehicle)
    {
        var resolution = ParseFixture(BindingWithAttributesRole(person, vehicle));
        Assert.Equal("attribute_binding_disabled", resolution.NotConfiguredReason);
    }

    [Fact]
    public void AMissingCapabilityBindingConfiguresNothing()
    {
        var binding = BindingWithAttributesRole(mutate: root => root["capabilityBindings"]!.AsArray().RemoveAt(root["capabilityBindings"]!.AsArray().Count - 1));
        Assert.Equal("attribute_binding_missing", ParseFixture(binding).NotConfiguredReason);
    }

    [Fact]
    public void TheIdentityChangesWithTheBoundModelPack()
    {
        var baseline = ParseFixture(BindingWithAttributesRole()).Definition!.Identity.Fingerprint;
        var other = ParseFixture(BindingWithAttributesRole(mutate: root =>
            root["capabilityBindings"]!.AsArray().Last()!["modelPackId"] = "mavi-model-v2-" + new string('3', 64))).Definition!.Identity.Fingerprint;
        Assert.NotEqual(baseline, other);
    }

    public static TheoryData<string, string> SiblingTampering => new()
    {
        { "fixture-attribute-schema-v1.json", "attribute_schema_invalid:sha256_mismatch" },
        { "fixture-aggregation-policy-v1.json", "aggregation_policy_invalid:sha256_mismatch" },
        { "fixture-parameters-v1.json", "attribute_parameters_invalid:sha256_mismatch" },
    };

    [Theory]
    [MemberData(nameof(SiblingTampering))]
    public void ATamperedSiblingFailsClosed(string file, string code)
    {
        var exception = Assert.Throws<VisualAttributeReleaseException>(() => ParseFixture(
            BindingWithAttributesRole(),
            name =>
            {
                var bytes = File.ReadAllBytes(Path.Combine(FixtureDirectory, name));
                return name == file ? [.. bytes, (byte)' '] : bytes;
            }));
        Assert.Equal(code, exception.Code);
    }

    [Fact]
    public void ACarriageReturnFailsClosed()
    {
        var binding = Encoding.UTF8.GetString(BindingWithAttributesRole()).Replace("\n", "\r\n", StringComparison.Ordinal);
        var exception = Assert.Throws<VisualAttributeReleaseException>(() => ParseFixture(Encoding.UTF8.GetBytes(binding)));
        Assert.Equal("release_text_cr_forbidden", exception.Code);
    }

    [Fact]
    public void ADuplicateMemberFailsClosed()
    {
        var binding = Encoding.UTF8.GetString(BindingWithAttributesRole());
        var duplicated = binding.Replace("\"bindingId\":", "\"bindingId\": \"x\", \"bindingId\":", StringComparison.Ordinal);
        var exception = Assert.Throws<VisualAttributeReleaseException>(() => ParseFixture(Encoding.UTF8.GetBytes(duplicated)));
        Assert.Equal("component_binding_invalid", exception.Code);
    }

    [Fact]
    public void ARoleMixingAttributeAndOtherCapabilitiesFailsClosed()
    {
        var binding = BindingWithAttributesRole(mutate: root =>
            root["roles"]!.AsArray().Last()!["capabilityIds"]!.AsArray().Add("ocr"));
        var exception = Assert.Throws<VisualAttributeReleaseException>(() => ParseFixture(binding));
        Assert.Equal("attribute_role_mixes_capabilities", exception.Code);
    }

    [Fact]
    public void ARoleDeclaringAnotherProvenanceContractFailsClosed()
    {
        var binding = BindingWithAttributesRole(mutate: root =>
            root["roles"]!.AsArray().Last()!["provenanceContract"] = "vision-job-complete-v3.2");
        var exception = Assert.Throws<VisualAttributeReleaseException>(() => ParseFixture(binding));
        Assert.Equal("attribute_role_provenance_contract_unknown", exception.Code);
    }

    [Fact]
    public void BindingsThatDoNotServeExactlyTheSchemaFailClosed()
    {
        // The schema's attributes are served by both capabilities; a role serving only one
        // would leave attributes with no producer.
        var binding = BindingWithAttributesRole(mutate: root =>
        {
            root["roles"]!.AsArray().Last()!["capabilityIds"] = new JsonArray("person-attributes");
            root["capabilityBindings"]!.AsArray().RemoveAt(root["capabilityBindings"]!.AsArray().Count - 1);
        });
        var exception = Assert.Throws<VisualAttributeReleaseException>(() => ParseFixture(binding));
        Assert.Equal("attribute_capabilities_schema_mismatch", exception.Code);
    }

    [Fact]
    public void AConfiguredRoleWithoutAProfileFailsClosed()
    {
        var exception = Assert.Throws<VisualAttributeReleaseException>(() => VisualAttributeReleaseParser.Parse(
            BindingWithAttributesRole(), () => null, _ => []));
        Assert.Equal("attribute_pipeline_profile_required", exception.Code);
    }

    [Theory]
    [InlineData("../fixture-attribute-schema-v1.json")]
    [InlineData("sub/fixture-attribute-schema-v1.json")]
    [InlineData("Fixture-attribute-schema-v1.json")]
    public void ASiblingOutsideTheProfileDirectoryIsRefused(string file)
    {
        var profile = File.ReadAllText(Path.Combine(FixtureDirectory, "fixture-pipeline-v1.json"))
            .Replace("\"fixture-attribute-schema-v1.json\"", JsonSerializer.Serialize(file), StringComparison.Ordinal);
        var exception = Assert.Throws<VisualAttributeReleaseException>(() =>
            ParseFixture(BindingWithAttributesRole(), profile: Encoding.UTF8.GetBytes(profile)));
        Assert.Equal("attribute_schema_invalid", exception.Code);
    }
}
