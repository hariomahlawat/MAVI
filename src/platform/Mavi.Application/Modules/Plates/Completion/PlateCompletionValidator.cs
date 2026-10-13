using System.Text;
using System.Text.Json;
using Mavi.Application.Modules.Plates.Release;
using Mavi.Contracts.Worker;
using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Plates;

namespace Mavi.Application.Modules.Plates.Completion;

/// <summary>One leased crop of a Vehicle Track: what the completion and the artefact must account for.</summary>
public sealed record PlateScopeObservation(Guid ObservationId, string Role, int EvidenceRank);

/// <summary>One Vehicle Track of the leased run, with its accepted crops in lease (evidence-rank) order.</summary>
public sealed record PlateCompletionTrackScope(Guid TrackId, IReadOnlyList<PlateScopeObservation> Observations);

public sealed record ValidatedPlateObservation(
    Guid SourceObservationId,
    int PlateIndex,
    int BoxX,
    int BoxY,
    int BoxWidth,
    int BoxHeight,
    int CropWidth,
    int CropHeight,
    double DetectorConfidence,
    PlateObservationOutcome Outcome,
    IReadOnlyList<PlateReadingValues> Readings);

public sealed record ValidatedPlateText(string NormalisedText, int SupportCount, double MaxConfidence, Guid BestSourceObservationId, int BestPlateIndex);

public sealed record ValidatedPlateTrack(
    Guid TrackId,
    PlateTrackOutcomeKind Outcome,
    string? Reason,
    IReadOnlyList<ValidatedPlateObservation> Observations,
    IReadOnlyList<ValidatedPlateText> Texts);

/// <summary>A completion that passed every Phase-A rule, with the digest that identifies it.</summary>
public sealed record ValidatedPlateCompletion(
    Guid AnalysisId,
    string WorkerId,
    int AttemptCount,
    string ProvenanceJson,
    long PredictionSizeBytes,
    string PredictionSha256,
    IReadOnlyList<ValidatedPlateTrack> Tracks,
    string CompletionDigest)
{
    public int TracksAnalysed => Tracks.Count(track => track.Outcome == PlateTrackOutcomeKind.Analysed);
    public int TracksUnavailable => Tracks.Count - TracksAnalysed;
    public int PlateObservationsRead => Tracks.Sum(track => track.Observations.Count(item => item.Outcome == PlateObservationOutcome.Read));
    public int PlateObservationsUnreadable => Tracks.Sum(track => track.Observations.Count(item => item.Outcome == PlateObservationOutcome.Unreadable));
}

public sealed record PlateCompletionValidation(ValidatedPlateCompletion? Completion, string? ErrorCode)
{
    public bool IsValid => ErrorCode is null;
    public static PlateCompletionValidation Invalid(string code) => new(null, code);
}

/// <summary>
/// Phase A's typed rules for a plate completion (ADR-013 implementation amendment 2026-10-13, items
/// 11–15): bounds, provenance, lease-order Track and crop coverage, the bounded v1 profile, the box inside
/// its crop, the kept-reading prefix at or above the OCR floor, and the Track texts — which the platform
/// derives itself, with the frozen normalisation, and requires the worker's to equal. Pure: it reads
/// nothing and never sees the capability.
/// </summary>
public static class PlateCompletionValidator
{
    public const string InvalidCode = "plate_completion_invalid";

    private static readonly HashSet<string> RuntimeVariants = new(StringComparer.Ordinal)
    {
        "windows-x86_64-cpu", "windows-x86_64-cuda", "linux-x86_64-cpu", "linux-x86_64-cuda",
    };

    private static readonly JsonSerializerOptions ProvenanceJsonOptions = new(JsonSerializerDefaults.Web);

    public static PlateCompletionValidation Validate(
        Guid routeAnalysisId,
        PlateCompleteRequest request,
        PlateIdentityFields identity,
        PlateParameters parameters,
        IReadOnlyList<PlateCompletionTrackScope> scope)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentNullException.ThrowIfNull(identity);
        ArgumentNullException.ThrowIfNull(parameters);
        ArgumentNullException.ThrowIfNull(scope);

        if (request.SchemaVersion != PlateContractRules.SchemaVersion) return PlateCompletionValidation.Invalid("worker_contract_version_unsupported");
        if (request.AnalysisId != routeAnalysisId || request.AttemptCount is not ({ } attempt and >= 1) ||
            !WorkerContractRules.TryNormalizeWorkerId(request.WorkerId, out var workerId))
            return PlateCompletionValidation.Invalid(InvalidCode);

