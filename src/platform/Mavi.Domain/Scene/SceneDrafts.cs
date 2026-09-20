namespace Mavi.Domain.Scene;

/// <summary>A raw normalised coordinate pair as submitted, before rounding and validation.</summary>
public sealed record ScenePointDraft(double X, double Y);

/// <summary>
/// A zone as submitted. <paramref name="ZoneId"/> is null for a new zone and carries
/// an existing stable identity when the operator is keeping a zone across revisions.
/// </summary>
public sealed record SceneZoneDraft(
    Guid? ZoneId,
    string? Name,
    string? Kind,
    bool Enabled,
    IReadOnlyList<ScenePointDraft>? Vertices,
    int? LoiteringThresholdSeconds);

/// <summary>A trip line as submitted; <paramref name="LineId"/> follows the same rule as a zone's.</summary>
public sealed record TripLineDraft(
    Guid? LineId,
    string? Name,
    bool Enabled,
    ScenePointDraft? A,
    ScenePointDraft? B,
    bool Directed,
    string? AToBLabel,
    string? BToALabel);

/// <summary>The complete geometry of the revision the operator is asking to activate.</summary>
public sealed record SceneRevisionDraft(
    string? Note,
    Guid? ReferenceFrameVideoAssetId,
    long? ReferenceFrameOffsetMs,
    IReadOnlyList<SceneZoneDraft> Zones,
    IReadOnlyList<TripLineDraft> TripLines);

/// <summary>
/// The stable zone and line identities a caller is allowed to reuse, namely those
/// present in the revision currently active.
/// </summary>
public sealed class SceneIdentitySet
{
    public static readonly SceneIdentitySet Empty = new(new HashSet<Guid>(), new HashSet<Guid>());

    public SceneIdentitySet(IReadOnlySet<Guid> zoneIds, IReadOnlySet<Guid> lineIds)
    {
        ZoneIds = zoneIds;
        LineIds = lineIds;
    }

    public IReadOnlySet<Guid> ZoneIds { get; }

    public IReadOnlySet<Guid> LineIds { get; }

    public static SceneIdentitySet FromRevision(SceneConfigurationRevision? revision) =>
        revision is null
            ? Empty
            : new SceneIdentitySet(
                revision.Zones.Select(zone => zone.ZoneId).ToHashSet(),
                revision.TripLines.Select(line => line.LineId).ToHashSet());
}
