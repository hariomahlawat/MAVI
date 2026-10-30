using Mavi.Application.Modules.VisualAttributes;
using Mavi.Application.Modules.VisualAttributes.Release;
using Mavi.Contracts.Api.Tracks;
using Mavi.Domain.Intelligence;
using Mavi.Domain.VisualAttributes;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>One attribute predicate: a Track matches when its final row for the type is <c>Observed</c> with the value.</summary>
public sealed record TrackAttributePredicate(string AttributeType, string Value);

/// <summary>
/// The visual-attribute predicate of a Track search (Stage-2 plan §16; PoC S5): one to
/// <see cref="TrackSearchContractRules.MaximumAttributePredicates"/> predicates, ANDed, of distinct types, in canonical
/// (ordinal type) order. The only way to build one from a request is <see cref="TrackAttributeQueryRules.TryParse"/>,
/// which sorts, so repeated keys in any order are one search, one fingerprint and one cursor (E6).
/// </summary>
public sealed record TrackAttributeQuery(IReadOnlyList<TrackAttributePredicate> Predicates)
{
    /// <summary>The canonical wire form, <c>type:value</c> per predicate in canonical order.</summary>
    public IReadOnlyList<string> Wire => Predicates.Select(item => item.AttributeType + ":" + item.Value).ToArray();
}

public static class TrackAttributeQueryRules
{
    /// <summary>
    /// Parses the repeated <c>attribute</c> key. None is no predicate (true, null). Each value is <c>type:value</c>
    /// of schema tokens; more than the maximum, a repeated type or a malformed value is a refusal. Whether the
    /// tokens exist in the bound schema is the service's check (<see cref="TryResolveObjectClass"/>).
    /// </summary>
    public static bool TryParse(IReadOnlyList<string?>? raw, out TrackAttributeQuery? query)
    {
        query = null;
        if (raw is null || raw.Count == 0)
            return true;
        if (raw.Count > TrackSearchContractRules.MaximumAttributePredicates)
            return false;

        var predicates = new List<TrackAttributePredicate>(raw.Count);
        foreach (var item in raw)
        {
            if (item is null)
                return false;
            var separator = item.IndexOf(':', StringComparison.Ordinal);
            if (separator <= 0 || separator != item.LastIndexOf(':'))
                return false;
            var type = item[..separator];
            var value = item[(separator + 1)..];
            if (!TrackSearchContractRules.IsAttributeToken(type) || !TrackSearchContractRules.IsAttributeToken(value))
                return false;
            predicates.Add(new TrackAttributePredicate(type, value));
        }

        predicates.Sort((left, right) => string.CompareOrdinal(left.AttributeType, right.AttributeType));
        for (var index = 1; index < predicates.Count; index++)
        {
            if (string.Equals(predicates[index - 1].AttributeType, predicates[index].AttributeType, StringComparison.Ordinal))
                return false;
        }

        query = new TrackAttributeQuery(predicates);
        return true;
    }

    /// <summary>
    /// The object class every predicate's type applies to under <paramref name="schema"/>; false when a type or a
    /// value is not in the schema or the types span both classes. A predicate on a value the schema does not have is
    /// a refusal, never an empty result.
    /// </summary>
    public static bool TryResolveObjectClass(TrackAttributeQuery query, AttributeSchemaDefinition schema, out ObjectClass objectClass)
    {
        ArgumentNullException.ThrowIfNull(query);
        ArgumentNullException.ThrowIfNull(schema);
        objectClass = default;
        string? schemaClass = null;
        foreach (var predicate in query.Predicates)
        {
            if (schema.Find(predicate.AttributeType) is not { } definition ||
                !definition.Values.Contains(predicate.Value, StringComparer.Ordinal) ||
                (schemaClass is not null && !string.Equals(schemaClass, definition.ObjectClass, StringComparison.Ordinal)))
                return false;
            schemaClass = definition.ObjectClass;
        }

        switch (schemaClass)
        {
            case "person":
                objectClass = ObjectClass.Person;
                return true;
            case "vehicle":
                objectClass = ObjectClass.Vehicle;
                return true;
            default:
                return false;
        }
    }

    public static string ToSchemaClass(ObjectClass objectClass) => objectClass switch
    {
        ObjectClass.Person => "person",
        ObjectClass.Vehicle => "vehicle",
        _ => throw new ArgumentOutOfRangeException(nameof(objectClass)),
    };
}

