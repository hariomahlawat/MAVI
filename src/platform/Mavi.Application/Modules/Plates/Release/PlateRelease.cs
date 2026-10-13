
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Common;
using Mavi.Domain.Plates;

namespace Mavi.Application.Modules.Plates.Release;

/// <summary>A plate release document the platform refuses; the code is stable and safe to log.</summary>
public sealed class PlateReleaseException(string code) : Exception(code)
{
    public string Code { get; } = code;
}

/// <summary>
/// The identity-bearing parameters <c>mavi-plate-parameters-v1</c> (ADR-013 implementation amendment
/// 2026-10-13, items 11, 13, 14): the bounded v1 processing profile, the two confidence floors and the
/// evidence roles the profile excludes.
/// </summary>
public sealed record PlateParameters(
    int MaxDetectionsPerCrop,
    int MaxPlatesPerCrop,
    int MaxReadingsPerPlate,
    double DetectorConfidenceFloor,
    double OcrConfidenceFloor,
    IReadOnlySet<string> ExcludedRoles,
    string? FixtureSeed);

/// <summary>The Track-text summary policy <c>mavi-plate-summary-policy-v1</c>.</summary>
public sealed record PlateSummaryPolicy(string Id, string Version, string Sha256, string Method);

/// <summary>What the release defines for the <c>plates</c> role.</summary>
public sealed record PlateReleaseDefinition(
    PlateIdentity Identity,
    PlateParameters Parameters,
    PlateSummaryPolicy SummaryPolicy,
    bool DevelopmentOnly,
    string RoleId,
    string ComponentBindingSha256,
    string PipelineProfileSha256,
    string ParametersJson,
    string SummaryPolicyJson)
{
    public PlateIdentityFields IdentityFields => new(
        Identity.Fingerprint,
        Identity.PipelineId,
        Identity.PipelineVersion,
        Identity.PredictionsSchemaVersion,
        Identity.NormalisationId,
        Identity.NormalisationSha256,
        Identity.SummaryPolicyId,
        Identity.SummaryPolicyVersion,
        Identity.SummaryPolicySha256,
        PlateReleaseParser.CanonicalCapabilities(Identity.Capabilities),
        Identity.ParametersSha256);
}

/// <summary>Either no plate analysis is configured (and why), or exactly one definition.</summary>
public sealed record PlateReleaseResolution(PlateReleaseDefinition? Definition, string? NotConfiguredReason)
{
    public bool IsConfigured => Definition is not null;

    public static PlateReleaseResolution NotConfigured(string reason) => new(null, reason);
    public static PlateReleaseResolution Configured(PlateReleaseDefinition definition) => new(definition, null);
}

/// <summary>
/// Reads the narrow, fail-closed subset of the release the platform needs for plates: the role serving
/// <c>ocr</c> and <c>plate-detector</c> and its two enabled capability bindings from the Component
/// Binding, and the plate pipeline profile with its two SHA-pinned siblings. The identity is
/// <see cref="PlateIdentity"/>; <c>contracts/test-vectors/plate-identity-v1.json</c> pins both languages.
/// </summary>
/// <remarks>
/// Capability-specific (ADR-013 item 11): the release-text rules (UTF-8, LF only, no BOM, no duplicate
/// member) are the attribute parser's, repeated here rather than shared, so neither plane can change
/// the other's release semantics.
/// </remarks>
public static class PlateReleaseParser
{
    public const string ComponentBindingSchema = "mavi-vision-component-binding-v2";
    public const string PipelineSchema = "mavi-plate-pipeline-v1";
    public const string SummaryPolicySchema = "mavi-plate-summary-policy-v1";
    public const string ParametersSchema = "mavi-plate-parameters-v1";
    public const string SummaryMethod = "distinct-rank0-normalised-text";

