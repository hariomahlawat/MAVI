using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Plates.Release;
using Mavi.Contracts.Worker.Plates;

namespace Mavi.Application.Tests.Plates;

/// <summary>
/// The platform's narrow, fail-closed reading of the plate release: the role and its two bindings, the
/// pipeline profile and its pinned siblings, the bounded v1 profile, and the cross-language identity.
/// </summary>
public sealed class PlateReleaseParserTests
{
    private const string FixtureDirectory = "tests/fixtures/plates";

    private static string Ocr => VectorCapabilities().GetProperty("ocr").GetString()!;
    private static string Detector => VectorCapabilities().GetProperty("plate-detector").GetString()!;

    private static JsonElement VectorCapabilities()
    {
        using var document = JsonDocument.Parse(PlateCompletionValidatorTests.Bytes("contracts/test-vectors/plate-identity-v1.json"));
        return document.RootElement.GetProperty("vectors")[0].GetProperty("capabilities").Clone();
    }

    private static byte[] Text(JsonNode node) => Encoding.UTF8.GetBytes(node.ToJsonString() + "\n");

    internal static JsonObject Binding(bool enabled = true, string? ocrPack = null, string? detectorPack = null) => new()
    {
        ["schemaVersion"] = "mavi-vision-component-binding-v2",
        ["roles"] = new JsonArray(
            new JsonObject
            {
                ["roleId"] = "vision",
                ["capabilityIds"] = new JsonArray("detector"),
                ["provenanceContract"] = "vision-job-complete-v3.3",
            },
            new JsonObject
            {
                ["roleId"] = "plates",
                ["capabilityIds"] = new JsonArray("ocr", "plate-detector"),
                ["provenanceContract"] = PlateContractRules.ProvenanceContract,
            }),
        ["capabilityBindings"] = new JsonArray(
            new JsonObject { ["capabilityId"] = "detector", ["roleId"] = "vision", ["modelPackId"] = "mavi-model-v2-" + new string('7', 64), ["enabled"] = true },
            new JsonObject { ["capabilityId"] = "ocr", ["roleId"] = "plates", ["modelPackId"] = ocrPack ?? Ocr, ["enabled"] = enabled },
            new JsonObject { ["capabilityId"] = "plate-detector", ["roleId"] = "plates", ["modelPackId"] = detectorPack ?? Detector, ["enabled"] = true }),
    };

    private static PlateReleaseResolution Parse(JsonNode binding, byte[]? profile = null, Func<string, byte[]>? sibling = null) =>
        PlateReleaseParser.Parse(Text(binding),
            () => profile ?? PlateCompletionValidatorTests.Bytes($"{FixtureDirectory}/fixture-pipeline-v1.json"),
            sibling ?? (name => PlateCompletionValidatorTests.Bytes($"{FixtureDirectory}/{name}")));

    [Fact]
    public void DerivesTheCrossLanguageIdentityVector()
    {
        var resolution = Parse(Binding());

        Assert.True(resolution.IsConfigured);
        var definition = resolution.Definition!;
        using var vector = JsonDocument.Parse(PlateCompletionValidatorTests.Bytes("contracts/test-vectors/plate-identity-v1.json"));
        var expected = vector.RootElement.GetProperty("vectors")[0];
        Assert.Equal(expected.GetProperty("fingerprint").GetString(), definition.Identity.Fingerprint);
        Assert.Equal(expected.GetProperty("canonicalIdentity").GetString(), definition.Identity.Canonical);
        Assert.Equal("plates", definition.RoleId);
        Assert.True(definition.DevelopmentOnly);
        Assert.Equal((2, 1, 3), (definition.Parameters.MaxDetectionsPerCrop, definition.Parameters.MaxPlatesPerCrop, definition.Parameters.MaxReadingsPerPlate));
        Assert.Equal("mavi-stage4-pr3-fixture-v1", definition.Parameters.FixtureSeed);
        Assert.Equal(PlateReleaseParser.CanonicalCapabilities(definition.Identity.Capabilities), definition.IdentityFields.CapabilitiesCanonical);
    }

    [Fact]
    public void TheIdentityChangesWithEitherModelPack()
    {
        var baseline = Parse(Binding()).Definition!.Identity.Fingerprint;
        Assert.NotEqual(baseline, Parse(Binding(ocrPack: "mavi-model-v2-" + new string('8', 64))).Definition!.Identity.Fingerprint);
        Assert.NotEqual(baseline, Parse(Binding(detectorPack: "mavi-model-v2-" + new string('8', 64))).Definition!.Identity.Fingerprint);
    }

