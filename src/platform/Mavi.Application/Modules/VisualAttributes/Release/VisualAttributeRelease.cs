using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Contracts.Worker.Attributes;
using Mavi.Domain.Common;

namespace Mavi.Application.Modules.VisualAttributes.Release;

/// <summary>A release overlay document the platform refuses; the code is stable and safe to log.</summary>
public sealed class VisualAttributeReleaseException(string code) : Exception(code)
{
    public string Code { get; } = code;
}

public sealed record AttributeDefinition(
    string AttributeType,
    string CapabilityId,
    string ObjectClass,
    IReadOnlyList<string> Values);

public sealed record AttributeSchemaDefinition(
    string SchemaId,
    string Version,
    string Sha256,
    IReadOnlyList<AttributeDefinition> Attributes)
{
    public IReadOnlyList<AttributeDefinition> ForObjectClass(string objectClass) =>
        Attributes.Where(item => string.Equals(item.ObjectClass, objectClass, StringComparison.Ordinal)).ToList();

    public AttributeDefinition? Find(string attributeType) =>
        Attributes.FirstOrDefault(item => string.Equals(item.AttributeType, attributeType, StringComparison.Ordinal));
}

public sealed record CapabilityIdentity(string CapabilityId, string ModelPackId);

/// <summary>The ADR-013 §11 identity without the run; <see cref="Fingerprint"/> is its §16 SHA-256.</summary>
public sealed record VisualAttributeIdentity(
    string Fingerprint,
    string AttributeSchemaId,
    string AttributeSchemaVersion,
    string AttributeSchemaSha256,
    string PipelineId,
    string PipelineVersion,
    string AggregationPolicyId,
    string AggregationPolicyVersion,
    string AggregationPolicySha256,
    IReadOnlyList<CapabilityIdentity> Capabilities,
    string ParametersSha256)
{
    /// <summary>The canonical capability list, as persisted on the analysis header.</summary>
    public string CapabilitiesCanonical => VisualAttributeReleaseParser.CanonicalCapabilities(Capabilities);
}

/// <summary>What the release overlay defines for the attributes role.</summary>
public sealed record VisualAttributeReleaseDefinition(
    VisualAttributeIdentity Identity,
    AttributeSchemaDefinition Schema,
    bool DevelopmentOnly,
    string RoleId,
    string ComponentBindingSha256,
    string PipelineProfileSha256,
    string AttributeSchemaJson);

/// <summary>Either no attribute analysis is configured (and why), or exactly one definition.</summary>
public sealed record VisualAttributeReleaseResolution(
    VisualAttributeReleaseDefinition? Definition,
    string? NotConfiguredReason)
{
    public bool IsConfigured => Definition is not null;

    public static VisualAttributeReleaseResolution NotConfigured(string reason) => new(null, reason);
    public static VisualAttributeReleaseResolution Configured(VisualAttributeReleaseDefinition definition) => new(definition, null);
}

/// <summary>
/// Reads the narrow, fail-closed subset of the release overlay the platform needs (ADR-013
/// implementation amendment 2026-09-28): the attributes role and its enabled capability
/// bindings from the Component Binding, and the attribute pipeline profile with its three
/// SHA-pinned siblings. The worker validates the full binding schema; this parser refuses
/// anything malformed in the members it reads and never guesses.
/// </summary>
/// <remarks>
/// The identity encoding is the pack-identity encoding shared with the worker: sorted keys,
/// compact separators, ASCII only, one trailing LF. Every value in it is a validated ASCII
/// token or hex digest, so writing the members in their sorted order is exact.
/// <c>contracts/test-vectors/visual-attribute-identity-v1.json</c> pins both languages to it.
/// </remarks>
public static class VisualAttributeReleaseParser
{
    public const string ComponentBindingSchema = "mavi-vision-component-binding-v2";
    public const string PipelineSchema = "mavi-visual-attribute-pipeline-v1";
    public const string AttributeSchemaSchema = "mavi-visual-attribute-schema-v1";
    public const string AggregationSchema = "mavi-visual-attribute-aggregation-v1";
    public const string ParametersSchema = "mavi-visual-attribute-parameters-v1";
    public const string IdentitySchema = "mavi-visual-attribute-identity-v1";