        var provenanceError = ValidateProvenance(request.Provenance, identity);
        if (provenanceError is not null) return PlateCompletionValidation.Invalid(provenanceError);

        if (request.Payload is not { PredictionArtifact: { } artifact, Tracks: { } tracks }) return PlateCompletionValidation.Invalid(InvalidCode);
        if (artifact.MediaType != PlateContractRules.PredictionsMediaType ||
            artifact.SizeBytes is not ({ } size and >= 1 and <= PlateContractRules.MaximumPredictionArtifactBytes) ||
            !PlateContractRules.IsCanonicalSha256(artifact.Sha256))
            return PlateCompletionValidation.Invalid("plate_prediction_descriptor_invalid");

        // Exactly one outcome for every Vehicle Track of the run, in lease order, and nothing else.
        if (tracks.Count != scope.Count) return PlateCompletionValidation.Invalid("plate_track_coverage_invalid");
        var validated = new List<ValidatedPlateTrack>(tracks.Count);
        for (var index = 0; index < tracks.Count; index++)
        {
            if (tracks[index].TrackId != scope[index].TrackId) return PlateCompletionValidation.Invalid("plate_track_coverage_invalid");
            var result = ValidateTrack(tracks[index], scope[index], parameters);
            if (result.Error is not null) return PlateCompletionValidation.Invalid(result.Error);
            validated.Add(result.Track!);
        }