    [Fact]
    public void NoPlateRoleOrADisabledOrMissingBindingConfiguresNothing()
    {
        var withoutRole = Binding();
        withoutRole["roles"]!.AsArray().RemoveAt(1);
        var bindings = withoutRole["capabilityBindings"]!.AsArray();
        bindings.RemoveAt(2);
        bindings.RemoveAt(1);
        Assert.Equal("plate_role_not_bound", Parse(withoutRole).NotConfiguredReason);
        Assert.Equal("plate_binding_disabled", Parse(Binding(enabled: false)).NotConfiguredReason);
        var missing = Binding();
        missing["capabilityBindings"]!.AsArray().RemoveAt(2);
        Assert.Equal("plate_binding_missing", Parse(missing).NotConfiguredReason);
    }

    [Fact]
    public void ARoleMixingCapabilitiesOrServingOnlyOneFailsClosed()
    {
        var mixed = Binding();
        mixed["roles"]![1]!["capabilityIds"] = new JsonArray("ocr", "plate-detector", "person-attributes");
        Assert.Equal("plate_role_mixes_capabilities", Assert.Throws<PlateReleaseException>(() => Parse(mixed)).Code);
        var half = Binding();
        half["roles"]![1]!["capabilityIds"] = new JsonArray("ocr");
        Assert.Equal("plate_role_capabilities_incomplete", Assert.Throws<PlateReleaseException>(() => Parse(half)).Code);
        var contract = Binding();
        contract["roles"]![1]!["provenanceContract"] = "visual-attribute-complete-v1";
        Assert.Equal("plate_role_provenance_contract_unknown", Assert.Throws<PlateReleaseException>(() => Parse(contract)).Code);
    }

    public static TheoryData<string, object, string> ParameterViolations() => new()
    {
        { "maxDetectionsPerCrop", 3, "plate_parameters_invalid:profile_outside_v1_bounds" },
        { "maxPlatesPerCrop", 2, "plate_parameters_invalid:profile_outside_v1_bounds" },
        { "maxReadingsPerPlate", 4, "plate_parameters_invalid:profile_outside_v1_bounds" },
        { "ocrConfidenceFloor", 1.5, "plate_parameters_invalid:ocrConfidenceFloor" },
        { "excludedRoles", "representative", "plate_parameters_invalid:excludedRoles" },
    };

    [Theory]
    [MemberData(nameof(ParameterViolations))]
    public void AProfileOutsideTheBoundedV1ProfileIsRefused(string member, object value, string code)
    {
        var parameters = JsonNode.Parse(PlateCompletionValidatorTests.Bytes($"{FixtureDirectory}/fixture-parameters-v1.json"))!.AsObject();
        parameters[member] = JsonValue.Create(value);
        var parameterBytes = Text(parameters);
        var profile = JsonNode.Parse(PlateCompletionValidatorTests.Bytes($"{FixtureDirectory}/fixture-pipeline-v1.json"))!.AsObject();
        profile["parameters"]!["sha256"] = Convert.ToHexStringLower(SHA256.HashData(parameterBytes));

        var exception = Assert.Throws<PlateReleaseException>(() => Parse(Binding(), Text(profile),
            name => name == "fixture-parameters-v1.json" ? parameterBytes : PlateCompletionValidatorTests.Bytes($"{FixtureDirectory}/{name}")));

        Assert.Equal(code, exception.Code);
    }

    [Fact]
    public void AnotherNormalisationOrATamperedSiblingFailsClosed()
    {
        var profile = JsonNode.Parse(PlateCompletionValidatorTests.Bytes($"{FixtureDirectory}/fixture-pipeline-v1.json"))!.AsObject();
        profile["normalisation"]!["sha256"] = new string('0', 64);
        Assert.Equal("plate_pipeline_invalid:normalisation", Assert.Throws<PlateReleaseException>(() => Parse(Binding(), Text(profile))).Code);

        Assert.Equal("plate_parameters_invalid:sha256_mismatch", Assert.Throws<PlateReleaseException>(() => Parse(Binding(), null,
            name => name == "fixture-parameters-v1.json" ? Encoding.UTF8.GetBytes("{}\n") : PlateCompletionValidatorTests.Bytes($"{FixtureDirectory}/{name}"))).Code);
    }

    [Fact]
    public void ReleaseTextIsLfOnly()
    {
        var crlf = Encoding.UTF8.GetBytes(Binding().ToJsonString().Replace(",", ",\r\n", StringComparison.Ordinal) + "\n");
        Assert.Equal("release_text_cr_forbidden", Assert.Throws<PlateReleaseException>(() =>
            PlateReleaseParser.Parse(crlf, () => null, _ => [])).Code);
    }

    [Fact]
    public void StoredParametersAreReVerifiedAgainstTheirSha()
    {
        var text = Encoding.UTF8.GetString(PlateCompletionValidatorTests.Bytes($"{FixtureDirectory}/fixture-parameters-v1.json"));
        var sha = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
        Assert.Equal(3, PlateReleaseParser.ParseStoredParameters(text, sha).MaxReadingsPerPlate);
        Assert.Throws<PlateReleaseException>(() => PlateReleaseParser.ParseStoredParameters(text + " ", sha));
    }
}
