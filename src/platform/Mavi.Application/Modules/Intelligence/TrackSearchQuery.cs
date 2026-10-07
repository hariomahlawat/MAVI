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
    string? ObjectSubclass = null)
{
    public bool IsAnalytic => Analytics is not null;

    /// <summary>The canonical form: a subclass filter states its implied Vehicle class.</summary>
    public TrackSearchQuery Canonical =>
        ObjectSubclass is not null && ObjectClass is null
            ? this with { ObjectClass = Domain.Intelligence.ObjectClass.Vehicle }
            : this;
}
