using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Contracts.Worker.Faces;
using Mavi.Domain.Faces;

namespace Mavi.Application.Modules.Faces;

/// <summary>The reference threshold every candidate is shown against (ADR-022 §7): uncalibrated on CCTV.</summary>
public sealed record FaceReferenceThreshold(double Cosine, string Provenance);

/// <summary>The resolved face release: the identity and the profile parameters the platform applies.</summary>
public sealed record FaceReleaseDefinition(
    FaceIdentityFields Identity,
    string CanonicalIdentity,
    bool DevelopmentOnly,
    double DetectorScoreThreshold,
    int MinimumFaceSide,
    FaceReferenceThreshold ReferenceThreshold,
    int QueryImageMaximumBytes);

/// <summary>Either no release (not configured), a definition, or a refusal code.</summary>
public sealed record FaceReleaseResolution(FaceReleaseDefinition? Definition, string? RefusalCode)
{
    public static readonly FaceReleaseResolution NotConfigured = new(null, null);
}

public interface IFaceRelease
{
    FaceReleaseResolution Resolution { get; }
}

/// <summary>
/// Parses the face pipeline's model manifest (manifest v2, capability <c>embedding</c>; ADR-022 §2) and pipeline
/// profile (<c>mavi-face-pipeline-v1</c>) into the identity of ADR-022 §3. The canonical identity is the compact,
/// key-sorted JSON the Python worker writes (<c>contracts/test-vectors/face-identity-v1.json</c>), with a trailing
/// LF; its SHA-256 is the fingerprint. Identity strings are printable ASCII without quotes or backslashes, so both
/// stacks produce the same bytes without JSON escaping.
/// </summary>
public static class FaceReleaseParser
{
    public const string InvalidCode = "face_release_invalid";

    public static FaceReleaseResolution Parse(byte[] manifestBytes, byte[] profileBytes)
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
                !m.TryGetProperty("capabilityIds", out var capabilities) || capabilities.ValueKind != JsonValueKind.Array ||
                !capabilities.EnumerateArray().Any(item => item.GetString() == "embedding") ||
                !m.TryGetProperty("capabilitySpecific", out var specific) ||
                !specific.TryGetProperty("embedding", out var section) ||
                !section.TryGetProperty("dimension", out var dimensionElement) || !dimensionElement.TryGetInt32(out var dimension))
                return Refused();

            if (Text(p, "schemaVersion") != FaceContractRules.PipelineSchemaVersion ||
                !p.TryGetProperty("dimension", out var profileDimension) || !profileDimension.TryGetInt32(out var pd) || pd != dimension ||
                !p.TryGetProperty("minimumFaceSide", out var sideElement) || !sideElement.TryGetInt32(out var side) || side is < 1 or > 4096 ||
                !p.TryGetProperty("developmentOnly", out var devElement) || devElement.ValueKind is not (JsonValueKind.True or JsonValueKind.False) ||
                !p.TryGetProperty("detector", out var detector) || detector.ValueKind != JsonValueKind.Object ||
                !detector.TryGetProperty("scoreThreshold", out var scoreElement) || !scoreElement.TryGetDouble(out var score) ||
                score is <= 0 or > 1 ||
                !p.TryGetProperty("referenceThreshold", out var reference) || reference.ValueKind != JsonValueKind.Object ||
                !reference.TryGetProperty("cosine", out var cosineElement) || !cosineElement.TryGetDouble(out var cosine) ||
                cosine is < -1 or > 1 || Text(reference, "provenance") is not { Length: >= 1 and <= 500 } provenance ||
                !p.TryGetProperty("objectClasses", out var classes) || classes.ValueKind != JsonValueKind.Array ||
                classes.GetArrayLength() != 1 || classes[0].GetString() != "Person")
                return Refused();

            var maximumBytes = FaceQuery.MaximumImageBytes;
            if (p.TryGetProperty("queryImageMaximumBytes", out var bytesElement))
            {
                if (!bytesElement.TryGetInt32(out maximumBytes) || maximumBytes is < 1024 or > FaceQuery.MaximumImageBytes) return Refused();
            }

            var modelId = Text(m, "modelId");
            var modelVersion = Text(m, "modelVersion");
            var pipelineId = Text(p, "pipelineId");
            var pipelineVersion = Text(p, "pipelineVersion");
            if (!IsIdentityText(modelId, 128) || !IsIdentityText(modelVersion, 64) || !IsIdentityText(pipelineId, 64) ||
                !IsIdentityText(pipelineVersion, 64) || pipelineVersion!.Length < 5 || dimension is < 1 or > FaceContractRules.MaximumDimension)
                return Refused();

            var manifestSha = Sha256Hex(manifestBytes);
            var profileSha = Sha256Hex(profileBytes);
            var canonical = Canonical(modelId!, modelVersion!, manifestSha, dimension, pipelineId!, pipelineVersion!, profileSha);
            var fields = new FaceIdentityFields(Sha256Hex(Encoding.UTF8.GetBytes(canonical)), modelId!, modelVersion!, manifestSha,
                dimension, pipelineId!, pipelineVersion!, profileSha);
            return new FaceReleaseResolution(new FaceReleaseDefinition(fields, canonical, devElement.GetBoolean(), score, side,
                new FaceReferenceThreshold(cosine, provenance), maximumBytes), null);
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
        "{\"model\":{\"dimension\":" + dimension.ToString(CultureInfo.InvariantCulture) +
        ",\"id\":\"" + modelId + "\",\"manifestSha256\":\"" + manifestSha256 + "\",\"version\":\"" + modelVersion + "\"}," +
        "\"pipeline\":{\"id\":\"" + pipelineId + "\",\"sha256\":\"" + pipelineSha256 + "\",\"version\":\"" + pipelineVersion + "\"}," +
        "\"schemaVersion\":\"" + FaceContractRules.IdentitySchemaVersion + "\"}\n";

    public static string Sha256Hex(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    private static bool IsIdentityText(string? value, int maximumLength) =>
        value is not null && value.Length >= 1 && value.Length <= maximumLength &&
        value.All(character => character is >= ' ' and <= '~' and not '"' and not '\\');

    private static string? Text(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

    private static FaceReleaseResolution Refused() => new(null, InvalidCode);
}
