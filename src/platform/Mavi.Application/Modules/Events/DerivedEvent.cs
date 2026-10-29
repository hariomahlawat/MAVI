namespace Mavi.Application.Modules.Events;

/// <summary>A Track an event names, and in what role.</summary>
public sealed record EventParticipant(Guid TrackId, string Role, string ObjectClass);

/// <summary>
/// One persisted fact an event was computed from: by id where the fact has one, or by
/// its position within a Track where it does not (a stationary interval).
/// </summary>
public sealed record EventInputReference(string Kind, string Reference, long? StartOffsetMs, long? EndOffsetMs);

/// <summary>A rule parameter as it was applied to this event, with its source (ADR-025 §2).</summary>
public sealed record EventAppliedParameter(string Name, string Value, string? Unit, string Source, string Reference);

/// <summary>A named measurement an event reports beside its inputs, for example the dwell observed.</summary>
public sealed record EventDetail(string Name, string Value);

/// <summary>The provenance envelope's evidence detail (ADR-025 §4).</summary>
public sealed record EventProvenance(
    IReadOnlyList<EventParticipant> Participants,
    IReadOnlyList<EventInputReference> Inputs,
    IReadOnlyList<EventAppliedParameter> Parameters,
    IReadOnlyList<EventDetail> Details);

/// <summary>What a rule produces before the deriver gives it an identity and a digest.</summary>
/// <remarks>
/// <paramref name="AtUtc"/> is set for point events taken from a persisted fact that carries
/// its own instant (a crossing): the event reuses scene analytics' instant rather than
/// recomputing one, so Events and the Stage-3 aggregates cannot place it in different buckets.
/// Otherwise the instant is the recording start plus the media offset, as scene analytics
/// computes it.
/// </remarks>
/// <param name="Discriminator">
/// What makes this event unique within its rule and unit, for example the crossing id.
/// It feeds the deterministic event id, so it must be a function of persisted facts only.
/// </param>
public sealed record EventDraft(
    string Discriminator,
    Guid? PrimaryTrackId,
    string? ObjectClass,
    Guid? ZoneId,
    Guid? LineId,
    string? Direction,
    long StartOffsetMs,
    long EndOffsetMs,
    EventProvenance Provenance,
    DateTimeOffset? AtUtc = null);

/// <summary>One derived event, identified and digested.</summary>
public sealed record DerivedEvent(
    Guid EventId,
    string RuleId,
    int RuleVersion,
    Guid? PrimaryTrackId,
    string? ObjectClass,
    Guid? ZoneId,
    Guid? LineId,
    string? Direction,
    long StartOffsetMs,
    long EndOffsetMs,
    DateTimeOffset StartUtc,
    DateTimeOffset EndUtc,
    EventProvenance Provenance,
    string ProvenanceJson,
    string InputSha256);

/// <summary>What one rule did in one derivation.</summary>
/// <summary>A rule's state in one derivation; a disabled rule ran on nothing and has no count, never zero.</summary>
public sealed record EventRuleState(string RuleId, int RuleVersion, bool Enabled, string? DisabledReason, int? EventCount);

/// <summary>The complete output of one derivation.</summary>
public sealed record EventDerivationResult(
    string CatalogueVersion,
    string CatalogueSha256,
    string InputsSha256,
    IReadOnlyList<EventRuleState> RuleStates,
    string RuleStatesJson,
    IReadOnlyList<DerivedEvent> Events);
