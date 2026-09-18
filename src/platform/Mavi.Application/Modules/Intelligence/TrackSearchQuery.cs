using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Intelligence;

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
    int Limit = 50);