    public static PlateReleaseResolution Parse(
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
            throw new PlateReleaseException("component_binding_invalid");

        (string RoleId, IReadOnlyList<string> CapabilityIds)? plateRole = null;
        foreach (var role in ReadArray(root, "roles", "component_binding_invalid").EnumerateArray())
        {
            var capabilityIds = ReadArray(role, "capabilityIds", "component_binding_invalid")
                .EnumerateArray()
                .Select(item => item.ValueKind == JsonValueKind.String
                    ? item.GetString()!
                    : throw new PlateReleaseException("component_binding_invalid"))
                .ToList();
            var plateCount = capabilityIds.Count(PlateContractRules.IsPlateCapability);
            if (plateCount == 0) continue;
            if (plateCount != capabilityIds.Count)
                throw new PlateReleaseException("plate_role_mixes_capabilities");
            if (plateRole is not null)
                throw new PlateReleaseException("plate_role_ambiguous");
            if (!capabilityIds.Order(StringComparer.Ordinal).SequenceEqual(PlateContractRules.Capabilities, StringComparer.Ordinal))
                throw new PlateReleaseException("plate_role_capabilities_incomplete");
            if (ReadString(role, "provenanceContract", "component_binding_invalid") != PlateContractRules.ProvenanceContract)
                throw new PlateReleaseException("plate_role_provenance_contract_unknown");
            plateRole = (ReadString(role, "roleId", "component_binding_invalid"), capabilityIds);
        }

        if (plateRole is not { } found)
            return PlateReleaseResolution.NotConfigured("plate_role_not_bound");

        var modelPacks = new SortedDictionary<string, string>(StringComparer.Ordinal);
        foreach (var capabilityBinding in ReadArray(root, "capabilityBindings", "component_binding_invalid").EnumerateArray())
        {
            if (ReadString(capabilityBinding, "roleId", "component_binding_invalid") != found.RoleId) continue;
            var capabilityId = ReadString(capabilityBinding, "capabilityId", "component_binding_invalid");
            if (!found.CapabilityIds.Contains(capabilityId, StringComparer.Ordinal))
                throw new PlateReleaseException("component_binding_invalid");
            if (!capabilityBinding.TryGetProperty("enabled", out var enabled) ||
                enabled.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
                throw new PlateReleaseException("component_binding_invalid");
            var modelPackId = ReadString(capabilityBinding, "modelPackId", "component_binding_invalid");
            if (!IsModelPackId(modelPackId) || !modelPacks.TryAdd(capabilityId, modelPackId))
                throw new PlateReleaseException("component_binding_invalid");
            // A disabled binding keeps its role from starting (ADR-014 §1): nothing is expected or queued.
            if (enabled.ValueKind == JsonValueKind.False)
                return PlateReleaseResolution.NotConfigured("plate_binding_disabled");
        }

        if (modelPacks.Count != PlateContractRules.Capabilities.Count)
            return PlateReleaseResolution.NotConfigured("plate_binding_missing");

        var profileBytes = readPipelineProfile() ?? throw new PlateReleaseException("plate_pipeline_profile_required");
        var profile = ParseProfile(profileBytes, readPipelineSibling);
        var identity = PlateIdentity.Create(
            profile.PipelineId,
            profile.PipelineVersion,
            profile.SummaryPolicy.Id,
            profile.SummaryPolicy.Version,
            profile.SummaryPolicy.Sha256,
            modelPacks.Select(pair => new PlateCapabilityIdentity(pair.Key, pair.Value)).ToList(),
            profile.ParametersSha256);
        return PlateReleaseResolution.Configured(new PlateReleaseDefinition(
            identity,
            profile.Parameters,
            profile.SummaryPolicy,
            profile.DevelopmentOnly,
            found.RoleId,
            Sha256Hex(componentBindingBytes),
            Sha256Hex(profileBytes),
            profile.ParametersJson,
            profile.SummaryPolicyJson));
    }

    /// <summary>The canonical capability list persisted on the analysis header (the identity's own encoding).</summary>
    public static string CanonicalCapabilities(IReadOnlyList<PlateCapabilityIdentity> capabilities)
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

    // --- Pipeline profile ----------------------------------------------------------------

    private sealed record ParsedProfile(
        string PipelineId,
        string PipelineVersion,
        bool DevelopmentOnly,
        PlateSummaryPolicy SummaryPolicy,
        string SummaryPolicyJson,
        PlateParameters Parameters,
        string ParametersJson,
        string ParametersSha256);

    private static ParsedProfile ParseProfile(byte[] profileBytes, Func<string, byte[]> readSibling)
    {
        const string code = "plate_pipeline_invalid";
        using var document = ParseReleaseJson(profileBytes, code);
        var root = document.RootElement;
        RequireExactKeys(root, code, "schemaVersion", "pipelineId", "pipelineVersion", "developmentOnly",
            "predictionsSchemaVersion", "normalisation", "summaryPolicy", "parameters");
        if (ReadString(root, "schemaVersion", code) != PipelineSchema)
            throw new PlateReleaseException(code);
        var developmentOnly = root.GetProperty("developmentOnly");
        if (developmentOnly.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
            throw new PlateReleaseException($"{code}:developmentOnly");
        if (ReadString(root, "predictionsSchemaVersion", code) != PlateContractRules.PredictionsSchemaVersion)
            throw new PlateReleaseException($"{code}:predictionsSchemaVersion");
        var normalisation = root.GetProperty("normalisation");
        RequireExactKeys(normalisation, $"{code}:normalisation", "id", "sha256");
        if (ReadString(normalisation, "id", $"{code}:normalisation") != PlateContractRules.NormalisationId ||
            ReadString(normalisation, "sha256", $"{code}:normalisation") != PlateContractRules.NormalisationSha256)
            throw new PlateReleaseException($"{code}:normalisation");

        var (summaryBytes, summarySha256) = ReadPinnedSibling(root.GetProperty("summaryPolicy"), readSibling, "plate_summary_policy_invalid");
        var (parameterBytes, parametersSha256) = ReadPinnedSibling(root.GetProperty("parameters"), readSibling, "plate_parameters_invalid");

        return new ParsedProfile(
            Token(root, "pipelineId", $"{code}:pipelineId"),
            Version(root, "pipelineVersion", $"{code}:pipelineVersion"),
            developmentOnly.ValueKind == JsonValueKind.True,
            ParseSummaryPolicy(summaryBytes, summarySha256),
            Encoding.UTF8.GetString(summaryBytes),
            ParseParameters(parameterBytes),
            Encoding.UTF8.GetString(parameterBytes),
            parametersSha256);
    }

    /// <summary>
    /// Re-reads parameters the platform stored at activation, verifying they are still exactly the bytes
    /// the identity pins: a unit of an obsolete identity is validated against its own profile.
    /// </summary>
    public static PlateParameters ParseStoredParameters(string parametersJson, string expectedSha256)
    {
        ArgumentNullException.ThrowIfNull(parametersJson);
        var bytes = Encoding.UTF8.GetBytes(parametersJson);
        if (!string.Equals(Sha256Hex(bytes), expectedSha256, StringComparison.Ordinal))
            throw new PlateReleaseException("plate_parameters_invalid:sha256_mismatch");
        return ParseParameters(bytes);
    }

    public static PlateParameters ParseParameters(byte[] bytes)
    {
        const string code = "plate_parameters_invalid";
        using var document = ParseReleaseJson(bytes, code);
        var root = document.RootElement;
        var keys = root.EnumerateObject().Select(property => property.Name).ToHashSet(StringComparer.Ordinal);
        string[] required = ["schemaVersion", "maxDetectionsPerCrop", "maxPlatesPerCrop", "maxReadingsPerPlate",
            "detectorConfidenceFloor", "ocrConfidenceFloor", "excludedRoles"];
        if (!required.All(keys.Contains) || keys.Except(required).Any(key => key != "fixtureSeed"))
            throw new PlateReleaseException(code);
        if (ReadString(root, "schemaVersion", code) != ParametersSchema)
            throw new PlateReleaseException(code);

        int Integer(string name) =>
            root.GetProperty(name) is { ValueKind: JsonValueKind.Number } value && value.TryGetInt32(out var number)
                ? number
                : throw new PlateReleaseException($"{code}:{name}");
        double Floor(string name) =>
            root.GetProperty(name) is { ValueKind: JsonValueKind.Number } value && value.TryGetDouble(out var number) &&
            double.IsFinite(number) && number is >= 0 and <= 1
                ? number
                : throw new PlateReleaseException($"{code}:{name}");

        var detections = Integer("maxDetectionsPerCrop");
        var plates = Integer("maxPlatesPerCrop");
        var readings = Integer("maxReadingsPerPlate");
        if (!PlateContractRules.IsAdmissibleProfileShape(detections, plates, readings))
            throw new PlateReleaseException($"{code}:profile_outside_v1_bounds");

        var roles = root.GetProperty("excludedRoles");
        if (roles.ValueKind != JsonValueKind.Array) throw new PlateReleaseException($"{code}:excludedRoles");
        var excluded = new HashSet<string>(StringComparer.Ordinal);
        foreach (var role in roles.EnumerateArray())
        {
            if (role.ValueKind != JsonValueKind.String || !PlateContractRules.IsEvidenceRole(role.GetString()) || !excluded.Add(role.GetString()!))
                throw new PlateReleaseException($"{code}:excludedRoles");
        }

        string? seed = null;
        if (root.TryGetProperty("fixtureSeed", out var seedElement))
        {
            seed = seedElement.ValueKind == JsonValueKind.String && seedElement.GetString() is { Length: > 0 } text
                ? text
                : throw new PlateReleaseException($"{code}:fixtureSeed");
        }

        return new PlateParameters(detections, plates, readings, Floor("detectorConfidenceFloor"), Floor("ocrConfidenceFloor"), excluded, seed);
    }

    private static PlateSummaryPolicy ParseSummaryPolicy(byte[] bytes, string sha256)
    {
        const string code = "plate_summary_policy_invalid";
        using var document = ParseReleaseJson(bytes, code);
        var root = document.RootElement;
        RequireExactKeys(root, code, "schemaVersion", "summaryPolicyId", "summaryPolicyVersion", "method");
        if (ReadString(root, "schemaVersion", code) != SummaryPolicySchema ||
            ReadString(root, "method", $"{code}:method") != SummaryMethod)
            throw new PlateReleaseException(code);
        return new PlateSummaryPolicy(
            Token(root, "summaryPolicyId", $"{code}:summaryPolicyId"),
            Version(root, "summaryPolicyVersion", $"{code}:summaryPolicyVersion"),
            sha256,
            SummaryMethod);
    }

    private static (byte[] Bytes, string Sha256) ReadPinnedSibling(JsonElement reference, Func<string, byte[]> readSibling, string code)
    {
        if (reference.ValueKind != JsonValueKind.Object) throw new PlateReleaseException(code);
        RequireExactKeys(reference, code, "file", "sha256");
        var name = ReadString(reference, "file", code);
        var sha256 = ReadString(reference, "sha256", code);
        if (!IsSiblingFileName(name) || !CanonicalSha256.IsCanonical(sha256))
            throw new PlateReleaseException(code);
        byte[] bytes;
        try
        {
            bytes = readSibling(name);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            throw new PlateReleaseException($"{code}:unreadable");
        }

        if (!string.Equals(Sha256Hex(bytes), sha256, StringComparison.Ordinal))
            throw new PlateReleaseException($"{code}:sha256_mismatch");
        return (bytes, sha256);
    }

    // --- JSON helpers (the attribute parser's release-text rules) -------------------------

    private static JsonDocument ParseReleaseJson(byte[] bytes, string code)
    {
        if (bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF)
            throw new PlateReleaseException("release_text_bom_forbidden");
        if (Array.IndexOf(bytes, (byte)'\r') >= 0)
            throw new PlateReleaseException("release_text_cr_forbidden");
        JsonDocument document;
        try
        {
            _ = new UTF8Encoding(false, throwOnInvalidBytes: true).GetCharCount(bytes);
            document = JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 16 });
        }
        catch (Exception exception) when (exception is JsonException or DecoderFallbackException or ArgumentException)
        {
            throw new PlateReleaseException(code);
        }

        if (document.RootElement.ValueKind != JsonValueKind.Object || HasDuplicateMembers(document.RootElement))
        {
            document.Dispose();
            throw new PlateReleaseException(code);
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
        if (element.ValueKind != JsonValueKind.Object) throw new PlateReleaseException(code);
        var actual = element.EnumerateObject().Select(property => property.Name).ToHashSet(StringComparer.Ordinal);
        if (!actual.SetEquals(keys)) throw new PlateReleaseException(code);
    }

    private static string ReadString(JsonElement element, string name, string code) =>
        element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.String &&
        value.GetString() is { Length: > 0 } text
            ? text
            : throw new PlateReleaseException(code);

    private static JsonElement ReadArray(JsonElement element, string name, string code) =>
        element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.Array
            ? value
            : throw new PlateReleaseException(code);

    private static string Token(JsonElement element, string name, string code)
    {
        var value = ReadString(element, name, code);
        return IsToken(value) ? value : throw new PlateReleaseException(code);
    }

    private static string Version(JsonElement element, string name, string code)
    {
        var value = ReadString(element, name, code);
        var parts = value.Split('.');
        return value.Length <= PlateContractRules.MaximumTokenLength &&
               parts.Length == 3 &&
               parts.All(part => part.Length > 0 && part.All(char.IsAsciiDigit))
            ? value
            : throw new PlateReleaseException(code);
    }

    private static bool IsToken(string value) =>
        value.Length is >= 1 and <= PlateContractRules.MaximumTokenLength &&
        value[0] is >= 'a' and <= 'z' && value[^1] != '-' &&
        !value.Contains("--", StringComparison.Ordinal) &&
        value.All(character => character is >= 'a' and <= 'z' or >= '0' and <= '9' or '-');

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
