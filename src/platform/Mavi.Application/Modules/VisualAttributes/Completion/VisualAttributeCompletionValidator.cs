using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Application.Modules.VisualAttributes.Release;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Attributes;
using Mavi.Domain.Common;
using Mavi.Domain.VisualAttributes;

namespace Mavi.Application.Modules.VisualAttributes.Completion;

/// <summary>One Track of the leased run the completion must account for, with its accepted crops.</summary>
public sealed record CompletionTrackScope(Guid TrackId, string ObjectClass, IReadOnlySet<Guid> ObservationIds);

public sealed record ValidatedAttributeRow(
    string AttributeType,
    VisualAttributeOutcome Outcome,
    string? Value,
    double? Confidence,
    Guid? SupportingObservationId);

public sealed record ValidatedTrackResult(
    Guid TrackId,
    VisualAttributeTrackOutcomeKind Outcome,
    string? Reason,
    IReadOnlyList<ValidatedAttributeRow> Rows);

/// <summary>A completion that passed every Phase-A rule, with the digest that identifies it.</summary>
public sealed record ValidatedAttributeCompletion(
    Guid AnalysisId,
    string WorkerId,
    int AttemptCount,
    string ProvenanceJson,
    long PredictionSizeBytes,
    string PredictionSha256,
    IReadOnlyList<ValidatedTrackResult> Tracks,
    string CompletionDigest)
{
    public int TracksAnalysed => Tracks.Count(track => track.Outcome == VisualAttributeTrackOutcomeKind.Analysed);
    public int TracksUnavailable => Tracks.Count - TracksAnalysed;
    public int AttributesObserved => Tracks.Sum(track => track.Rows.Count(row => row.Outcome == VisualAttributeOutcome.Observed));
    public int AttributesUnknown => Tracks.Sum(track => track.Rows.Count(row => row.Outcome == VisualAttributeOutcome.Unknown));
}

public sealed record CompletionValidation(ValidatedAttributeCompletion? Completion, string? ErrorCode)
{
    public bool IsValid => ErrorCode is null;
    public static CompletionValidation Invalid(string code) => new(null, code);
}

/// <summary>
/// Phase A's typed rules (S2b plan §13): bounds, provenance shape, Track and Observation
/// ownership, exact outcome and final-row cardinality, and the Observed/Unknown shape.
/// Pure: it reads nothing, and it never sees the capability.
/// </summary>
public static class VisualAttributeCompletionValidator
{
    public const string DigestDomain = "mavi:visual-attribute-completion-digest:v1";
    public const string InvalidCode = "visual_attribute_completion_invalid";

    private static readonly HashSet<string> RuntimeVariants = new(StringComparer.Ordinal)
    {
        "windows-x86_64-cpu", "windows-x86_64-cuda", "linux-x86_64-cpu", "linux-x86_64-cuda",
    };

    public static CompletionValidation Validate(
        Guid routeAnalysisId,
        VisualAttributeCompleteRequest request,
        VisualAttributeIdentityFields identity,
        AttributeSchemaDefinition schema,
        IReadOnlyList<CompletionTrackScope> scope)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentNullException.ThrowIfNull(identity);
        ArgumentNullException.ThrowIfNull(schema);
        ArgumentNullException.ThrowIfNull(scope);

