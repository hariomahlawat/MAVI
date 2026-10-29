using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>One Track search as the endpoint parsed it.</summary>
/// <remarks>
/// <paramref name="Analytics"/> is null for an ordinary search, which keeps every
/// pre-Slice-4 path — validation, fingerprint, v2 cursor, repository — exactly as it
/// was. It is set only when the request carried an analytics-dependent key.
/// <para>
/// <paramref name="ObjectSubclass"/> is the operator-facing vehicle subclass filter (Stage 3,
/// X2). Null leaves every pre-X2 path exactly as it was. When set it must be a value
/// <see cref="VehicleSubclassExposurePolicy"/> exposes, and it implies
/// <see cref="ObjectClass.Vehicle"/>; <see cref="Canonical"/> makes that implication explicit,
/// so <c>objectSubclass=car</c> and <c>objectClass=Vehicle&amp;objectSubclass=car</c> are one search.
/// </para>
/// <para>
/// <paramref name="Plate"/> is the Stage-4 plate predicate (plan §5.4). Null leaves every pre-Stage-4
/// path exactly as it was. When set it implies <see cref="ObjectClass.Vehicle"/> in the same way, and
/// the search is paged by the v4 cursor whether or not analytic predicates are combined with it.
/// </para>
/// </remarks>
public sealed record TrackSearchQuery(
    Guid? CameraId,
    Guid? VideoAssetId,
    Guid? ProcessingRunId,
    ObjectClass? ObjectClass,
    DateTimeOffset? FromUtc,
    DateTimeOffset? ToUtc,
    long? MinimumDurationMs,
    double? MinimumConfidence,
    string? Cursor,
    int Limit = 50,
    TrackAnalyticsQuery? Analytics = null,
    string? ObjectSubclass = null,
    TrackPlateQuery? Plate = null,
    TrackAttributeQuery? Attributes = null)
{
    public bool IsAnalytic => Analytics is not null;

    public bool IsPlate => Plate is not null;

    /// <summary>
    /// A visual-attribute search (PoC S5; Stage-2 plan §16). The object class its types imply is resolved against the
    /// bound schema by the service, which then searches the query with that class stated.
    /// </summary>
    public bool IsAttribute => Attributes is not null;

    /// <summary>The canonical form: a subclass or plate filter states its implied Vehicle class.</summary>
    public TrackSearchQuery Canonical =>
        (ObjectSubclass is not null || Plate is not null) && ObjectClass is null
            ? this with { ObjectClass = Domain.Intelligence.ObjectClass.Vehicle }
            : this;
}
