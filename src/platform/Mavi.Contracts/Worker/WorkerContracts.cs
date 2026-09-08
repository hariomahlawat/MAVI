namespace Mavi.Contracts.Worker;

public sealed record WorkerHealthContract(
    Guid WorkerId,
    string Status,
    DateTimeOffset TimestampUtc,
    string SchemaVersion = "1.0");

public sealed record VisionJobContract(
    Guid JobId,
    Guid VideoAssetId,
    string CameraId,
    string MediaUri,
    DateTimeOffset? StartUtc = null,
    DateTimeOffset? EndUtc = null,
    string SchemaVersion = "1.0");

public sealed record BoundingBoxContract(
    double X,
    double Y,
    double Width,
    double Height);

public sealed record VisionObservationContract(
    string TrackId,
    string EntityType,
    DateTimeOffset TimestampUtc,
    double Confidence,
    BoundingBoxContract BoundingBox);

public sealed record VisionResultContract(
    Guid JobId,
    string Status,
    IReadOnlyList<VisionObservationContract> Observations,
    string SchemaVersion = "1.0");
