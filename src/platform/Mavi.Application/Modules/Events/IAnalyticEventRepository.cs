using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;

namespace Mavi.Application.Modules.Events;

public enum EventDerivationOutcome
{
    /// <summary>Events were derived and committed in this call.</summary>
    Derived,

    /// <summary>A derivation at this catalogue version already exists; nothing was written.</summary>
    AlreadyDerived,

    /// <summary>The unit exists but carries no facts (not Completed or Superseded); nothing was written.</summary>
    NotFactBearing,

    /// <summary>No such unit.</summary>
    NotFound,
}

public sealed record AnalyticEventTimelineQuery(
    Guid CameraId,
    DateTimeOffset FromUtc,
    DateTimeOffset ToUtc,
    int BucketSeconds,
    IReadOnlySet<string>? RuleIds,
    int Limit);

/// <summary>An event as the timeline lists it: typed columns only, no provenance.</summary>
public sealed record AnalyticEventRow(
    Guid EventId,
    string RuleId,
    int RuleVersion,
    DateTimeOffset StartUtc,
    DateTimeOffset EndUtc,
    long StartOffsetMs,
    long EndOffsetMs,
    Guid VideoAssetId,
    Guid ProcessingRunId,
    Guid? PrimaryTrackId,
    string? ObjectClass,
    Guid? ZoneId,
    Guid? LineId,
    string? Direction,
    int ParticipantCount);

public sealed record EventGeometryZone(Guid ZoneId, string Name);

public sealed record EventGeometryLine(Guid LineId, string Name, string AToBLabel, string BToALabel);

/// <summary>A crossing event reduced to what bucketed counting needs.</summary>
public sealed record EventCrossingPoint(Guid LineId, DateTimeOffset AtUtc, bool AToB);

public sealed record AnalyticEventTimelineResult(
    bool Found,
    AnalyticsResolvedIdentity? Identity,
    string CatalogueVersion,
    TrackAnalyticsCoverage? Coverage,
    int DerivedRuns,
    int EventsPendingRuns,
    IReadOnlyList<EventGeometryZone> Zones,
    IReadOnlyList<EventGeometryLine> Lines,
    IReadOnlyList<AnalyticEventRow> Events,
    IReadOnlyDictionary<string, int> RuleCounts,
    IReadOnlyList<EventCrossingPoint> Crossings,
    bool Truncated)
{
    public static AnalyticEventTimelineResult NotFound(string catalogueVersion) =>
        new(false, null, catalogueVersion, null, 0, 0, [], [], [], new Dictionary<string, int>(), [], false);
}

public sealed record AnalyticEventParticipantView(
    Guid TrackId,
    string Role,
    string ObjectClass,
    Guid VideoAssetId,
    long StartOffsetMs,
    long EndOffsetMs,
    Guid? ThumbnailArtifactId);

public sealed record AnalyticEventDetailView(
    AnalyticEventRow Event,
    Guid CameraId,
    Guid SceneAnalysisId,
    Guid SceneRevisionId,
    int SceneRevisionNumber,
    string AnalyticsAlgorithmVersion,
    string CatalogueVersion,
    string CatalogueSha256,
    string InputSha256,
    DateTimeOffset DerivedAtUtc,
    string? ZoneName,
    EventGeometryLine? Line,
    EventProvenance Provenance,
    IReadOnlyList<AnalyticEventParticipantView> Participants);

/// <summary>Persistence and reads for analytic events (ADR-025).</summary>
public interface IAnalyticEventRepository
{
    /// <summary>Fact-bearing, visible units with no derivation at <paramref name="catalogueVersion"/>, oldest first.</summary>
    Task<IReadOnlyList<Guid>> ListUnitsAwaitingDerivationAsync(
        string catalogueVersion,
        int batchSize,
        CancellationToken cancellationToken);

    /// <summary>
    /// Derives one unit in one transaction: locks the unit, re-checks, reads its facts,
    /// runs the catalogue and inserts the derivation with its events.
    /// </summary>
    Task<EventDerivationOutcome> DeriveAsync(
        Guid sceneAnalysisId,
        RuleCatalogueDefinition catalogue,
        DateTimeOffset nowUtc,
        CancellationToken cancellationToken);

    /// <summary>The exact input a derivation of this unit would read, or null if the unit is not fact-bearing.</summary>
    Task<EventDerivationInput?> ReadDerivationInputAsync(Guid sceneAnalysisId, CancellationToken cancellationToken);

    Task<AnalyticEventTimelineResult> ReadTimelineAsync(
        AnalyticEventTimelineQuery query,
        RuleCatalogueDefinition catalogue,
        CancellationToken cancellationToken);

    /// <summary>One event, or null when it does not exist or its run is not published.</summary>
    Task<AnalyticEventDetailView?> GetEventAsync(Guid eventId, CancellationToken cancellationToken);
}
