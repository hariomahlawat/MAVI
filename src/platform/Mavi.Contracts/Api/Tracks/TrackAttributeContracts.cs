using System.Text.Json.Serialization;

namespace Mavi.Contracts.Api.Tracks;

/// <summary>
/// How much of an attribute search's scope had attribute facts to search (Stage-2 plan §16; PoC S5), in Tracks of the
/// predicates' object class in the base candidate scope. Always returned when <c>attribute</c> is present, so an empty
/// page is never read as "no such Track". <paramref name="Analysed"/> + <paramref name="Unavailable"/> +
/// <paramref name="NotAnalysed"/> partition <paramref name="TracksInScope"/>. <paramref name="Unknown"/> counts, per
/// predicate, analysed Tracks whose value was not asserted: they may hold it.
/// </summary>
/// <param name="Disclosure">The pipeline's own operator disclosure (PoC: <c>zero-shot, Development</c>); null when none.</param>
public sealed record AttributeCoverageResponse(
    string? IdentityFingerprint,
    string? Disclosure,
    IReadOnlyList<string> Predicates,
    int TracksInScope,
    int Analysed,
    int Unavailable,
    int NotAnalysed,
    IReadOnlyList<AttributeUnknownCountResponse> Unknown);

public sealed record AttributeUnknownCountResponse(string AttributeType, int Tracks);

/// <summary>Why one row matched an attribute predicate: its Observed value, confidence and supporting crop.</summary>
public sealed record TrackItemAttributeResponse(string AttributeType, string Value, double Confidence, Guid SupportingObservationId);

/// <summary>A Track's visual attributes on the detail surface. Present when attribute analysis applies to the Track.</summary>
/// <param name="Readiness">One of <see cref="TrackSearchContractRules.AttributeReadinessValues"/> for the Track's run.</param>
/// <param name="TrackOutcome"><c>Analysed</c> or <c>Unavailable</c>; present only when Ready.</param>
public sealed record TrackAttributesResponse(
    string Readiness,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? Disclosure,
    bool DevelopmentOnly,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? TrackOutcome,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? UnavailableReason,
    IReadOnlyList<TrackAttributeResponse> Attributes,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    TrackAttributeProvenanceResponse? Provenance);

/// <summary>One final row: <c>Observed</c> with value, confidence and supporting crop, or <c>Unknown</c> with none.</summary>
public sealed record TrackAttributeResponse(
    string AttributeType,
    string Outcome,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? Value,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    double? Confidence,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    Guid? SupportingObservationId);

public sealed record TrackAttributeProvenanceResponse(
    Guid AnalysisId,
    string IdentityFingerprint,
    string AttributeSchemaId,
    string AttributeSchemaVersion,
    string PipelineId,
    string PipelineVersion,
    string AggregationPolicyId,
    string AggregationPolicyVersion,
    string Capabilities,
    DateTimeOffset? CompletedAtUtc);