/// <summary>
/// The attribute coverage of a search's base candidate scope, in Tracks of the predicates' object class
/// (Stage-2 plan §16: explicit Unknown/Unavailable coverage, no implicit negative from a missing analysis).
/// <see cref="Analysed"/> + <see cref="Unavailable"/> + <see cref="NotAnalysed"/> partition
/// <see cref="TracksInScope"/>; <see cref="Unknown"/> holds, per predicate type in canonical order, how many
/// analysed Tracks have an <c>Unknown</c> row for it — Tracks that may hold the value but were not asserted.
/// </summary>
public sealed record TrackAttributeCoverage(
    string? IdentityFingerprint,
    string? Disclosure,
    int TracksInScope,
    int Analysed,
    int Unavailable,
    int NotAnalysed,
    IReadOnlyList<int> Unknown)
{
    public static TrackAttributeCoverage NotConfigured(int tracksInScope, int predicateCount) =>
        new(null, null, tracksInScope, 0, 0, tracksInScope, new int[predicateCount]);
}

/// <summary>Why one row matched: each predicate's Observed value with its confidence and supporting crop.</summary>
public sealed record TrackItemAttributeMatch(string AttributeType, string Value, double Confidence, Guid SupportingObservationId);

/// <summary>Everything a continuation page of an attribute search pins (ADR-013 §16), inside the v4 cursor.</summary>
public sealed record TrackAttributeCursorPosition(
    TrackCursorPosition Position,
    string AttributeIdentityFingerprint,
    TrackAttributeCoverage AttributeCoverage,
    TrackAnalyticsPinnedIdentity? AnalyticsIdentity = null,
    TrackAnalyticsCoverage? AnalyticsCoverage = null)
{
    public bool IsAnalytic => AnalyticsIdentity is not null;
}

public sealed record TrackAttributeSearchRepositoryPage(
    IReadOnlyList<TrackSearchRow> Items,
    DateTimeOffset SnapshotUtc,
    long SnapshotVisibilitySequence,
    TrackAttributeCoverage AttributeCoverage,
    IReadOnlyDictionary<Guid, IReadOnlyList<TrackItemAttributeMatch>> ItemAttributes,
    TrackAnalyticsPinnedIdentity? AnalyticsIdentity = null,
    TrackAnalyticsCoverage? AnalyticsCoverage = null,
    IReadOnlyDictionary<Guid, TrackItemAnalytics>? ItemAnalytics = null);

public sealed record TrackAttributeSearchRepositoryResult(TrackAttributeSearchRepositoryPage? Page)
{
    public bool IsValid => Page is not null;

    public static TrackAttributeSearchRepositoryResult Invalid { get; } = new((TrackAttributeSearchRepositoryPage?)null);
}

// --- Detail ----------------------------------------------------------------------------------

/// <summary>One final row of a Track (Observed with value, confidence and supporting crop, or Unknown).</summary>
public sealed record TrackAttributeRow(
    string AttributeType,
    VisualAttributeOutcome Outcome,
    string? Value,
    double? Confidence,
    Guid? SupportingObservationId);

/// <summary>The analysis behind a Track's attribute facts (tier-3 provenance).</summary>
public sealed record TrackAttributeProvenance(
    Guid AnalysisId,
    string IdentityFingerprint,
    string AttributeSchemaId,
    string AttributeSchemaVersion,
    string PipelineId,
    string PipelineVersion,
    string AggregationPolicyId,
    string AggregationPolicyVersion,
    string CapabilitiesCanonical,
    DateTimeOffset? CompletedAtUtc);

/// <summary>
/// The default analysis's facts for one Track. <paramref name="Outcome"/> is null only when the completed analysis
/// has no outcome row for the Track (its completion forbids that); the detail then reports it without inventing facts.
/// </summary>
public sealed record TrackAttributeFacts(
    VisualAttributeTrackOutcomeKind? Outcome,
    string? UnavailableReason,
    IReadOnlyList<TrackAttributeRow> Attributes,
    TrackAttributeProvenance Provenance);

/// <summary>A Track's attribute detail: its run's readiness and, when Ready, the default analysis's facts.</summary>
public sealed record TrackAttributeDetail(
    VisualAttributeReadinessState Readiness,
    string? Disclosure,
    bool DevelopmentOnly,
    TrackAttributeFacts? Facts);

/// <summary>The attribute half of Track search and detail against the operational store.</summary>
public interface ITrackAttributeSearchRepository
{
    /// <summary>
    /// A search carrying attribute predicates, coordinated as one operation exactly as a plate search is: the first
    /// page takes the shared visibility barrier, allocates the snapshot, resolves the analytic scope when analytic
    /// predicates are combined, computes both coverage blocks and fetches the page under
    /// <paramref name="preferredFingerprint"/>; a continuation evaluates against the pinned identities and snapshot.
    /// </summary>
    Task<TrackAttributeSearchRepositoryResult> SearchAttributesAsync(
        TrackSearchQuery query,
        string? preferredFingerprint,
        string? disclosure,
        TrackAttributeCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken);

    Task<TrackAttributeFacts?> GetTrackAttributeFactsAsync(Guid trackId, Guid analysisId, CancellationToken cancellationToken);
}
