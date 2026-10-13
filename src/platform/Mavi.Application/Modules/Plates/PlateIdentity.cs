using System.Security.Cryptography;
using System.Text;
using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Common;

namespace Mavi.Application.Modules.Plates;

public sealed record PlateCapabilityIdentity(string CapabilityId, string ModelPackId);

/// <summary>
/// The plate analysis identity of ADR-013 implementation amendment 2026-10-13, item 11, without the
/// run; <see cref="Fingerprint"/> is the SHA-256 of <see cref="Canonical"/>. Runtime Pack, device,
/// build and commit are provenance, never identity (§11).
/// </summary>
public sealed record PlateIdentity(
    string Fingerprint,
    string PipelineId,
    string PipelineVersion,
    string PredictionsSchemaVersion,
    string NormalisationId,
    string NormalisationSha256,
    string SummaryPolicyId,
    string SummaryPolicyVersion,
    string SummaryPolicySha256,
    IReadOnlyList<PlateCapabilityIdentity> Capabilities,
    string ParametersSha256)
{
    /// <summary>
    /// Builds the identity and its fingerprint. Every token is validated first, so the canonical text
    /// needs no JSON escaping; capabilities must be exactly <c>ocr</c> then <c>plate-detector</c>.
    /// </summary>
    /// <exception cref="ArgumentException">A member is outside its grammar.</exception>
    public static PlateIdentity Create(
        string pipelineId,
        string pipelineVersion,
        string summaryPolicyId,
        string summaryPolicyVersion,
        string summaryPolicySha256,
        IReadOnlyList<PlateCapabilityIdentity> capabilities,
        string parametersSha256)
    {
        ArgumentNullException.ThrowIfNull(capabilities);
        if (!IsToken(pipelineId) || !IsVersion(pipelineVersion) || !IsToken(summaryPolicyId) || !IsVersion(summaryPolicyVersion) ||
            !CanonicalSha256.IsCanonical(summaryPolicySha256) || !CanonicalSha256.IsCanonical(parametersSha256) ||
            capabilities.Count != PlateContractRules.Capabilities.Count ||
            !capabilities.Select(item => item.CapabilityId).SequenceEqual(PlateContractRules.Capabilities, StringComparer.Ordinal) ||
            !capabilities.All(item => IsModelPackId(item.ModelPackId)))
            throw new ArgumentException("plate_identity_invalid");

        var canonical = CanonicalText(pipelineId, pipelineVersion, summaryPolicyId, summaryPolicyVersion, summaryPolicySha256,
            capabilities, parametersSha256);
        return new PlateIdentity(
            CanonicalSha256.ToHex(SHA256.HashData(Encoding.ASCII.GetBytes(canonical))),
            pipelineId,
            pipelineVersion,
            PlateContractRules.PredictionsSchemaVersion,
            PlateContractRules.NormalisationId,
            PlateContractRules.NormalisationSha256,
            summaryPolicyId,
            summaryPolicyVersion,
            summaryPolicySha256,
            [.. capabilities],
            parametersSha256);
    }

    /// <summary>The canonical identity text, trailing LF included (vector <c>plate-identity-v1.json</c>).</summary>
    public string Canonical => CanonicalText(PipelineId, PipelineVersion, SummaryPolicyId, SummaryPolicyVersion, SummaryPolicySha256,
        Capabilities, ParametersSha256);

    private static string CanonicalText(
        string pipelineId, string pipelineVersion, string summaryPolicyId, string summaryPolicyVersion, string summaryPolicySha256,
        IReadOnlyList<PlateCapabilityIdentity> capabilities, string parametersSha256)
    {
        var builder = new StringBuilder(768).Append("{\"capabilities\":[");
        for (var index = 0; index < capabilities.Count; index++)
        {
            if (index > 0) builder.Append(',');
            builder.Append("{\"capabilityId\":\"").Append(capabilities[index].CapabilityId)
                .Append("\",\"modelPackId\":\"").Append(capabilities[index].ModelPackId).Append("\"}");
        }

        return builder.Append("],\"normalisation\":{\"id\":\"").Append(PlateContractRules.NormalisationId)
            .Append("\",\"sha256\":\"").Append(PlateContractRules.NormalisationSha256)
            .Append("\"},\"parametersSha256\":\"").Append(parametersSha256)
            .Append("\",\"pipeline\":{\"id\":\"").Append(pipelineId)
            .Append("\",\"version\":\"").Append(pipelineVersion)
            .Append("\"},\"predictionsSchemaVersion\":\"").Append(PlateContractRules.PredictionsSchemaVersion)
            .Append("\",\"schemaVersion\":\"").Append(PlateContractRules.IdentitySchemaVersion)
            .Append("\",\"summaryPolicy\":{\"id\":\"").Append(summaryPolicyId)
            .Append("\",\"sha256\":\"").Append(summaryPolicySha256)
            .Append("\",\"version\":\"").Append(summaryPolicyVersion)
            .Append("\"}}\n")
            .ToString();
    }

    private static bool IsToken(string? value) =>
        value is { Length: >= 1 and <= PlateContractRules.MaximumTokenLength } &&
        value[0] is >= 'a' and <= 'z' &&
        value[^1] != '-' &&
        !value.Contains("--", StringComparison.Ordinal) &&
        value.All(character => character is >= 'a' and <= 'z' or >= '0' and <= '9' or '-');

    private static bool IsVersion(string? value) =>
        value is { Length: >= 5 and <= 64 } &&
        value.Split('.') is { Length: 3 } parts &&
        parts.All(part => part.Length > 0 && part.All(char.IsAsciiDigit));

    private static bool IsModelPackId(string? value) =>
        value is { Length: 78 } && value.StartsWith("mavi-model-v2-", StringComparison.Ordinal) &&
        CanonicalSha256.IsCanonical(value["mavi-model-v2-".Length..]);
}
