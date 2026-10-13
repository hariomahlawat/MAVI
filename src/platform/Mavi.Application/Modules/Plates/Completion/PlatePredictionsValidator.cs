using System.Text.Json;
using System.Text.Json.Serialization;
using Mavi.Application.Modules.Plates.Release;
using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Plates;

namespace Mavi.Application.Modules.Plates.Completion;

/// <summary>
/// Validation of the uploaded <c>PlatePredictions</c> artefact (ADR-013 implementation amendment
/// 2026-10-13, items 12–15), streamed with bounded memory: one Track element at a time.
/// </summary>
/// <remarks>
/// The artefact is the sealed forensic record of every raw output; the relational rows are the facts.
/// The platform binds the artefact to the unit (schema, analysis id, identity, normalisation, parameters,
/// pipeline and summary policy), checks that every leased crop appears exactly once in lease order with
/// a status the bounded v1 profile admits, re-derives each crop's selection and read/unreadable decision,
/// and holds the completion's plate observations, kept readings, texts and Track outcomes equal to what
/// the artefact implies — so the two can never silently disagree. It hashes nothing: the Phase B seal
/// verifies the received bytes' SHA-256 and the platform never re-serialises them.
/// </remarks>
public static class PlatePredictionsValidator
{
    public const string InvalidCode = "plate_predictions_invalid";
    /// <summary>The largest single Track element the reader buffers.</summary>
    public const int MaximumElementBytes = 1024 * 1024;
    private const int ReadChunkBytes = 64 * 1024;

    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        AllowDuplicateProperties = false,
        NumberHandling = JsonNumberHandling.Strict,
        RespectRequiredConstructorParameters = true,
        RespectNullableAnnotations = true,
        MaxDepth = 16,
    };

    private static readonly Dictionary<string, string> TrackReasonOfCrop = new(StringComparer.Ordinal)
    {
        ["evidence_integrity_failed"] = "evidence_integrity_failed",
        ["evidence_missing"] = "evidence_missing",
        ["decode_failed"] = "evidence_decode_failed",
        ["detector_error"] = "plate_inference_failed",
        ["ocr_error"] = "plate_inference_failed",
        ["ocr_output_invalid"] = "plate_inference_failed",
    };

    public sealed record Expectation(
        Guid AnalysisId,
        PlateIdentityFields Identity,
        PlateParameters Parameters,
        IReadOnlyList<PlateCompletionTrackScope> Scope,
        ValidatedPlateCompletion Completion);

    /// <summary>An error code, or none and the accepted crops the worker found missing or corrupt.</summary>
    public sealed record Result(string? Error, IReadOnlyList<Guid> IntegrityIncidents);

    public static async Task<Result> ValidateAsync(Stream stream, Expectation expectation, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(stream);
        ArgumentNullException.ThrowIfNull(expectation);
        var machine = new Machine(expectation);
        var buffer = new byte[ReadChunkBytes * 2];
        var filled = 0;
        var final = false;
        try
        {
            while (true)
            {
                if (!final && filled < buffer.Length)
                {
                    var read = await stream.ReadAsync(buffer.AsMemory(filled), cancellationToken);
                    if (read == 0) final = true;
                    filled += read;
                }

                var consumed = machine.Process(buffer.AsSpan(0, filled), final);
                if (machine.Error is not null) return new Result(machine.Error, []);
                if (machine.IsDone)
                    return await OnlyWhitespaceRemainsAsync(stream, buffer.AsMemory(consumed, filled - consumed), cancellationToken)
                        ? new Result(null, machine.IntegrityIncidents)
                        : Invalid;
                if (consumed > 0)
                {
                    Buffer.BlockCopy(buffer, consumed, buffer, 0, filled - consumed);
                    filled -= consumed;
                }
                else if (final)
                {
                    break;
                }
                else if (filled == buffer.Length)
                {
                    if (buffer.Length >= MaximumElementBytes) return Invalid;
                    Array.Resize(ref buffer, Math.Min(buffer.Length * 2, MaximumElementBytes));
                }
            }
        }
        catch (JsonException)
        {
            return Invalid;
        }

        return Invalid;
    }

    private static readonly Result Invalid = new(InvalidCode, []);

    private static async Task<bool> OnlyWhitespaceRemainsAsync(Stream stream, ReadOnlyMemory<byte> pending, CancellationToken cancellationToken)
    {
        if (!IsWhitespace(pending.Span)) return false;
        var tail = new byte[ReadChunkBytes];
        int read;
        while ((read = await stream.ReadAsync(tail, cancellationToken)) > 0)
        {
            if (!IsWhitespace(tail.AsSpan(0, read))) return false;
        }

        return true;
    }

    private static bool IsWhitespace(ReadOnlySpan<byte> bytes)
    {
        foreach (var value in bytes)
        {
            if (value is not ((byte)' ' or (byte)'\n' or (byte)'\t' or (byte)'\r')) return false;
        }

        return true;
    }

    // --- Element shapes (exactly the schema's members) -------------------------------------

    private sealed record Normalisation(string Id, string Sha256);
    private sealed record Pipeline(string Id, string Version);
    private sealed record SummaryPolicy(string Id, string Sha256, string Version);
    private sealed record Reading(double Confidence, int Rank, int RawLineCount, string RawText);
    private sealed record Plate(string Outcome, int PlateIndex, IReadOnlyList<Reading> Readings);
    private sealed record Detection(IReadOnlyList<int> Box, Plate? Plate, double Score);
    private sealed record Crop(int? CropHeight, int? CropWidth, IReadOnlyList<Detection> Detections, int EvidenceRank,
        Guid ObservationId, string? Reason, string Role, string Status);
    private sealed record BestPlate(Guid ObservationId, int PlateIndex);
    private sealed record Text(BestPlate BestPlate, double MaxConfidence, int SupportCount);
    private sealed record Track(IReadOnlyList<Crop> Crops, string Outcome, string? Reason, IReadOnlyList<Text> Texts, Guid TrackId);

    // --- The streaming state machine -------------------------------------------------------

    private enum Phase { Root, RootProperty, Tracks, Done }

    private sealed class Machine(Expectation expectation)
    {
        private static readonly string[] HeaderProperties =
            ["analysisId", "identityFingerprint", "normalisation", "parametersSha256", "pipeline", "schemaVersion", "summaryPolicy"];

        private readonly HashSet<string> _headerSeen = new(StringComparer.Ordinal);
        private JsonReaderState _state = new(new JsonReaderOptions { MaxDepth = 16 });
        private Phase _phase = Phase.Root;
        private bool _tracksSeenProperty;
        private int _trackIndex;

        public string? Error { get; private set; }

        public bool IsDone => _phase == Phase.Done;

        public List<Guid> IntegrityIncidents { get; } = [];

        public int Process(ReadOnlySpan<byte> data, bool final)
        {
            var reader = new Utf8JsonReader(data, final, _state);
            var safeState = _state;
            long safe = 0;
            while (Error is null && _phase != Phase.Done)
            {
                if (!reader.Read()) break;
                switch (_phase)
                {
                    case Phase.Root:
                        if (reader.TokenType != JsonTokenType.StartObject) { Error = InvalidCode; break; }
                        _phase = Phase.RootProperty;
                        break;

                    case Phase.RootProperty:
                        if (reader.TokenType == JsonTokenType.EndObject)
                        {
                            if (!_tracksSeenProperty || _headerSeen.Count != HeaderProperties.Length) Error = InvalidCode;
                            _phase = Phase.Done;
                            break;
                        }

                        if (reader.TokenType != JsonTokenType.PropertyName) { Error = InvalidCode; break; }
                        var name = reader.GetString()!;
                        if (!reader.Read()) goto NeedMore;
                        if (name == "tracks")
                        {
                            if (_tracksSeenProperty || reader.TokenType != JsonTokenType.StartArray) { Error = InvalidCode; break; }
                            _tracksSeenProperty = true;
                            _phase = Phase.Tracks;
                            break;
                        }

                        if (reader.TokenType == JsonTokenType.StartObject)
                        {
                            var probe = reader;
                            if (!probe.TrySkip()) goto NeedMore;
                        }

                        Header(name, ref reader);
                        break;

                    case Phase.Tracks:
                        if (reader.TokenType == JsonTokenType.EndArray)
                        {
                            if (_trackIndex != expectation.Scope.Count) Error = InvalidCode;
                            _phase = Phase.RootProperty;
                            break;
                        }

                        if (reader.TokenType != JsonTokenType.StartObject) { Error = InvalidCode; break; }
                        var element = reader;
                        if (!element.TrySkip()) goto NeedMore;
                        TrackElement(JsonSerializer.Deserialize<Track>(ref reader, Options));
                        break;
                }

                safeState = reader.CurrentState;
                safe = reader.BytesConsumed;
                continue;

            NeedMore:
                break;
            }

            _state = safeState;
            return (int)safe;
        }

        private void Header(string name, ref Utf8JsonReader reader)
        {
            if (!_headerSeen.Add(name)) { Error = InvalidCode; return; }
            var identity = expectation.Identity;
            var valid = name switch
            {
                "schemaVersion" => reader.TokenType == JsonTokenType.String && reader.GetString() == PlateContractRules.PredictionsSchemaVersion,
                "analysisId" => reader.TokenType == JsonTokenType.String && Guid.TryParseExact(reader.GetString(), "D", out var id) &&
                                id == expectation.AnalysisId,
                "identityFingerprint" => reader.TokenType == JsonTokenType.String && reader.GetString() == identity.Fingerprint,
                "parametersSha256" => reader.TokenType == JsonTokenType.String && reader.GetString() == identity.ParametersSha256,
                "normalisation" => JsonSerializer.Deserialize<Normalisation>(ref reader, Options) ==
                                   new Normalisation(identity.NormalisationId, identity.NormalisationSha256),
                "pipeline" => JsonSerializer.Deserialize<Pipeline>(ref reader, Options) ==
                              new Pipeline(identity.PipelineId, identity.PipelineVersion),
                "summaryPolicy" => JsonSerializer.Deserialize<SummaryPolicy>(ref reader, Options) ==
                                   new SummaryPolicy(identity.SummaryPolicyId, identity.SummaryPolicySha256, identity.SummaryPolicyVersion),
                _ => false,
            };
            if (!valid) Error = InvalidCode;
        }

        private void TrackElement(Track? track)
        {
            if (track is null || _trackIndex >= expectation.Scope.Count) { Error = InvalidCode; return; }
            var scope = expectation.Scope[_trackIndex];
            var completed = expectation.Completion.Tracks[_trackIndex];
            _trackIndex++;
            if (track.TrackId != scope.TrackId || track.Crops.Count != scope.Observations.Count ||
                track.Texts.Count > PlateContractRules.MaximumTrackPlateObservations)
            {
                Error = InvalidCode;
                return;
            }

            var parameters = expectation.Parameters;
            var derived = new List<ValidatedPlateObservation>();
            var scored = 0;
            var caused = new HashSet<string>(StringComparer.Ordinal);
            for (var index = 0; index < track.Crops.Count; index++)
            {
                var crop = track.Crops[index];
                var leased = scope.Observations[index];
                if (crop.ObservationId != leased.ObservationId || crop.Role != leased.Role || crop.EvidenceRank != leased.EvidenceRank ||
                    !ValidCrop(crop, parameters))
                {
                    Error = InvalidCode;
                    return;
                }

                if (crop.Reason is { } reason) caused.Add(TrackReasonOfCrop[reason]);
                if (crop.Status == PlateContractRules.CropUnavailable && IsIntegrityReason(crop.Reason))
                    IntegrityIncidents.Add(crop.ObservationId);
                if (crop.Status != PlateContractRules.CropScored) continue;
                scored++;
                foreach (var detection in crop.Detections)
                {
                    if (detection.Plate is not { } plate) continue;
                    var readings = plate.Outcome == PlateContractRules.PlateOutcomeRead
                        ? plate.Readings.Where(item => item.Confidence >= parameters.OcrConfidenceFloor)
                            .Select(item => new PlateReadingValues(item.Rank, item.RawText, item.RawLineCount, item.Confidence, null,
                                PlateNormalisationOutcome.Ok, null, null))
                            .ToList()
                        : [];
                    derived.Add(new ValidatedPlateObservation(crop.ObservationId, plate.PlateIndex, detection.Box[0], detection.Box[1],
                        detection.Box[2], detection.Box[3], crop.CropWidth!.Value, crop.CropHeight!.Value, detection.Score,
                        plate.Outcome == PlateContractRules.PlateOutcomeRead ? PlateObservationOutcome.Read : PlateObservationOutcome.Unreadable,
                        readings));
                }
            }

            // The Track outcome the artefact implies, and the completion's.
            var outcome = scored > 0 ? PlateContractRules.TrackOutcomeAnalysed : PlateContractRules.TrackOutcomeUnavailable;
            var expectedReason = scored > 0
                ? null
                : PlateContractRules.TrackUnavailableReasonsBySeverity.FirstOrDefault(caused.Contains) ?? "no_accepted_evidence";
            var completedOutcome = completed.Outcome == PlateTrackOutcomeKind.Analysed
                ? PlateContractRules.TrackOutcomeAnalysed
                : PlateContractRules.TrackOutcomeUnavailable;
            if (track.Outcome != outcome || track.Reason != expectedReason || completedOutcome != outcome || completed.Reason != expectedReason)
            {
                Error = InvalidCode;
                return;
            }

            // Plate observations and kept readings: the completion's facts are exactly the artefact's decisions.
            if (derived.Count != completed.Observations.Count)
            {
                Error = InvalidCode;
                return;
            }

            for (var index = 0; index < derived.Count; index++)
            {
                var left = derived[index];
                var right = completed.Observations[index];
                if (left.SourceObservationId != right.SourceObservationId || left.PlateIndex != right.PlateIndex ||
                    left.BoxX != right.BoxX || left.BoxY != right.BoxY || left.BoxWidth != right.BoxWidth || left.BoxHeight != right.BoxHeight ||
                    left.CropWidth != right.CropWidth || left.CropHeight != right.CropHeight ||
                    left.DetectorConfidence != right.DetectorConfidence || left.Outcome != right.Outcome ||
                    left.Readings.Count != right.Readings.Count ||
                    left.Readings.Zip(right.Readings).Any(pair => pair.First.Rank != pair.Second.Rank ||
                        !string.Equals(pair.First.RawText, pair.Second.RawText, StringComparison.Ordinal) ||
                        pair.First.RawLineCount != pair.Second.RawLineCount || pair.First.Confidence != pair.Second.Confidence))
                {
                    Error = InvalidCode;
                    return;
                }
            }

            // The texts the artefact records are the platform's derivation (already checked against the completion).
            if (track.Texts.Count != completed.Texts.Count ||
                track.Texts.Zip(completed.Texts).Any(pair => pair.First.BestPlate.ObservationId != pair.Second.BestSourceObservationId ||
                    pair.First.BestPlate.PlateIndex != pair.Second.BestPlateIndex ||
                    pair.First.SupportCount != pair.Second.SupportCount || pair.First.MaxConfidence != pair.Second.MaxConfidence))
                Error = InvalidCode;
        }

        private static bool IsIntegrityReason(string? reason) => reason is "evidence_integrity_failed" or "evidence_missing";

        /// <summary>One crop under the bounded v1 profile; the selection and decisions are re-derived, never trusted.</summary>
        private static bool ValidCrop(Crop crop, PlateParameters parameters)
        {
            var excluded = parameters.ExcludedRoles.Contains(crop.Role);
            if (excluded != (crop.Status == PlateContractRules.CropExcluded)) return false;
            var noDimensions = crop.CropWidth is null && crop.CropHeight is null;
            var dimensions = crop.CropWidth is >= 1 and <= PlateContractRules.MaximumCropDimension &&
                             crop.CropHeight is >= 1 and <= PlateContractRules.MaximumCropDimension;
            if (crop.Detections.Count > parameters.MaxDetectionsPerCrop) return false;
            switch (crop.Status)
            {
                case PlateContractRules.CropExcluded:
                    return crop.Reason is null && noDimensions && crop.Detections.Count == 0;
                case PlateContractRules.CropUnavailable:
                    return crop.Reason is { } unavailable && PlateContractRules.CropUnavailableReasons.Contains(unavailable) &&
                           noDimensions && crop.Detections.Count == 0;
                case PlateContractRules.CropAbstained:
                    if (crop.Reason is not { } abstained || !PlateContractRules.CropAbstentionReasons.Contains(abstained)) return false;
                    if (noDimensions) return crop.Detections.Count == 0;
                    return dimensions && crop.Detections.All(item => item.Plate is null) && ValidDetections(crop);
                case PlateContractRules.CropScored:
                    if (crop.Reason is not null || !dimensions || !ValidDetections(crop)) return false;
                    var selected = 0;
                    for (var index = 0; index < crop.Detections.Count; index++)
                    {
                        var detection = crop.Detections[index];
                        var shouldSelect = selected == index && selected < parameters.MaxPlatesPerCrop &&
                                           detection.Score >= parameters.DetectorConfidenceFloor;
                        if (shouldSelect != detection.Plate is not null) return false;
                        if (detection.Plate is not { } plate) continue;
                        if (plate.PlateIndex != selected || !ValidPlate(plate, parameters)) return false;
                        selected++;
                    }

                    return true;
                default:
                    return false;
            }
        }

        private static bool ValidDetections(Crop crop)
        {
            Detection? previous = null;
            foreach (var detection in crop.Detections)
            {
                if (detection.Box.Count != 4 || !double.IsFinite(detection.Score) || detection.Score is < 0 or > 1) return false;
                var (x, y, width, height) = (detection.Box[0], detection.Box[1], detection.Box[2], detection.Box[3]);
                if (x < 0 || y < 0 || width < 1 || height < 1 || (long)x + width > crop.CropWidth || (long)y + height > crop.CropHeight)
                    return false;
                // Ordered by score (descending), then x, y, width, height.
                if (previous is not null)
                {
                    var order = (-previous.Score, previous.Box[0], previous.Box[1], previous.Box[2], previous.Box[3])
                        .CompareTo((-detection.Score, x, y, width, height));
                    if (order > 0) return false;
                }

                previous = detection;
            }

            return true;
        }

        private static bool ValidPlate(Plate plate, PlateParameters parameters)
        {
            if (plate.Readings.Count > parameters.MaxReadingsPerPlate) return false;
            for (var index = 0; index < plate.Readings.Count; index++)
            {
                var reading = plate.Readings[index];
                if (reading.Rank != index || !PlateContractRules.IsRawText(reading.RawText) ||
                    reading.RawLineCount != PlateContractRules.RawLineCount(reading.RawText) ||
                    !double.IsFinite(reading.Confidence) || reading.Confidence is < 0 or > 1)
                    return false;
                if (index > 0)
                {
                    var prior = plate.Readings[index - 1];
                    if (reading.Confidence > prior.Confidence ||
                        (reading.Confidence == prior.Confidence && string.CompareOrdinal(reading.RawText, prior.RawText) <= 0))
                        return false;
                }
            }

            var read = plate.Readings.Count > 0 && plate.Readings[0].Confidence >= parameters.OcrConfidenceFloor;
            return plate.Outcome == (read ? PlateContractRules.PlateOutcomeRead : PlateContractRules.PlateOutcomeUnreadable);
        }
    }
}
