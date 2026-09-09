namespace Mavi.Contracts.Worker;

public sealed record WorkerHealthContract(Guid WorkerId, string Status, DateTimeOffset TimestampUtc, string SchemaVersion = "1.0");

public sealed record VisionJobContract(
    Guid JobId,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    Guid CameraId,
    string Pipeline,
    string PipelineVersion,
    string SourceStorageKey,
    string SourceSha256,
    long SourceSizeBytes,
    DateTimeOffset RecordingStartUtc,
    DateTimeOffset RecordingEndUtc,
    long DurationMs,
    int Width,
    int Height,
    int FrameRateNumerator,
    int FrameRateDenominator,
    int AttemptCount,
    DateTimeOffset LeaseExpiresAtUtc,
    string RecordingTimeZoneId,
    int RecordingUtcOffsetMinutes,
    string SchemaVersion = "1.0");

public sealed record BoundingBoxContract(double X, double Y, double Width, double Height);
public sealed record VisionObservationContract(string TrackId, string EntityType, DateTimeOffset TimestampUtc,
    double Confidence, BoundingBoxContract BoundingBox);
public sealed record VisionResultContract(Guid JobId, string Status,
    IReadOnlyList<VisionObservationContract> Observations, string SchemaVersion = "1.0");