        if (request.SchemaVersion != VisualAttributeContractRules.SchemaVersion) return CompletionValidation.Invalid("worker_contract_version_unsupported");
        if (request.AnalysisId != routeAnalysisId || request.AttemptCount is not ({ } attempt and >= 1) ||
            !WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId))
            return CompletionValidation.Invalid(InvalidCode);

        var provenanceError = ValidateProvenance(request.Provenance, identity);
        if (provenanceError is not null) return CompletionValidation.Invalid(provenanceError);

        if (request.Payload is not { PredictionArtifact: { } artifact, Tracks: { } tracks }) return CompletionValidation.Invalid(InvalidCode);
        if (artifact.MediaType != VisualAttributeContractRules.PredictionsMediaType ||
            artifact.SizeBytes is not ({ } size and >= 1 and <= VisualAttributeContractRules.MaximumPredictionArtifactBytes) ||
            !VisualAttributeContractRules.IsCanonicalSha256(artifact.Sha256))
            return CompletionValidation.Invalid("visual_attribute_prediction_descriptor_invalid");

        // Exactly one outcome for every applicable Track of the run, and nothing else.
        var byId = scope.ToDictionary(item => item.TrackId);
        if (tracks.Count != scope.Count) return CompletionValidation.Invalid("visual_attribute_track_coverage_invalid");
        var seen = new HashSet<Guid>();
        var validated = new List<ValidatedTrackResult>(tracks.Count);
        foreach (var track in tracks)
        {
            if (track.TrackId is not { } trackId || !byId.TryGetValue(trackId, out var trackScope) || !seen.Add(trackId))
                return CompletionValidation.Invalid("visual_attribute_track_coverage_invalid");
            var result = ValidateTrack(track, trackScope, schema);
            if (result.Error is not null) return CompletionValidation.Invalid(result.Error);
            validated.Add(result.Track!);
        }

        validated.Sort((left, right) => left.TrackId.CompareTo(right.TrackId));
        var provenanceJson = JsonSerializer.Serialize(request.Provenance, ProvenanceJsonOptions);
        var digest = ComputeDigest(routeAnalysisId, attempt, identity.Fingerprint, request.Provenance!, size, artifact.Sha256!, validated);
        return new CompletionValidation(
            new ValidatedAttributeCompletion(routeAnalysisId, workerId, attempt, provenanceJson, size, artifact.Sha256!, validated, digest),
            null);
    }

    private static (ValidatedTrackResult? Track, string? Error) ValidateTrack(
        VisualAttributeTrackResultContract track, CompletionTrackScope scope, AttributeSchemaDefinition schema)
    {
        var trackId = scope.TrackId;
        if (track.Outcome == VisualAttributeContractRules.OutcomeUnavailable)
        {
            if (track.Reason is not { } reason || !VisualAttributeContractRules.UnavailableReasons.Contains(reason) ||
                track.Attributes is { Count: > 0 })
                return (null, "visual_attribute_track_outcome_invalid");
            // "No accepted evidence" is a fact about the lease, not a worker opinion.
            if ((reason == "no_accepted_evidence") != (scope.ObservationIds.Count == 0))
                return (null, "visual_attribute_track_outcome_invalid");
            return (new ValidatedTrackResult(trackId, VisualAttributeTrackOutcomeKind.Unavailable, reason, []), null);
        }

        if (track.Outcome != VisualAttributeContractRules.OutcomeAnalysed || track.Reason is not null || scope.ObservationIds.Count == 0)
            return (null, "visual_attribute_track_outcome_invalid");

        // Exactly one final row per applicable attribute type: a missing row is not Unknown.
        var applicable = schema.ForObjectClass(scope.ObjectClass);
        var rows = track.Attributes ?? [];
        if (rows.Count != applicable.Count) return (null, "visual_attribute_row_cardinality_invalid");
        var validated = new List<ValidatedAttributeRow>(rows.Count);
        var types = new HashSet<string>(StringComparer.Ordinal);
        foreach (var row in rows)
        {
            if (row.AttributeType is not { } type || schema.Find(type) is not { } definition ||
                definition.ObjectClass != scope.ObjectClass || !types.Add(type))
                return (null, "visual_attribute_row_cardinality_invalid");
            if (row.Outcome == VisualAttributeContractRules.OutcomeObserved)
            {
                if (row.Value is not { } value || !definition.Values.Contains(value, StringComparer.Ordinal) ||
                    row.Confidence is not ({ } confidence and >= 0 and <= 1) || !double.IsFinite(confidence) ||
                    row.SupportingObservationId is not { } supporting || !scope.ObservationIds.Contains(supporting))
                    return (null, "visual_attribute_row_invalid");
                validated.Add(new ValidatedAttributeRow(type, VisualAttributeOutcome.Observed, value, confidence, supporting));
            }
            else if (row.Outcome == VisualAttributeContractRules.OutcomeUnknown)
            {
                // Unknown asserts nothing: no value, no confidence, no evidence claim.
                if (row.Value is not null || row.Confidence is not null || row.SupportingObservationId is not null)
                    return (null, "visual_attribute_row_invalid");
                validated.Add(new ValidatedAttributeRow(type, VisualAttributeOutcome.Unknown, null, null, null));
            }
            else
            {
                return (null, "visual_attribute_row_invalid");
            }
        }

        validated.Sort((left, right) => string.CompareOrdinal(left.AttributeType, right.AttributeType));
        return (new ValidatedTrackResult(trackId, VisualAttributeTrackOutcomeKind.Analysed, null, validated), null);
    }

    private static string? ValidateProvenance(VisualAttributeProvenanceContract? provenance, VisualAttributeIdentityFields identity)
    {
        const string code = "visual_attribute_provenance_invalid";
        if (provenance is null || provenance.ProvenanceContract != VisualAttributeContractRules.ProvenanceContract ||
            !VisualAttributeContractRules.IsSchemaToken(provenance.RoleId) ||
            !VisualAttributeContractRules.IsSchemaToken(provenance.RuntimePackFamilyId) ||
            !VisualAttributeContractRules.IsCanonicalSha256(provenance.RuntimeProfileSha256) ||
            provenance.RuntimeVariant is not { } variant || !RuntimeVariants.Contains(variant) ||
            !VisualAttributeContractRules.IsCanonicalSha256(provenance.ComponentBindingSha256) ||
            !VisualAttributeContractRules.IsCanonicalSha256(provenance.PipelineProfileSha256) ||
            provenance.ConfiguredDevicePolicy is not ("cpu" or "cuda" or "auto") ||
            !IsDevice(provenance.ActualDevice) ||
            !IsOptionalText(provenance.MaviBuild) || !IsOptionalText(provenance.MaviCommit))
            return code;

        // Truthful Runtime Pack identity (ADR-014 §8): an installed pack names its id; an
        // unpacked environment names none.
        switch (provenance.RuntimePackSource)
        {
            case "installed-pack" when IsPrefixedSha(provenance.RuntimePackId, "mavi-runtime-v2-"):
            case "unpacked-environment" when provenance.RuntimePackId is null:
                break;
            default:
                return code;
        }

        // The producer must be exactly the unit's capability identity: same capabilities, same
        // Model Packs, in canonical order.
        if (provenance.Capabilities is not { Count: >= 1 } capabilities) return code;
        var canonical = new StringBuilder("[");
        for (var index = 0; index < capabilities.Count; index++)
        {
            var capability = capabilities[index];
            if (!VisualAttributeContractRules.IsAttributeCapability(capability.CapabilityId) ||
                !IsPrefixedSha(capability.ModelPackId, "mavi-model-v2-") ||
                !VisualAttributeContractRules.IsCanonicalSha256(capability.ModelManifestSha256) ||
                !VisualAttributeContractRules.IsSchemaToken(capability.QualificationId) ||
                !VisualAttributeContractRules.IsCanonicalSha256(capability.QualificationSha256) ||
                capability.VerificationStatus is not ("verified" or "unverified"))
                return code;
            if (index > 0) canonical.Append(',');
            canonical.Append("{\"capabilityId\":\"").Append(capability.CapabilityId)
                .Append("\",\"modelPackId\":\"").Append(capability.ModelPackId).Append("\"}");
        }

        canonical.Append(']');
        // An unpacked environment is never verified (ADR-014 §8).
        if (provenance.RuntimePackSource == "unpacked-environment" && capabilities.Any(item => item.VerificationStatus == "verified"))
            return code;
        return string.Equals(canonical.ToString(), identity.CapabilitiesCanonical, StringComparison.Ordinal)
            ? null
            : "visual_attribute_provenance_identity_mismatch";
    }

    /// <summary>
    /// The completion digest: length-prefixed fields under its own domain tag. The worker id
    /// and the capability are never inputs; provenance is (ADR-013 §11), so a replay from
    /// another device or build is a different completion.
    /// </summary>
    public static string ComputeDigest(
        Guid analysisId,
        int attemptCount,
        string identityFingerprint,
        VisualAttributeProvenanceContract provenance,
        long predictionSizeBytes,
        string predictionSha256,
        IReadOnlyList<ValidatedTrackResult> tracks)
    {
        ArgumentNullException.ThrowIfNull(provenance);
        ArgumentNullException.ThrowIfNull(tracks);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        void Field(string? value)
        {
            if (value is null)
            {
                hash.AppendData([0xFF]);
                return;
            }

            var bytes = Encoding.UTF8.GetBytes(value);
            Span<byte> length = stackalloc byte[4];
            System.Buffers.Binary.BinaryPrimitives.WriteInt32BigEndian(length, bytes.Length);
            hash.AppendData([0x01]);
            hash.AppendData(length);
            hash.AppendData(bytes);
        }

        string Number(long value) => value.ToString(CultureInfo.InvariantCulture);

        Field(DigestDomain);
        Field(analysisId.ToString("D"));
        Field(Number(attemptCount));
        Field(identityFingerprint);
        Field(provenance.ProvenanceContract);
        Field(provenance.RoleId);
        Field(Number(provenance.Capabilities!.Count));
        foreach (var capability in provenance.Capabilities)
        {
            Field(capability.CapabilityId);
            Field(capability.ModelPackId);
            Field(capability.ModelManifestSha256);
            Field(capability.QualificationId);
            Field(capability.QualificationSha256);
            Field(capability.VerificationStatus);
        }

        Field(provenance.RuntimePackFamilyId);
        Field(provenance.RuntimeProfileSha256);
        Field(provenance.RuntimeVariant);
        Field(provenance.RuntimePackId);
        Field(provenance.RuntimePackSource);
        Field(provenance.ComponentBindingSha256);
        Field(provenance.PipelineProfileSha256);
        Field(provenance.ConfiguredDevicePolicy);
        Field(provenance.ActualDevice);
        Field(provenance.MaviBuild);
        Field(provenance.MaviCommit);
        Field(Number(predictionSizeBytes));
        Field(predictionSha256);
        Field(Number(tracks.Count));
        foreach (var track in tracks)
        {
            Field(track.TrackId.ToString("D"));
            Field(track.Outcome.ToString());
            Field(track.Reason);
            Field(Number(track.Rows.Count));
            foreach (var row in track.Rows)
            {
                Field(row.AttributeType);
                Field(row.Outcome.ToString());
                Field(row.Value);
                Field(row.Confidence?.ToString("R", CultureInfo.InvariantCulture));
                Field(row.SupportingObservationId?.ToString("D"));
            }
        }

        return CanonicalSha256.ToHex(hash.GetHashAndReset());
    }

    private static readonly JsonSerializerOptions ProvenanceJsonOptions = new(JsonSerializerDefaults.Web);

    private static bool IsDevice(string? value) =>
        value == "cpu" ||
        (value is { Length: >= 6 and <= 8 } && value.StartsWith("cuda:", StringComparison.Ordinal) &&
         value[5..].All(char.IsAsciiDigit) && (value.Length == 6 || value[5] != '0'));

    private static bool IsOptionalText(string? value) =>
        value is null || (value.Length is >= 1 and <= 128 && value.All(character => character is > ' ' and < (char)0x7F));

    private static bool IsPrefixedSha(string? value, string prefix) =>
        value is not null && value.StartsWith(prefix, StringComparison.Ordinal) &&
        VisualAttributeContractRules.IsCanonicalSha256(value[prefix.Length..]);
}