    private static readonly Dictionary<string, string> CapabilityObjectClass =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            [VisualAttributeContractRules.CapabilityPersonAttributes] = VisualAttributeContractRules.ObjectClassPerson,
            [VisualAttributeContractRules.CapabilityVehicleAttributes] = VisualAttributeContractRules.ObjectClassVehicle,
        };

    public static VisualAttributeReleaseResolution Parse(
        byte[] componentBindingBytes,
        Func<byte[]?> readPipelineProfile,
        Func<string, byte[]> readPipelineSibling)
    {
        ArgumentNullException.ThrowIfNull(componentBindingBytes);
        ArgumentNullException.ThrowIfNull(readPipelineProfile);
        ArgumentNullException.ThrowIfNull(readPipelineSibling);

        using var binding = ParseReleaseJson(componentBindingBytes, "component_binding_invalid");
        var root = binding.RootElement;
        if (ReadString(root, "schemaVersion", "component_binding_invalid") != ComponentBindingSchema)
            throw new VisualAttributeReleaseException("component_binding_invalid");

        var roles = ReadArray(root, "roles", "component_binding_invalid");
        (string RoleId, IReadOnlyList<string> CapabilityIds)? attributeRole = null;
        foreach (var role in roles.EnumerateArray())
        {
            var capabilityIds = ReadArray(role, "capabilityIds", "component_binding_invalid")
                .EnumerateArray()
                .Select(item => item.ValueKind == JsonValueKind.String
                    ? item.GetString()!
                    : throw new VisualAttributeReleaseException("component_binding_invalid"))
                .ToList();
            var attributeCount = capabilityIds.Count(VisualAttributeContractRules.IsAttributeCapability);
            if (attributeCount == 0) continue;
            if (attributeCount != capabilityIds.Count)
                throw new VisualAttributeReleaseException("attribute_role_mixes_capabilities");
            if (attributeRole is not null)
                throw new VisualAttributeReleaseException("attribute_role_ambiguous");
            if (capabilityIds.Distinct(StringComparer.Ordinal).Count() != capabilityIds.Count)
                throw new VisualAttributeReleaseException("component_binding_invalid");
            if (ReadString(role, "provenanceContract", "component_binding_invalid") != VisualAttributeContractRules.ProvenanceContract)
                throw new VisualAttributeReleaseException("attribute_role_provenance_contract_unknown");
            attributeRole = (ReadString(role, "roleId", "component_binding_invalid"), capabilityIds);
        }

        if (attributeRole is not { } found)
            return VisualAttributeReleaseResolution.NotConfigured("attribute_role_not_bound");

        var modelPacks = new SortedDictionary<string, string>(StringComparer.Ordinal);
        foreach (var capabilityBinding in ReadArray(root, "capabilityBindings", "component_binding_invalid").EnumerateArray())
        {
            if (ReadString(capabilityBinding, "roleId", "component_binding_invalid") != found.RoleId) continue;
            var capabilityId = ReadString(capabilityBinding, "capabilityId", "component_binding_invalid");
            if (!found.CapabilityIds.Contains(capabilityId, StringComparer.Ordinal))
                throw new VisualAttributeReleaseException("component_binding_invalid");
            if (!capabilityBinding.TryGetProperty("enabled", out var enabled) ||
                enabled.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
                throw new VisualAttributeReleaseException("component_binding_invalid");
            var modelPackId = ReadString(capabilityBinding, "modelPackId", "component_binding_invalid");
            if (!IsModelPackId(modelPackId))
                throw new VisualAttributeReleaseException("component_binding_invalid");
            if (!modelPacks.TryAdd(capabilityId, modelPackId))
                throw new VisualAttributeReleaseException("component_binding_invalid");
            // A disabled binding keeps its role from starting (ADR-014 §1), so no analysis
            // can run under this release: nothing is expected, nothing is queued.
            if (enabled.ValueKind == JsonValueKind.False)
                return VisualAttributeReleaseResolution.NotConfigured("attribute_binding_disabled");
        }

        if (modelPacks.Count != found.CapabilityIds.Count)
            return VisualAttributeReleaseResolution.NotConfigured("attribute_binding_missing");

        var profileBytes = readPipelineProfile()
            ?? throw new VisualAttributeReleaseException("attribute_pipeline_profile_required");
        var profile = ParseProfile(profileBytes, readPipelineSibling);
        if (!modelPacks.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(profile.Schema.Attributes.Select(item => item.CapabilityId)))
            throw new VisualAttributeReleaseException("attribute_capabilities_schema_mismatch");

        var capabilities = modelPacks.Select(pair => new CapabilityIdentity(pair.Key, pair.Value)).ToList();
        var identity = BuildIdentity(profile, capabilities);
        return VisualAttributeReleaseResolution.Configured(new VisualAttributeReleaseDefinition(
            identity,
            profile.Schema,
            profile.DevelopmentOnly,
            found.RoleId,
            Sha256Hex(componentBindingBytes),
            Sha256Hex(profileBytes),
            profile.AttributeSchemaJson));
    }

    // --- Pipeline profile ----------------------------------------------------------------

    private sealed record ParsedProfile(
        string AttributeSchemaJson,
        string PipelineId,
        string PipelineVersion,
        bool DevelopmentOnly,
        AttributeSchemaDefinition Schema,
        string AggregationPolicyId,
        string AggregationPolicyVersion,
        string AggregationPolicySha256,
        string ParametersSha256);

    private static ParsedProfile ParseProfile(byte[] profileBytes, Func<string, byte[]> readSibling)
    {
        const string code = "attribute_pipeline_invalid";
        using var document = ParseReleaseJson(profileBytes, code);
        var root = document.RootElement;
        RequireExactKeys(root, code, "schemaVersion", "pipelineId", "pipelineVersion", "developmentOnly",
            "attributeSchema", "aggregationPolicy", "parameters");
        if (ReadString(root, "schemaVersion", code) != PipelineSchema)
            throw new VisualAttributeReleaseException(code);
        var developmentOnly = root.GetProperty("developmentOnly");
        if (developmentOnly.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
            throw new VisualAttributeReleaseException($"{code}:developmentOnly");

        var (schemaBytes, schemaSha256) = ReadPinnedSibling(root.GetProperty("attributeSchema"), readSibling, "attribute_schema_invalid");
        var (aggregationBytes, aggregationSha256) = ReadPinnedSibling(root.GetProperty("aggregationPolicy"), readSibling, "aggregation_policy_invalid");
        var (parametersBytes, parametersSha256) = ReadPinnedSibling(root.GetProperty("parameters"), readSibling, "attribute_parameters_invalid");

        var schema = ParseSchema(schemaBytes, schemaSha256);
        string aggregationId, aggregationVersion;
        using (var aggregation = ParseReleaseJson(aggregationBytes, "aggregation_policy_invalid"))
        {
            var element = aggregation.RootElement;
            RequireExactKeys(element, "aggregation_policy_invalid", "schemaVersion", "aggregationPolicyId",
                "aggregationPolicyVersion", "method", "minimumConfidence");
            if (ReadString(element, "schemaVersion", "aggregation_policy_invalid") != AggregationSchema ||
                ReadString(element, "method", "aggregation_policy_invalid") != "mean-score-argmax")
                throw new VisualAttributeReleaseException("aggregation_policy_invalid");
            if (element.GetProperty("minimumConfidence") is not { ValueKind: JsonValueKind.Number } minimum ||
                !minimum.TryGetDouble(out var value) || value is < 0 or > 1)
                throw new VisualAttributeReleaseException("aggregation_policy_invalid:minimumConfidence");
            aggregationId = Token(element, "aggregationPolicyId", "aggregation_policy_invalid:aggregationPolicyId");
            aggregationVersion = Version(element, "aggregationPolicyVersion", "aggregation_policy_invalid:aggregationPolicyVersion");
        }

        using (var parameters = ParseReleaseJson(parametersBytes, "attribute_parameters_invalid"))
        {
            var element = parameters.RootElement;
            RequireExactKeys(element, "attribute_parameters_invalid", "schemaVersion", "parameters");
            if (ReadString(element, "schemaVersion", "attribute_parameters_invalid") != ParametersSchema ||
                element.GetProperty("parameters").ValueKind != JsonValueKind.Object)
                throw new VisualAttributeReleaseException("attribute_parameters_invalid");
        }

        return new ParsedProfile(
            Encoding.UTF8.GetString(schemaBytes),
            Token(root, "pipelineId", $"{code}:pipelineId"),
            Version(root, "pipelineVersion", $"{code}:pipelineVersion"),
            developmentOnly.ValueKind == JsonValueKind.True,
            schema,
            aggregationId,
            aggregationVersion,
            aggregationSha256,
            parametersSha256);
    }

    /// <summary>
    /// Re-reads a schema the platform stored at activation, verifying it is still exactly the
    /// bytes the identity pins (ADR-013 §11: the schema SHA is part of the identity).
    /// </summary>
    public static AttributeSchemaDefinition ParseStoredSchema(string attributeSchemaJson, string expectedSha256)
    {
        ArgumentNullException.ThrowIfNull(attributeSchemaJson);
        var bytes = Encoding.UTF8.GetBytes(attributeSchemaJson);
        if (!string.Equals(Sha256Hex(bytes), expectedSha256, StringComparison.Ordinal))
            throw new VisualAttributeReleaseException("attribute_schema_invalid:sha256_mismatch");
        return ParseSchema(bytes, expectedSha256);
    }

    private static AttributeSchemaDefinition ParseSchema(byte[] bytes, string sha256)
    {
        const string code = "attribute_schema_invalid";
        using var document = ParseReleaseJson(bytes, code);
        var root = document.RootElement;
        RequireExactKeys(root, code, "schemaVersion", "attributeSchemaId", "attributeSchemaVersion", "attributes");
        if (ReadString(root, "schemaVersion", code) != AttributeSchemaSchema)
            throw new VisualAttributeReleaseException(code);
        var attributes = root.GetProperty("attributes");
        if (attributes.ValueKind != JsonValueKind.Array ||
            attributes.GetArrayLength() is < 1 or > VisualAttributeContractRules.MaximumSchemaAttributeTypes)
            throw new VisualAttributeReleaseException($"{code}:attributes");

        var parsed = new List<AttributeDefinition>();
        foreach (var item in attributes.EnumerateArray())
        {
            RequireExactKeys(item, $"{code}:attributes", "attributeType", "capabilityId", "objectClass", "values");
            var attributeType = Token(item, "attributeType", $"{code}:attributeType");
            var capabilityId = ReadString(item, "capabilityId", $"{code}:capabilityId");
            if (!CapabilityObjectClass.TryGetValue(capabilityId, out var objectClass))
                throw new VisualAttributeReleaseException($"{code}:capabilityId");
            if (ReadString(item, "objectClass", $"{code}:objectClass") != objectClass)
                throw new VisualAttributeReleaseException($"{code}:objectClass");
            var values = item.GetProperty("values");
            if (values.ValueKind != JsonValueKind.Array ||
                values.GetArrayLength() is < 1 or > VisualAttributeContractRules.MaximumAttributeValues)
                throw new VisualAttributeReleaseException($"{code}:values");
            var tokens = values.EnumerateArray()
                .Select(value => value.ValueKind == JsonValueKind.String && VisualAttributeContractRules.IsSchemaToken(value.GetString())
                    ? value.GetString()!
                    : throw new VisualAttributeReleaseException($"{code}:values"))
                .ToList();
            if (!tokens.SequenceEqual(tokens.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal)))
                throw new VisualAttributeReleaseException($"{code}:values_order");
            parsed.Add(new AttributeDefinition(attributeType, capabilityId, objectClass, tokens));
        }

        var names = parsed.Select(item => item.AttributeType).ToList();
        if (!names.SequenceEqual(names.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal)))
            throw new VisualAttributeReleaseException($"{code}:attributes_order");
        if (parsed.GroupBy(item => item.ObjectClass, StringComparer.Ordinal)
            .Any(group => group.Count() > VisualAttributeContractRules.MaximumAttributeTypesPerObjectClass))
            throw new VisualAttributeReleaseException($"{code}:object_class_limit");

        return new AttributeSchemaDefinition(
            Token(root, "attributeSchemaId", $"{code}:attributeSchemaId"),
            Version(root, "attributeSchemaVersion", $"{code}:attributeSchemaVersion"),
            sha256,
            parsed);
    }

    private static (byte[] Bytes, string Sha256) ReadPinnedSibling(JsonElement reference, Func<string, byte[]> readSibling, string code)
    {
        if (reference.ValueKind != JsonValueKind.Object) throw new VisualAttributeReleaseException(code);
        RequireExactKeys(reference, code, "file", "sha256");
        var name = ReadString(reference, "file", code);
        var sha256 = ReadString(reference, "sha256", code);
        if (!IsSiblingFileName(name) || !CanonicalSha256.IsCanonical(sha256))
            throw new VisualAttributeReleaseException(code);
        byte[] bytes;
        try
        {
            bytes = readSibling(name);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            throw new VisualAttributeReleaseException($"{code}:unreadable");
        }

        if (!string.Equals(Sha256Hex(bytes), sha256, StringComparison.Ordinal))
            throw new VisualAttributeReleaseException($"{code}:sha256_mismatch");
        return (bytes, sha256);
    }

    // --- Identity ------------------------------------------------------------------------

    private static VisualAttributeIdentity BuildIdentity(ParsedProfile profile, IReadOnlyList<CapabilityIdentity> capabilities)
    {
        var canonical = CanonicalIdentity(
            profile.AggregationPolicyId, profile.AggregationPolicySha256, profile.AggregationPolicyVersion,
            profile.Schema.SchemaId, profile.Schema.Sha256, profile.Schema.Version,
            capabilities, profile.ParametersSha256, profile.PipelineId, profile.PipelineVersion);
        return new VisualAttributeIdentity(
            Sha256Hex(Encoding.ASCII.GetBytes(canonical)),
            profile.Schema.SchemaId,
            profile.Schema.Version,
            profile.Schema.Sha256,
            profile.PipelineId,
            profile.PipelineVersion,
            profile.AggregationPolicyId,
            profile.AggregationPolicyVersion,
            profile.AggregationPolicySha256,
            capabilities,
            profile.ParametersSha256);
    }

    /// <summary>The canonical identity text, trailing LF included; exposed for the cross-language vector.</summary>
    public static string CanonicalIdentity(VisualAttributeIdentity identity)
    {
        ArgumentNullException.ThrowIfNull(identity);
        return CanonicalIdentity(
            identity.AggregationPolicyId, identity.AggregationPolicySha256, identity.AggregationPolicyVersion,
            identity.AttributeSchemaId, identity.AttributeSchemaSha256, identity.AttributeSchemaVersion,
            identity.Capabilities, identity.ParametersSha256, identity.PipelineId, identity.PipelineVersion);
    }

    private static string CanonicalIdentity(
        string aggregationId, string aggregationSha256, string aggregationVersion,
        string schemaId, string schemaSha256, string schemaVersion,
        IReadOnlyList<CapabilityIdentity> capabilities, string parametersSha256,
        string pipelineId, string pipelineVersion)
    {
        var builder = new StringBuilder(512);
        builder.Append("{\"aggregationPolicy\":{\"id\":\"").Append(aggregationId)
            .Append("\",\"sha256\":\"").Append(aggregationSha256)
            .Append("\",\"version\":\"").Append(aggregationVersion)
            .Append("\"},\"attributeSchema\":{\"id\":\"").Append(schemaId)
            .Append("\",\"sha256\":\"").Append(schemaSha256)
            .Append("\",\"version\":\"").Append(schemaVersion)
            .Append("\"},\"capabilities\":").Append(CanonicalCapabilities(capabilities))
            .Append(",\"parametersSha256\":\"").Append(parametersSha256)
            .Append("\",\"pipeline\":{\"id\":\"").Append(pipelineId)
            .Append("\",\"version\":\"").Append(pipelineVersion)
            .Append("\"},\"schemaVersion\":\"").Append(IdentitySchema)
            .Append("\"}\n");
        return builder.ToString();
    }

    public static string CanonicalCapabilities(IReadOnlyList<CapabilityIdentity> capabilities)
    {
        ArgumentNullException.ThrowIfNull(capabilities);
        var builder = new StringBuilder(256).Append('[');
        for (var index = 0; index < capabilities.Count; index++)
        {
            if (index > 0) builder.Append(',');
            builder.Append("{\"capabilityId\":\"").Append(capabilities[index].CapabilityId)
                .Append("\",\"modelPackId\":\"").Append(capabilities[index].ModelPackId).Append("\"}");
        }

        return builder.Append(']').ToString();
    }

    // --- JSON helpers --------------------------------------------------------------------

    /// <summary>UTF-8, LF-only, no BOM, and no duplicate member anywhere (the worker's release-text rules).</summary>
    private static JsonDocument ParseReleaseJson(byte[] bytes, string code)
    {
        if (bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF)
            throw new VisualAttributeReleaseException("release_text_bom_forbidden");
        if (Array.IndexOf(bytes, (byte)'\r') >= 0)
            throw new VisualAttributeReleaseException("release_text_cr_forbidden");
        JsonDocument document;
        try
        {
            _ = new UTF8Encoding(false, throwOnInvalidBytes: true).GetCharCount(bytes);
            document = JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 16 });
        }
        catch (Exception exception) when (exception is JsonException or DecoderFallbackException or ArgumentException)
        {
            throw new VisualAttributeReleaseException(code);
        }

        if (document.RootElement.ValueKind != JsonValueKind.Object || HasDuplicateMembers(document.RootElement))
        {
            document.Dispose();
            throw new VisualAttributeReleaseException(code);
        }

        return document;
    }

    private static bool HasDuplicateMembers(JsonElement element)
    {
        switch (element.ValueKind)
        {
            case JsonValueKind.Object:
                var names = new HashSet<string>(StringComparer.Ordinal);
                foreach (var property in element.EnumerateObject())
                {
                    if (!names.Add(property.Name) || HasDuplicateMembers(property.Value)) return true;
                }
                return false;
            case JsonValueKind.Array:
                return element.EnumerateArray().Any(HasDuplicateMembers);
            default:
                return false;
        }
    }

    private static void RequireExactKeys(JsonElement element, string code, params string[] keys)
    {
        if (element.ValueKind != JsonValueKind.Object) throw new VisualAttributeReleaseException(code);
        var actual = element.EnumerateObject().Select(property => property.Name).ToHashSet(StringComparer.Ordinal);
        if (!actual.SetEquals(keys)) throw new VisualAttributeReleaseException(code);
    }

    private static string ReadString(JsonElement element, string name, string code) =>
        element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.String &&
        value.GetString() is { Length: > 0 } text
            ? text
            : throw new VisualAttributeReleaseException(code);

    private static JsonElement ReadArray(JsonElement element, string name, string code) =>
        element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.Array
            ? value
            : throw new VisualAttributeReleaseException(code);

    private static string Token(JsonElement element, string name, string code)
    {
        var value = ReadString(element, name, code);
        return VisualAttributeContractRules.IsSchemaToken(value) ? value : throw new VisualAttributeReleaseException(code);
    }

    private static string Version(JsonElement element, string name, string code)
    {
        var value = ReadString(element, name, code);
        var parts = value.Split('.');
        return value.Length <= VisualAttributeContractRules.MaximumTokenLength &&
               parts.Length == 3 &&
               parts.All(part => part.Length > 0 && part.All(char.IsAsciiDigit))
            ? value
            : throw new VisualAttributeReleaseException(code);
    }

    private static bool IsSiblingFileName(string name) =>
        name is { Length: >= 6 and <= 128 } &&
        name.EndsWith(".json", StringComparison.Ordinal) &&
        name[0] is (>= 'a' and <= 'z') or (>= '0' and <= '9') &&
        !name.Contains("..", StringComparison.Ordinal) &&
        name.All(character => character is (>= 'a' and <= 'z') or (>= '0' and <= '9') or '.' or '-');

    private static bool IsModelPackId(string value) =>
        value.StartsWith("mavi-model-v2-", StringComparison.Ordinal) &&
        CanonicalSha256.IsCanonical(value["mavi-model-v2-".Length..]);

    private static string Sha256Hex(byte[] bytes) => CanonicalSha256.ToHex(SHA256.HashData(bytes));
}
