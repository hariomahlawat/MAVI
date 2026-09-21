using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>One Track search as the endpoint parsed it.</summary>
/// <remarks>
/// <paramref name="Analytics"/> is null for an ordinary search, which keeps every
/// pre-Slice-4 path — validation, fingerprint, v2 cursor, repository — exactly as it
/// was. It is set only when the request carried an analytics-dependent key.
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
    TrackAnalyticsQuery? Analytics = null)
{
    public bool IsAnalytic => Analytics is not null;
}
