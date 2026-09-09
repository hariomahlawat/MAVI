namespace Mavi.Contracts.Worker;

public sealed record BoundingBoxContract(double X, double Y, double Width, double Height);
public sealed record VisionObservationContract(string TrackId, string EntityType, DateTimeOffset TimestampUtc,
    double Confidence, BoundingBoxContract BoundingBox);
public sealed record VisionResultContract(Guid JobId, string Status,
    IReadOnlyList<VisionObservationContract> Observations, string SchemaVersion = "1.0");