        var provenanceJson = JsonSerializer.Serialize(request.Provenance, ProvenanceJsonOptions);
        var digest = PlateCompletionDigest.Compute(routeAnalysisId, attempt, identity.Fingerprint, request);
        return new PlateCompletionValidation(
            new ValidatedPlateCompletion(routeAnalysisId, workerId, attempt, provenanceJson, size, artifact.Sha256!, validated, digest), null);
    }

    private static (ValidatedPlateTrack? Track, string? Error) ValidateTrack(
        PlateTrackResultContract track, PlateCompletionTrackScope scope, PlateParameters parameters)
    {
        const string outcomeInvalid = "plate_track_outcome_invalid";
        var readable = scope.Observations.Where(item => !parameters.ExcludedRoles.Contains(item.Role)).ToList();
        if (track.PlateObservations is null || track.Texts is null) return (null, InvalidCode);

        if (track.Outcome == PlateContractRules.TrackOutcomeUnavailable)
        {
            if (track.Reason is not { } reason || !PlateContractRules.TrackUnavailableReasonsBySeverity.Contains(reason) ||
                track.PlateObservations.Count > 0 || track.Texts.Count > 0)
                return (null, outcomeInvalid);
            // "No accepted evidence" is a fact about the lease and the profile, not a worker opinion.
            if ((reason == "no_accepted_evidence") != (readable.Count == 0))
                return (null, outcomeInvalid);
            return (new ValidatedPlateTrack(scope.TrackId, PlateTrackOutcomeKind.Unavailable, reason, [], []), null);
        }

        if (track.Outcome != PlateContractRules.TrackOutcomeAnalysed || track.Reason is not null || readable.Count == 0)
            return (null, outcomeInvalid);

        // Plate observations in lease order, then plate index; only from crops the profile reads.
        var position = readable.Select((item, index) => (item, index)).ToDictionary(pair => pair.item.ObservationId, pair => pair.index);
        var observations = new List<ValidatedPlateObservation>(track.PlateObservations.Count);
        (int Position, int PlateIndex)? previous = null;
        foreach (var observation in track.PlateObservations)
        {
            var (validatedObservation, error) = ValidateObservation(observation, position, parameters);
            if (error is not null) return (null, error);
            var key = (position[validatedObservation!.SourceObservationId], validatedObservation.PlateIndex);
            if (previous is { } last && key.CompareTo(last) <= 0) return (null, "plate_observation_order_invalid");
            previous = key;
            observations.Add(validatedObservation);
        }

        // The Track texts are the platform's derivation; the worker's must be exactly it.
        var ranks = scope.Observations.ToDictionary(item => item.ObservationId, item => item.EvidenceRank);
        var expected = DeriveTexts(observations, ranks);
        if (track.Texts.Count != expected.Count) return (null, "plate_track_texts_invalid");
        for (var index = 0; index < expected.Count; index++)
        {
            var given = track.Texts[index];
            var derived = expected[index];
            if (given.BestPlate is not { } best || best.SourceObservationId != derived.BestSourceObservationId ||
                best.PlateIndex != derived.BestPlateIndex || given.SupportCount != derived.SupportCount ||
                given.MaxConfidence is not { } confidence || confidence != derived.MaxConfidence)
                return (null, "plate_track_texts_invalid");
        }

        return (new ValidatedPlateTrack(scope.TrackId, PlateTrackOutcomeKind.Analysed, null, observations, expected), null);
    }

    private static (ValidatedPlateObservation? Observation, string? Error) ValidateObservation(
        PlateObservationResultContract observation, Dictionary<Guid, int> readable, PlateParameters parameters)
    {
        const string code = "plate_observation_invalid";
        if (observation.SourceObservationId is not { } source || !readable.ContainsKey(source) ||
            observation.PlateIndex is not ({ } plateIndex and >= 0) || plateIndex >= parameters.MaxPlatesPerCrop ||
            observation.Box is not { X: { } x, Y: { } y, Width: { } width, Height: { } height } ||
            observation.CropWidth is not ({ } cropWidth and >= 1 and <= PlateContractRules.MaximumCropDimension) ||
            observation.CropHeight is not ({ } cropHeight and >= 1 and <= PlateContractRules.MaximumCropDimension) ||
            x < 0 || y < 0 || width < 1 || height < 1 || (long)x + width > cropWidth || (long)y + height > cropHeight ||
            observation.DetectorConfidence is not { } detector || !IsProbability(detector) ||
            detector < parameters.DetectorConfidenceFloor ||
            observation.Readings is not { } readings)
            return (null, code);

        PlateObservationOutcome outcome;
        if (observation.Outcome == PlateContractRules.PlateOutcomeRead)
        {
            if (readings.Count is < 1 || readings.Count > parameters.MaxReadingsPerPlate) return (null, "plate_reading_invalid");
            outcome = PlateObservationOutcome.Read;
        }
        else if (observation.Outcome == PlateContractRules.PlateOutcomeUnreadable)
        {
            if (readings.Count != 0) return (null, "plate_reading_invalid");
            outcome = PlateObservationOutcome.Unreadable;
        }
        else
        {
            return (null, code);
        }

        var values = new List<PlateReadingValues>(readings.Count);
        for (var index = 0; index < readings.Count; index++)
        {
            var reading = readings[index];
            if (reading.Rank != index || !PlateContractRules.IsRawText(reading.RawText) ||
                reading.RawLineCount != PlateContractRules.RawLineCount(reading.RawText!) ||
                reading.Confidence is not { } confidence || !IsProbability(confidence) ||
                // Kept readings are exactly the ranked prefix at or above the OCR floor.
                confidence < parameters.OcrConfidenceFloor)
                return (null, "plate_reading_invalid");
            if (index > 0)
            {
                var prior = readings[index - 1];
                if (confidence > prior.Confidence!.Value ||
                    (confidence == prior.Confidence.Value && string.CompareOrdinal(reading.RawText, prior.RawText) <= 0))
                    return (null, "plate_reading_invalid");
            }

            var normalised = PlateNormalisation.Normalise(reading.RawText!);
            values.Add(new PlateReadingValues(index, reading.RawText!, reading.RawLineCount!.Value, confidence, normalised.Normalised,
                normalised.Outcome == PlateNormalisation.Ok ? PlateNormalisationOutcome.Ok : PlateNormalisationOutcome.Rejected,
                normalised.Reason, normalised.FormatClass));
        }

        return (new ValidatedPlateObservation(source, plateIndex, x, y, width, height, cropWidth, cropHeight, detector, outcome, values), null);
    }

    /// <summary>
    /// The summary policy <c>distinct-rank0-normalised-text</c>: one text per distinct <c>ok</c> normalised
    /// rank-0 reading of the Track's read plates; support, maximum confidence and the best plate (highest
    /// confidence, then lower evidence rank, then lower plate index); ordered by normalised text.
    /// </summary>
    public static IReadOnlyList<ValidatedPlateText> DeriveTexts(
        IReadOnlyList<ValidatedPlateObservation> observations, IReadOnlyDictionary<Guid, int> evidenceRanks)
    {
        ArgumentNullException.ThrowIfNull(observations);
        ArgumentNullException.ThrowIfNull(evidenceRanks);
        return observations
            .Where(item => item.Outcome == PlateObservationOutcome.Read && item.Readings[0].NormalisationOutcome == PlateNormalisationOutcome.Ok)
            .GroupBy(item => item.Readings[0].NormalisedText!, StringComparer.Ordinal)
            .OrderBy(group => group.Key, StringComparer.Ordinal)
            .Select(group =>
            {
                var best = group
                    .OrderByDescending(item => item.Readings[0].Confidence)
                    .ThenBy(item => evidenceRanks[item.SourceObservationId])
                    .ThenBy(item => item.PlateIndex)
                    .First();
                return new ValidatedPlateText(group.Key, group.Count(), group.Max(item => item.Readings[0].Confidence),
                    best.SourceObservationId, best.PlateIndex);
            })
            .ToList();
    }

    private static string? ValidateProvenance(PlateProvenanceContract? provenance, PlateIdentityFields identity)
    {
        const string code = "plate_provenance_invalid";
        if (provenance is null || provenance.ProvenanceContract != PlateContractRules.ProvenanceContract ||
            !IsToken(provenance.RoleId) ||
            !IsToken(provenance.RuntimePackFamilyId) ||
            !PlateContractRules.IsCanonicalSha256(provenance.RuntimeProfileSha256) ||
            provenance.RuntimeVariant is not { } variant || !RuntimeVariants.Contains(variant) ||
            !PlateContractRules.IsCanonicalSha256(provenance.ComponentBindingSha256) ||
            !PlateContractRules.IsCanonicalSha256(provenance.PipelineProfileSha256) ||
            provenance.ConfiguredDevicePolicy is not ("cpu" or "cuda" or "auto") ||
            !IsDevice(provenance.ActualDevice) ||
            !IsOptionalText(provenance.MaviBuild) || !IsOptionalText(provenance.MaviCommit))
            return code;

        // Truthful Runtime Pack identity (ADR-014 §8): an installed pack names its id; an unpacked environment none.
        switch (provenance.RuntimePackSource)
        {
            case "installed-pack" when IsPrefixedSha(provenance.RuntimePackId, "mavi-runtime-v2-"):
            case "unpacked-environment" when provenance.RuntimePackId is null:
                break;
            default:
                return code;
        }

        // The producer must be exactly the unit's capability identity: ocr then plate-detector, same packs.
        if (provenance.Capabilities is not { Count: 2 } capabilities) return code;
        var canonical = new StringBuilder("[");
        for (var index = 0; index < capabilities.Count; index++)
        {
            var capability = capabilities[index];
            if (!PlateContractRules.IsPlateCapability(capability.CapabilityId) ||
                !IsPrefixedSha(capability.ModelPackId, "mavi-model-v2-") ||
                !PlateContractRules.IsCanonicalSha256(capability.ModelManifestSha256) ||
                !IsToken(capability.QualificationId) ||
                !PlateContractRules.IsCanonicalSha256(capability.QualificationSha256) ||
                capability.VerificationStatus is not ("verified" or "unverified"))
                return code;
            if (index > 0) canonical.Append(',');
            canonical.Append("{\"capabilityId\":\"").Append(capability.CapabilityId)
                .Append("\",\"modelPackId\":\"").Append(capability.ModelPackId).Append("\"}");
        }

        canonical.Append(']');
        if (provenance.RuntimePackSource == "unpacked-environment" && capabilities.Any(item => item.VerificationStatus == "verified"))
            return code;
        return string.Equals(canonical.ToString(), identity.CapabilitiesCanonical, StringComparison.Ordinal)
            ? null
            : "plate_provenance_identity_mismatch";
    }

    private static bool IsProbability(double value) => double.IsFinite(value) && value is >= 0 and <= 1;

    private static bool IsToken(string? value) =>
        value is { Length: >= 1 and <= PlateContractRules.MaximumTokenLength } &&
        value[0] is >= 'a' and <= 'z' && value[^1] != '-' &&
        !value.Contains("--", StringComparison.Ordinal) &&
        value.All(character => character is >= 'a' and <= 'z' or >= '0' and <= '9' or '-');

    private static bool IsDevice(string? value) =>
        value == "cpu" ||
        (value is { Length: >= 6 and <= 8 } && value.StartsWith("cuda:", StringComparison.Ordinal) &&
         value[5..].All(char.IsAsciiDigit) && (value.Length == 6 || value[5] != '0'));

    private static bool IsOptionalText(string? value) =>
        value is null || (value.Length is >= 1 and <= 128 && value.All(character => character is > ' ' and < (char)0x7F));

    private static bool IsPrefixedSha(string? value, string prefix) =>
        value is not null && value.StartsWith(prefix, StringComparison.Ordinal) &&
        PlateContractRules.IsCanonicalSha256(value[prefix.Length..]);
}
