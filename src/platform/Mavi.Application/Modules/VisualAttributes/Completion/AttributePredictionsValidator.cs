using System.Text.Json;
using System.Text.Json.Serialization;
using Mavi.Application.Modules.VisualAttributes.Release;
using Mavi.Contracts.Worker.Attributes;
using Mavi.Domain.VisualAttributes;

namespace Mavi.Application.Modules.VisualAttributes.Completion;

/// <summary>
/// Structural validation of the uploaded <c>AttributePredictions</c> artefact (ADR-013 §13;
/// S2b plan §11), streamed with bounded memory: one Track element at a time, never a DOM of
/// the whole document.
/// </summary>
/// <remarks>
/// <para>
/// The artefact is the non-authoritative forensic record; the relational rows are the facts.
/// The platform therefore binds it — schema id and version, the unit's analysis id and
/// identity fingerprint, the attribute schema and aggregation policy it was produced under,
/// Track and Observation identifiers, bounded records — and holds its aggregation decisions
/// equal, value by value, to the completion's final rows, so the two can never silently
/// disagree. It hashes nothing: the Phase B seal verifies the received bytes' SHA-256 and
/// the platform never re-serialises them.
/// </para>
/// </remarks>
public static class AttributePredictionsValidator
{
    public const string InvalidCode = "visual_attribute_predictions_invalid";
    /// <summary>The largest single Track element the reader buffers.</summary>
    public const int MaximumElementBytes = 1024 * 1024;
    private const int ReadChunkBytes = 64 * 1024;

    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        AllowDuplicateProperties = false,
        NumberHandling = JsonNumberHandling.Strict,
        MaxDepth = 16,
    };

    public sealed record Expectation(
        Guid AnalysisId,
        VisualAttributeIdentityFields Identity,
        AttributeSchemaDefinition Schema,
        IReadOnlyList<CompletionTrackScope> Scope,
        ValidatedAttributeCompletion Completion);

    /// <summary>
    /// The outcome of validating an artefact: an error code, or none and the accepted crops the
    /// worker found missing or not matching their recorded digest — an integrity signal the
    /// platform cannot see for itself, since the worker hashes what it reads.
    /// </summary>
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
                    // One element does not fit: grow up to the element bound, never beyond.
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

    // --- The streaming state machine -----------------------------------------------------

    private enum Phase { Root, RootProperty, Tracks, Done }

    private sealed record Ref(string Id, string Sha256, string Version);

    private sealed record Decision(string AttributeType, double? Confidence, string Outcome, Guid? SupportingObservationId, string? Value);

    private sealed record PredictedObservation(Guid ObservationId, string? Reason, Dictionary<string, Dictionary<string, double>>? Scores, string Status);

    private sealed record PredictedTrack(
        IReadOnlyList<Decision> Decisions, IReadOnlyList<PredictedObservation> Observations, string Outcome, string? Reason, Guid TrackId);

    private sealed class Machine(Expectation expectation)
    {
        private static readonly string[] HeaderProperties =
            ["aggregationPolicy", "analysisId", "attributeSchema", "identityFingerprint", "schemaVersion"];

        private readonly Dictionary<Guid, CompletionTrackScope> _scope = expectation.Scope.ToDictionary(item => item.TrackId);
        private readonly Dictionary<Guid, ValidatedTrackResult> _completed = expectation.Completion.Tracks.ToDictionary(item => item.TrackId);
        private readonly HashSet<string> _headerSeen = new(StringComparer.Ordinal);
        private readonly HashSet<Guid> _tracksSeen = [];
        private JsonReaderState _state = new(new JsonReaderOptions { MaxDepth = 16 });
        private Phase _phase = Phase.Root;
        private bool _tracksSeenProperty;

        public string? Error { get; private set; }

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
                            if (_tracksSeen.Count != _completed.Count) Error = InvalidCode;
                            _phase = Phase.RootProperty;
                            break;
                        }

                        if (reader.TokenType != JsonTokenType.StartObject) { Error = InvalidCode; break; }
                        var element = reader;
                        if (!element.TrySkip()) goto NeedMore;
                        Track(JsonSerializer.Deserialize<PredictedTrack>(ref reader, Options));
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

        public bool IsDone => _phase == Phase.Done;

        public List<Guid> IntegrityIncidents { get; } = [];

        private void Header(string name, ref Utf8JsonReader reader)
        {
            if (!_headerSeen.Add(name)) { Error = InvalidCode; return; }
            var identity = expectation.Identity;
            switch (name)
            {
                case "schemaVersion":
                    if (reader.TokenType != JsonTokenType.String || reader.GetString() != VisualAttributeContractRules.PredictionsSchemaVersion)
                        Error = InvalidCode;
                    break;
                case "analysisId":
                    if (reader.TokenType != JsonTokenType.String || !Guid.TryParseExact(reader.GetString(), "D", out var id) || id != expectation.AnalysisId)
                        Error = InvalidCode;
                    break;
                case "identityFingerprint":
                    if (reader.TokenType != JsonTokenType.String || reader.GetString() != identity.Fingerprint)
                        Error = InvalidCode;
                    break;
                case "attributeSchema":
                    var schema = JsonSerializer.Deserialize<Ref>(ref reader, Options);
                    if (schema != new Ref(identity.AttributeSchemaId, identity.AttributeSchemaSha256, identity.AttributeSchemaVersion))
                        Error = InvalidCode;
                    break;
                case "aggregationPolicy":
                    var policy = JsonSerializer.Deserialize<Ref>(ref reader, Options);
                    if (policy != new Ref(identity.AggregationPolicyId, identity.AggregationPolicySha256, identity.AggregationPolicyVersion))
                        Error = InvalidCode;
                    break;
                default:
                    Error = InvalidCode;
                    break;
            }
        }

        private void Track(PredictedTrack? track)
        {
            if (track is null || track.Decisions is null || track.Observations is null ||
                !_scope.TryGetValue(track.TrackId, out var scope) || !_completed.TryGetValue(track.TrackId, out var completed) ||
                !_tracksSeen.Add(track.TrackId))
            {
                Error = InvalidCode;
                return;
            }

            var outcome = completed.Outcome == VisualAttributeTrackOutcomeKind.Analysed
                ? VisualAttributeContractRules.OutcomeAnalysed
                : VisualAttributeContractRules.OutcomeUnavailable;
            if (track.Outcome != outcome || track.Reason != completed.Reason ||
                track.Observations.Count > VisualAttributeContractRules.MaximumTrackObservations)
            {
                Error = InvalidCode;
                return;
            }

            var applicable = expectation.Schema.ForObjectClass(scope.ObjectClass);
            var scored = new HashSet<Guid>();
            var observed = new HashSet<Guid>();
            var reasons = new HashSet<string>(StringComparer.Ordinal);
            foreach (var observation in track.Observations)
            {
                if (!scope.ObservationIds.Contains(observation.ObservationId) || !observed.Add(observation.ObservationId))
                {
                    Error = InvalidCode;
                    return;
                }

                if (observation.Status == "scored")
                {
                    if (observation.Reason is not null || observation.Scores is not { } scores || scores.Count != applicable.Count ||
                        applicable.Any(attribute => !scores.TryGetValue(attribute.AttributeType, out var values) ||
                            values.Count != attribute.Values.Count ||
                            attribute.Values.Any(value => !values.TryGetValue(value, out var score) || !double.IsFinite(score))))
                    {
                        Error = InvalidCode;
                        return;
                    }

                    scored.Add(observation.ObservationId);
                }
                else if (observation.Status == "unavailable")
                {
                    if (observation.Reason is not { } reason || !VisualAttributeContractRules.UnavailableReasons.Contains(reason) ||
                        observation.Scores is { Count: > 0 })
                    {
                        Error = InvalidCode;
                        return;
                    }

                    reasons.Add(reason);
                }
                else
                {
                    Error = InvalidCode;
                    return;
                }
            }

            // Every leased crop is accounted for, so no usable evidence can be left out silently
            // and every result stays traceable to the evidence it was (or was not) drawn from.
            if (!observed.SetEquals(scope.ObservationIds))
            {
                Error = InvalidCode;
                return;
            }

            // An Analysed Track was scored from at least one crop; an Unavailable one from none,
            // and for a reason at least one of its crops reports.
            if ((completed.Outcome == VisualAttributeTrackOutcomeKind.Analysed) != (scored.Count > 0) ||
                (completed.Outcome == VisualAttributeTrackOutcomeKind.Unavailable && scope.ObservationIds.Count > 0 &&
                 !reasons.Contains(completed.Reason!)))
            {
                Error = InvalidCode;
                return;
            }

            IntegrityIncidents.AddRange(track.Observations
                .Where(observation => observation.Status == "unavailable" && observation.Reason is "evidence_integrity_failed" or "evidence_missing")
                .Select(observation => observation.ObservationId));

            // The aggregation decisions are the final rows, value for value.
            if (track.Decisions.Count != completed.Rows.Count)
            {
                Error = InvalidCode;
                return;
            }

            var decisions = track.Decisions.OrderBy(item => item.AttributeType, StringComparer.Ordinal).ToList();
            for (var index = 0; index < decisions.Count; index++)
            {
                var decision = decisions[index];
                var row = completed.Rows[index];
                var rowOutcome = row.Outcome == VisualAttributeOutcome.Observed
                    ? VisualAttributeContractRules.OutcomeObserved
                    : VisualAttributeContractRules.OutcomeUnknown;
                if (decision.AttributeType != row.AttributeType || decision.Outcome != rowOutcome || decision.Value != row.Value ||
                    decision.Confidence != row.Confidence || decision.SupportingObservationId != row.SupportingObservationId ||
                    (row.SupportingObservationId is { } supporting && !scored.Contains(supporting)))
                {
                    Error = InvalidCode;
                    return;
                }
            }
        }
    }
}
