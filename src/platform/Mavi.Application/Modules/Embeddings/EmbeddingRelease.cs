using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Contracts.Worker.Embeddings;
using Mavi.Domain.Embeddings;

namespace Mavi.Application.Modules.Embeddings;

/// <summary>The resolved embedding release: the identity, the profile parameters the platform applies.</summary>
public sealed record EmbeddingReleaseDefinition(
    EmbeddingIdentityFields Identity,
    string CanonicalIdentity,
    bool DevelopmentOnly,
    int MinimumCropSide,
    IReadOnlyList<string> ObjectClasses);

/// <summary>Either no release (not configured), a definition, or a refusal code.</summary>
public sealed record EmbeddingReleaseResolution(EmbeddingReleaseDefinition? Definition, string? RefusalCode)
{
    public static readonly EmbeddingReleaseResolution NotConfigured = new(null, null);
}

public interface IEmbeddingRelease
{
    EmbeddingReleaseResolution Resolution { get; }
}

/// <summary>
/// Parses the model manifest and pipeline profile into the identity of ADR-021 §3. The canonical identity is
/// the compact, key-sorted JSON the Python worker writes (<c>contracts/test-vectors/embedding-identity-v1.json</c>),
/// with a trailing LF; its SHA-256 is the fingerprint. Identity strings are restricted to printable ASCII without
/// quotes or backslashes, so no JSON escaping is involved and both stacks produce the same bytes.
/// </summary>
public static class EmbeddingReleaseParser
{
    public const string InvalidCode = "embedding_release_invalid";

    public static EmbeddingReleaseResolution Parse(byte[] manifestBytes, byte[] profileBytes)
    {
        ArgumentNullException.ThrowIfNull(manifestBytes);
        ArgumentNullException.ThrowIfNull(profileBytes);
        try
        {
            using var manifest = JsonDocument.Parse(manifestBytes);
            using var profile = JsonDocument.Parse(profileBytes);
            var m = manifest.RootElement;
            var p = profile.RootElement;
            if (Text(m, "schemaVersion") != "2.0" ||
                !m.TryGetProperty("capabilityIds", out var capabilities) ||
                capabilities.ValueKind != JsonValueKind.Array ||
                !capabilities.EnumerateArray().Any(item => item.GetString() == "embedding") ||
                !m.TryGetProperty("capabilitySpecific", out var specific) ||
                !specific.TryGetProperty("embedding", out var section) ||
                !section.TryGetProperty("dimension", out var dimensionElement) ||
                !dimensionElement.TryGetInt32(out var dimension))
                return Refused();

            if (Text(p, "schemaVersion") != EmbeddingContractRules.PipelineSchemaVersion ||
                !p.TryGetProperty("dimension", out var profileDimension) || !profileDimension.TryGetInt32(out var pd) || pd != dimension ||
                !p.TryGetProperty("minimumCropSide", out var floorElement) || !floorElement.TryGetInt32(out var floor) || floor is < 1 or > 4096 ||
                !p.TryGetProperty("developmentOnly", out var devElement) || devElement.ValueKind is not (JsonValueKind.True or JsonValueKind.False) ||
                !p.TryGetProperty("objectClasses", out var classesElement) || classesElement.ValueKind != JsonValueKind.Array)
                return Refused();

            var classes = classesElement.EnumerateArray().Select(item => item.GetString() ?? string.Empty).ToList();
            if (classes.Count == 0 || classes.Any(item => !EmbeddingContractRules.ObjectClasses.Contains(item)) ||
                classes.Distinct(StringComparer.Ordinal).Count() != classes.Count)
                return Refused();

            var modelId = Text(m, "modelId");
            var modelVersion = Text(m, "modelVersion");
            var pipelineId = Text(p, "pipelineId");
            var pipelineVersion = Text(p, "pipelineVersion");
            // The same bounds EmbeddingAnalysis enforces, so a release that starts can always queue.
            if (!IsIdentityText(modelId, 128) || !IsIdentityText(modelVersion, 64) || !IsIdentityText(pipelineId, 64) ||
                !IsIdentityText(pipelineVersion, 64) || pipelineVersion!.Length < 5 || dimension is < 1 or > EmbeddingContractRules.MaximumDimension)
                return Refused();

            var manifestSha = Sha256Hex(manifestBytes);
            var profileSha = Sha256Hex(profileBytes);
            var canonical = Canonical(modelId!, modelVersion!, manifestSha, dimension, pipelineId!, pipelineVersion!, profileSha);
            var fields = new EmbeddingIdentityFields(Sha256Hex(Encoding.UTF8.GetBytes(canonical)), modelId!, modelVersion!, manifestSha,
                dimension, pipelineId!, pipelineVersion!, profileSha);
            return new EmbeddingReleaseResolution(
                new EmbeddingReleaseDefinition(fields, canonical, devElement.GetBoolean(), floor, classes), null);
        }
        catch (JsonException)
        {
            return Refused();
        }
        catch (InvalidOperationException)
        {
            return Refused();
        }
    }

    /// <summary>The canonical identity text: sorted keys, no whitespace, trailing LF.</summary>
    public static string Canonical(
        string modelId, string modelVersion, string manifestSha256, int dimension, string pipelineId, string pipelineVersion, string pipelineSha256) =>
        "{\"model\":{\"dimension\":" + dimension.ToString(System.Globalization.CultureInfo.InvariantCulture) +
        ",\"id\":\"" + modelId + "\",\"manifestSha256\":\"" + manifestSha256 + "\",\"version\":\"" + modelVersion + "\"}," +
        "\"pipeline\":{\"id\":\"" + pipelineId + "\",\"sha256\":\"" + pipelineSha256 + "\",\"version\":\"" + pipelineVersion + "\"}," +
        "\"schemaVersion\":\"" + EmbeddingContractRules.IdentitySchemaVersion + "\"}\n";

    public static string Sha256Hex(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    private static bool IsIdentityText(string? value, int maximumLength) =>
        value is not null && value.Length >= 1 && value.Length <= maximumLength &&
        value.All(character => character is >= ' ' and <= '~' and not '"' and not '\\');

    private static string? Text(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

    private static EmbeddingReleaseResolution Refused() => new(null, InvalidCode);
}
