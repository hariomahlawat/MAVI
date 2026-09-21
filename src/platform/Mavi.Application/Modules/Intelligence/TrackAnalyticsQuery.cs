using Mavi.Contracts.Api.Tracks;
using Mavi.Domain.SceneAnalytics;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>How a Track must relate to a zone for <c>zoneId</c> to match (plan §S).</summary>
public enum TrackZoneRelation
{
    /// <summary>At least one visit that did not begin inside the zone.</summary>
    Entered,

    /// <summary>At least one visit that did not end inside the zone.</summary>
    Exited,

    /// <summary>Any dwell at all: <c>total_dwell_ms &gt; 0</c>. The default.</summary>
    Dwelled,
}

/// <summary>Which way a trip line was crossed, relative to its own endpoints.</summary>
public enum TrackCrossingDirection
{
    AToB,
    BToA,
}

/// <summary>
/// The analytic half of a Track search: the identity to evaluate against and the
/// predicates to evaluate. Present on a <see cref="TrackSearchQuery"/> exactly when
/// the request supplied an analytics-dependent key.
/// </summary>
/// <remarks>
/// <para>
/// Every member is optional individually; the record as a whole is meaningful only
/// when <see cref="TrackAnalyticsQueryRules.IsValid"/> holds, which is where the
/// dependency matrix (zoneRelation → zoneId, crossingDirection → lineId,
/// analyticsAlgorithmVersion → sceneRevisionId) is enforced.
/// </para>
/// <para>
/// <see cref="RequireCompleteCoverage"/> is the <c>analyticsCoverage=complete</c> control
/// flag. It is not a predicate: it changes the response to a 409 when any run in scope
/// went unevaluated, and nothing else.
/// </para>
/// </remarks>
public sealed record TrackAnalyticsQuery(
    Guid? SceneRevisionId,
    string? AnalyticsAlgorithmVersion,
    Guid? ZoneId,
    TrackZoneRelation? ZoneRelation,
    long? MinDwellMs,
    Guid? LineId,
    TrackCrossingDirection? CrossingDirection,
    string? MotionDirection,
    long? MinStationaryMs,
    bool Loitering,
    bool RequireCompleteCoverage)
{
    /// <summary>A query with nothing set; the starting point for building one.</summary>
    public static TrackAnalyticsQuery Empty { get; } =
        new(null, null, null, null, null, null, null, null, null, false, false);

    /// <summary>
    /// Whether any key that makes a request analytics-dependent is set. The coverage
    /// flag alone does not count.
    /// </summary>
    public bool HasAnalyticsDependentKey =>
        SceneRevisionId is not null ||
        AnalyticsAlgorithmVersion is not null ||
        ZoneId is not null ||
        ZoneRelation is not null ||
        MinDwellMs is not null ||
        LineId is not null ||
        CrossingDirection is not null ||
        MotionDirection is not null ||
        MinStationaryMs is not null ||
        Loitering;

    /// <summary>The zone relation in force: the explicit one, or the default when a zone is named.</summary>
    public TrackZoneRelation? EffectiveZoneRelation =>
        ZoneId is null ? null : ZoneRelation ?? TrackZoneRelation.Dwelled;
}

/// <summary>
/// The dependency matrix and canonical form of an analytic query (plan §S, frozen).
/// </summary>
/// <remarks>
/// The same graph is enforced by the web canonical state, so a URL the browser will
/// write is a URL this accepts and vice versa. Nothing here reads the database: whether
/// a zone belongs to the resolved revision is the repository's question.
/// </remarks>
public static class TrackAnalyticsQueryRules
{
    public static bool IsValid(TrackAnalyticsQuery query)
    {
        ArgumentNullException.ThrowIfNull(query);

        // The flag on its own would silently turn an ordinary query into an analytic
        // one; the plan makes that a rejection rather than a surprise.
        if (!query.HasAnalyticsDependentKey)
            return false;

        if (query.SceneRevisionId == Guid.Empty ||
            query.ZoneId == Guid.Empty ||
            query.LineId == Guid.Empty)
            return false;

        if (query.AnalyticsAlgorithmVersion is { } version &&
            (query.SceneRevisionId is null || !TrackSearchContractRules.IsAlgorithmVersion(version)))
            return false;

        if ((query.ZoneRelation is not null || query.MinDwellMs is not null) && query.ZoneId is null)
            return false;

        if (query.CrossingDirection is not null && query.LineId is null)
            return false;

        if (query.MinDwellMs is < 0 || query.MinStationaryMs is < 0)
            return false;

        if (query.MotionDirection is { } heading && !TrackSearchContractRules.IsMotionDirection(heading))
            return false;

        return true;
    }

    /// <summary>
    /// The form two equal queries share: an explicit <c>dwelled</c> and an omitted
    /// relation are the same query, so the fingerprint must see them as one.
    /// </summary>
    public static TrackAnalyticsQuery Canonicalise(TrackAnalyticsQuery query)
    {
        ArgumentNullException.ThrowIfNull(query);
        return query with { ZoneRelation = query.EffectiveZoneRelation };
    }

    // --- Wire ↔ model -------------------------------------------------------

    public static bool TryParseZoneRelation(string value, out TrackZoneRelation relation)
    {
        switch (value)
        {
            case "entered": relation = TrackZoneRelation.Entered; return true;
            case "exited": relation = TrackZoneRelation.Exited; return true;
            case "dwelled": relation = TrackZoneRelation.Dwelled; return true;
            default: relation = default; return false;
        }
    }

    public static string ToWire(TrackZoneRelation relation) => relation switch
    {
        TrackZoneRelation.Entered => "entered",
        TrackZoneRelation.Exited => "exited",
        TrackZoneRelation.Dwelled => "dwelled",
        _ => throw new ArgumentOutOfRangeException(nameof(relation)),
    };

    public static bool TryParseCrossingDirection(string value, out TrackCrossingDirection direction)
    {
        switch (value)
        {
            case "aToB": direction = TrackCrossingDirection.AToB; return true;
            case "bToA": direction = TrackCrossingDirection.BToA; return true;
            default: direction = default; return false;
        }
    }

    public static string ToWire(TrackCrossingDirection direction) => direction switch
    {
        TrackCrossingDirection.AToB => "aToB",
        TrackCrossingDirection.BToA => "bToA",
        _ => throw new ArgumentOutOfRangeException(nameof(direction)),
    };

    /// <summary>The value the fact tables persist for a direction (<see cref="SceneAnalyticsVocabulary.CrossingDirections"/>).</summary>
    public static string ToPersisted(TrackCrossingDirection direction) => direction switch
    {
        TrackCrossingDirection.AToB => "AToB",
        TrackCrossingDirection.BToA => "BToA",
        _ => throw new ArgumentOutOfRangeException(nameof(direction)),
    };

    /// <summary>The wire form of a persisted direction, for responses.</summary>
    public static string PersistedDirectionToWire(string persisted) => persisted switch
    {
        "AToB" => "aToB",
        "BToA" => "bToA",
        _ => throw new ArgumentOutOfRangeException(nameof(persisted), persisted, "Unknown persisted crossing direction."),
    };
}
