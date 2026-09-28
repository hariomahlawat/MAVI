using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.VisualAttributes.Release;

namespace Mavi.IntegrationTests;

/// <summary>
/// Development overlays for integration tests: the shipped Component Binding plus an
/// <c>attributes</c> role bound to fixture Model Pack ids, over the committed fixture profile.
/// </summary>
internal static class VisualAttributeReleaseFixture
{
    public static readonly string Root = FindRepositoryRoot();
    public static readonly string FixtureDirectory = Path.Combine(Root, "tests", "fixtures", "visual-attributes");
    public static readonly string ShippedBinding = Path.Combine(Root, "src", "vision", "config", "components", "phase1-bindings-v2.json");
    public static readonly string PipelineProfile = Path.Combine(FixtureDirectory, "fixture-pipeline-v1.json");

    public const string PersonPackA = "mavi-model-v2-1111111111111111111111111111111111111111111111111111111111111111";
    public const string VehiclePackA = "mavi-model-v2-2222222222222222222222222222222222222222222222222222222222222222";
    public const string VehiclePackB = "mavi-model-v2-3333333333333333333333333333333333333333333333333333333333333333";

    /// <summary>Identity A (the cross-language vector's) or identity B (another vehicle Model Pack).</summary>
    public static VisualAttributeReleaseDefinition Definition(bool identityB = false) =>
        VisualAttributeReleaseParser.Parse(
            BindingBytes(PersonPackA, identityB ? VehiclePackB : VehiclePackA),
            () => File.ReadAllBytes(PipelineProfile),
            name => File.ReadAllBytes(Path.Combine(FixtureDirectory, name))).Definition!;

    public static byte[] BindingBytes(string personPack, string vehiclePack)
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
        bindings.Add(Bound("person-attributes", personPack));
        bindings.Add(Bound("vehicle-attributes", vehiclePack));
        return Encoding.UTF8.GetBytes(binding.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n");
    }

    /// <summary>Writes a binding for identity A or B to a file, for hosts configured by path.</summary>
    public static string WriteBinding(string directory, bool identityB = false)
    {
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, identityB ? "binding-b.json" : "binding-a.json");
        File.WriteAllBytes(path, BindingBytes(PersonPackA, identityB ? VehiclePackB : VehiclePackA));
        return path;
    }

    /// <summary>
    /// A Development pipeline profile over another attribute schema (the fixture's aggregation
    /// policy and parameters), for worst-shape measurements: the Python and .NET loaders read it
    /// exactly as they read the committed fixture.
    /// </summary>
    public static string WriteProfile(string directory, IReadOnlyDictionary<string, string[]> typesByClass)
    {
        Directory.CreateDirectory(directory);
        foreach (var name in new[] { "fixture-aggregation-policy-v1.json", "fixture-parameters-v1.json" })
            File.Copy(Path.Combine(FixtureDirectory, name), Path.Combine(directory, name), overwrite: true);
        var attributes = new JsonArray();
        foreach (var (objectClass, types) in typesByClass.SelectMany(pair => pair.Value.Select(type => (pair.Key, type)))
                     .OrderBy(item => item.type, StringComparer.Ordinal))
        {
            attributes.Add(new JsonObject
            {
                ["attributeType"] = types,
                ["capabilityId"] = objectClass + "-attributes",
                ["objectClass"] = objectClass,
                ["values"] = new JsonArray("dark", "light", "mid"),
            });
        }

        var schema = new JsonObject
        {
            ["schemaVersion"] = "mavi-visual-attribute-schema-v1",
            ["attributeSchemaId"] = "visual-attributes-worst-shape",
            ["attributeSchemaVersion"] = "1.0.0",
            ["attributes"] = attributes,
        };
        var schemaBytes = Encoding.UTF8.GetBytes(schema.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n");
        File.WriteAllBytes(Path.Combine(directory, "worst-shape-schema-v1.json"), schemaBytes);
        var profile = JsonNode.Parse(File.ReadAllText(PipelineProfile))!.AsObject();
        profile["attributeSchema"] = new JsonObject
        {
            ["file"] = "worst-shape-schema-v1.json",
            ["sha256"] = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(schemaBytes)),
        };
        var path = Path.Combine(directory, "worst-shape-pipeline-v1.json");
        File.WriteAllText(path, profile.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n");
        return path;
    }

    private static JsonObject Bound(string capabilityId, string modelPackId) => new()
    {
        ["capabilityId"] = capabilityId,
        ["roleId"] = "attributes",
        ["modelPackId"] = modelPackId,
        ["qualificationId"] = capabilityId + "-fixture",
        ["enabled"] = true,
    };

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "MAVI.sln")))
            directory = directory.Parent;
        return directory?.FullName ?? throw new DirectoryNotFoundException("Could not locate MAVI.sln.");
    }
}
