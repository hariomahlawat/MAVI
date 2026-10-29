using System.Security.Cryptography;
using System.Text;

namespace Mavi.Application.Modules.Events;

/// <summary>
/// Runs a catalogue's enabled rules over one derivation input and gives every event
/// its deterministic identity, UTC instants and input digest (ADR-025 §3, §4).
/// </summary>
/// <remarks>
/// Pure: the same input and catalogue always produce byte-identical output, which is
/// what the recompute tests assert and what lets a persisted event be re-checked
/// against the facts it names.
/// </remarks>
public static class EventDeriver
{
    public static EventDerivationResult Derive(EventDerivationInput input, RuleCatalogueDefinition catalogue)
    {
        ArgumentNullException.ThrowIfNull(input);
        ArgumentNullException.ThrowIfNull(catalogue);

        var canonical = input.Canonical();
        var events = new List<DerivedEvent>();
        var states = new List<EventRuleState>(catalogue.Rules.Count);

        foreach (var rule in catalogue.Rules)
        {
            if (!rule.Enabled)
            {
                states.Add(new EventRuleState(rule.RuleId, rule.RuleVersion, false, rule.DisabledReason, 0));
                continue;
            }

            var drafts = Evaluate(rule, canonical);
            foreach (var draft in drafts)
                events.Add(Identify(catalogue, rule, canonical.Unit, draft));
            states.Add(new EventRuleState(rule.RuleId, rule.RuleVersion, true, null, drafts.Count));
        }

        var ordered = events
            .OrderBy(item => item.StartOffsetMs)
            .ThenBy(item => item.RuleId, StringComparer.Ordinal)
            .ThenBy(item => item.EventId)
            .ToList();

        return new EventDerivationResult(
            catalogue.CatalogueVersion,
            catalogue.Sha256,
            Convert.ToHexStringLower(SHA256.HashData(RuleCatalogueDefinition.Canonical(canonical))),
            states,
            Encoding.UTF8.GetString(RuleCatalogueDefinition.Canonical(states)),
            ordered);
    }

    /// <summary>The drafts one rule produces, in the rule's own deterministic order.</summary>
    public static IReadOnlyList<EventDraft> Evaluate(RuleDefinition rule, EventDerivationInput canonical)
    {
        ArgumentNullException.ThrowIfNull(rule);
        return rule.RuleId switch
        {
            EventRuleIds.LineCrossing => EventRules.LineCrossing(canonical),
            EventRuleIds.ZoneDwell => EventRules.ZoneDwell(canonical),
            EventRuleIds.StoppedVehicle => EventRules.StoppedVehicle(canonical, RuleCatalogue.StoppedVehicleMinimumMs),
            EventRuleIds.WrongWay => EventRules.WrongWay(canonical),
            EventRuleIds.CoOccurrence => EventRules.CoOccurrence(canonical),
            EventRuleIds.RepeatedVisit => EventRules.RepeatedVisit(canonical, 2),
            _ => throw new InvalidOperationException($"Rule '{rule.RuleId}' has no implementation."),
        };
    }

    /// <summary>
    /// A UUID (version 8, RFC 9562 custom) from SHA-256 over the catalogue version, the
    /// rule, the unit and the rule's discriminator.
    /// </summary>
    public static Guid EventId(string catalogueVersion, string ruleId, int ruleVersion, Guid sceneAnalysisId, string discriminator)
    {
        var material = string.Join(
            '\n',
            catalogueVersion,
            ruleId,
            ruleVersion.ToString(System.Globalization.CultureInfo.InvariantCulture),
            sceneAnalysisId.ToString("D"),
            discriminator);
        Span<byte> hash = stackalloc byte[32];
        SHA256.HashData(Encoding.UTF8.GetBytes(material), hash);
        var bytes = hash[..16].ToArray();
        bytes[6] = (byte)((bytes[6] & 0x0F) | 0x80);
        bytes[8] = (byte)((bytes[8] & 0x3F) | 0x80);
        return new Guid(bytes, bigEndian: true);
    }

    private static DerivedEvent Identify(
        RuleCatalogueDefinition catalogue,
        RuleDefinition rule,
        EventUnitIdentity unit,
        EventDraft draft)
    {
        var id = EventId(catalogue.CatalogueVersion, rule.RuleId, rule.RuleVersion, unit.SceneAnalysisId, draft.Discriminator);
        var provenanceJson = Encoding.UTF8.GetString(RuleCatalogueDefinition.Canonical(draft.Provenance));

        // What the event claims, bound to everything it was computed from: the rule
        // version, the unit (and with it run, revision and algorithm version), the
        // instants, the geometry it names and the provenance envelope.
        var digest = Convert.ToHexStringLower(SHA256.HashData(RuleCatalogueDefinition.Canonical(new
        {
            catalogueVersion = catalogue.CatalogueVersion,
            ruleId = rule.RuleId,
            ruleVersion = rule.RuleVersion,
            sceneAnalysisId = unit.SceneAnalysisId,
            sceneRevisionId = unit.SceneRevisionId,
            analyticsAlgorithmVersion = unit.AnalyticsAlgorithmVersion,
            draft.PrimaryTrackId,
            draft.ObjectClass,
            draft.ZoneId,
            draft.LineId,
            draft.Direction,
            draft.StartOffsetMs,
            draft.EndOffsetMs,
            draft.AtUtc,
            provenance = draft.Provenance,
        })));

        return new DerivedEvent(
            id,
            rule.RuleId,
            rule.RuleVersion,
            draft.PrimaryTrackId,
            draft.ObjectClass,
            draft.ZoneId,
            draft.LineId,
            draft.Direction,
            draft.StartOffsetMs,
            draft.EndOffsetMs,
            draft.AtUtc ?? unit.RecordingStartUtc.AddMilliseconds(draft.StartOffsetMs),
            draft.AtUtc ?? unit.RecordingStartUtc.AddMilliseconds(draft.EndOffsetMs),
            draft.Provenance,
            provenanceJson,
            digest);
    }
}
