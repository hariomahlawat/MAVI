using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Mavi.Application.Modules.Events;

/// <summary>Where a rule parameter's value comes from (ADR-025 §2).</summary>
public static class RuleParameterSource
{
    /// <summary>Read from the analysis unit's own scene revision; bound to the event by the revision id.</summary>
    public const string SceneRevision = "scene-revision";

    /// <summary>A value the owner accepted on the record, cited by decision id.</summary>
    public const string OwnerDecision = "owner-decision";

    /// <summary>A rule-definition constant: disclosed, with no tunable number behind it.</summary>
    public const string Catalogue = "catalogue";
}

/// <summary>The rule identities of the catalogue. Stable across catalogue versions.</summary>
public static class EventRuleIds
{
    public const string LineCrossing = "line-crossing";
    public const string ZoneDwell = "zone-dwell";
    public const string StoppedVehicle = "stopped-vehicle";
    public const string WrongWay = "wrong-way";
    public const string CoOccurrence = "co-occurrence";
    public const string RepeatedVisit = "repeated-visit";

    public static readonly IReadOnlyList<string> All =
        [LineCrossing, ZoneDwell, StoppedVehicle, WrongWay, CoOccurrence, RepeatedVisit];
}

/// <summary>One declared parameter of a rule, with its source.</summary>
/// <param name="Value">
/// The catalogue value, or null when the value is read per event from the scene revision.
/// </param>
public sealed record RuleParameterDefinition(
    string Name,
    string? Value,
    string? Unit,
    string Source,
    string Reference);

/// <summary>One rule of a catalogue version.</summary>
public sealed record RuleDefinition(
    string RuleId,
    int RuleVersion,
    string Title,
    string Description,
    bool Enabled,
    string? DisabledReason,
    IReadOnlyList<RuleParameterDefinition> Parameters);

/// <summary>A whole, immutable catalogue version.</summary>
public sealed record RuleCatalogueDefinition(string CatalogueVersion, IReadOnlyList<RuleDefinition> Rules)
{
    private static readonly JsonSerializerOptions CanonicalJson = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = false,
    };

    /// <summary>SHA-256 of the catalogue's canonical JSON, recorded with every derivation.</summary>
    public string Sha256 { get; } = Hash(CatalogueVersion, Rules);

    public RuleDefinition Rule(string ruleId) =>
        Rules.Single(rule => string.Equals(rule.RuleId, ruleId, StringComparison.Ordinal));

    private static string Hash(string version, IReadOnlyList<RuleDefinition> rules)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(new { catalogueVersion = version, rules }, CanonicalJson);
        return Convert.ToHexStringLower(SHA256.HashData(bytes));
    }

    internal static byte[] Canonical<T>(T value) => JsonSerializer.SerializeToUtf8Bytes(value, CanonicalJson);

    /// <summary>Reads a persisted provenance document back (the inverse of the deriver's serialisation).</summary>
    public static EventProvenance ReadProvenance(string json) =>
        JsonSerializer.Deserialize<EventProvenance>(json, CanonicalJson)
        ?? throw new InvalidOperationException("The provenance document is empty.");

    internal static string Sha256Hex(string text) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
}

/// <summary>
/// The code-defined rule catalogues. A change to any rule's semantics, or to any
/// parameter whose source is not the scene revision, is a new catalogue version
/// (ADR-025 §2); a version once shipped is never edited.
/// </summary>
public static class RuleCatalogue
{
    /// <summary>The disabled reason of entity-conditioned rules until Entity confirmation (S7) exists.</summary>
    public const string RequiresEntityConfirmation = "requires_entity_confirmation";

    /// <summary>S2 owner decision 10: the 30 s stationary minimum for the stopped-vehicle demonstration.</summary>
    public const long StoppedVehicleMinimumMs = 30_000;

    public static readonly RuleCatalogueDefinition V1 = new(
        "mavi-events-v1",
        [
            new RuleDefinition(
                EventRuleIds.LineCrossing,
                1,
                "Line crossing",
                "One event per crossing of an enabled trip line, as persisted by scene analytics; counted per line, direction and time bucket.",
                Enabled: true,
                DisabledReason: null,
                []),
            new RuleDefinition(
                EventRuleIds.ZoneDwell,
                1,
                "Dwell",
                "A person's total dwell in an enabled zone reached the zone's threshold. This is the scene-analytics loitering verdict, which is person-only.",
                Enabled: true,
                DisabledReason: null,
                [
                    new RuleParameterDefinition(
                        "thresholdSeconds", null, "s", RuleParameterSource.SceneRevision,
                        "zone loiteringThresholdSeconds; the engine default when the zone sets none"),
                ]),
            new RuleDefinition(
                EventRuleIds.StoppedVehicle,
                1,
                "Stopped vehicle",
                "A Vehicle Track stood still, overlapping a visit to an enabled Restricted zone, for at least the minimum.",
                Enabled: true,
                DisabledReason: null,
                [
                    new RuleParameterDefinition(
                        "minimumStationarySeconds", "30", "s", RuleParameterSource.OwnerDecision,
                        "S2 admissibility record §9, owner decision 10 (accepted, disclosed, 2026-10-29)"),
                    new RuleParameterDefinition(
                        "zoneKind", "Restricted", null, RuleParameterSource.Catalogue,
                        "ADR-025 §2"),
                ]),
            new RuleDefinition(
                EventRuleIds.WrongWay,
                1,
                "Wrong way",
                "A crossing against the trip line's permitted direction. A line with no permitted direction never fires.",
                Enabled: true,
                DisabledReason: null,
                [
                    new RuleParameterDefinition(
                        "permittedDirection", null, null, RuleParameterSource.SceneRevision,
                        "trip line permittedDirection (ADR-025 §6)"),
                ]),
            new RuleDefinition(
                EventRuleIds.CoOccurrence,
                1,
                "Co-occurrence",
                "Within one enabled zone, at least one Person and at least one Vehicle were inside at the same time; one event per episode, naming every participant.",
                Enabled: true,
                DisabledReason: null,
                [
                    new RuleParameterDefinition(
                        "classes", "Person+Vehicle", null, RuleParameterSource.Catalogue, "ADR-025 §2"),
                    new RuleParameterDefinition(
                        "minimumOverlapMs", "0 (exclusive)", "ms", RuleParameterSource.Catalogue,
                        "ADR-025 §2: any positive overlap; no tunable threshold"),
                ]),
            new RuleDefinition(
                EventRuleIds.RepeatedVisit,
                1,
                "Repeated visit",
                "One confirmed Entity entered the same zone through at least two distinct Tracks. Entity-conditioned: disabled until Entity confirmation (S7) exists.",
                Enabled: false,
                DisabledReason: RequiresEntityConfirmation,
                [
                    new RuleParameterDefinition(
                        "minimumDistinctTracks", "2", null, RuleParameterSource.Catalogue, "ADR-025 §2"),
                ]),
        ]);

    /// <summary>The catalogue the platform derives and serves now.</summary>
    public static RuleCatalogueDefinition Current => V1;
}
