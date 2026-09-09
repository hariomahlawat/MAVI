using System.Text.Json.Serialization;

namespace Mavi.Contracts.Worker;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionJobLeaseRequest(string? SchemaVersion, string? WorkerId);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionJobLeaseContract(
    string SchemaVersion, Guid JobId, Guid ProcessingRunId, Guid VideoAssetId, Guid CameraId,
    string WorkerId, string LeaseToken, int AttemptCount,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset LeaseExpiresAtUtc,
    string Pipeline, string PipelineVersion, string SourceStorageKey, string SourceSha256,
    long SourceSizeBytes,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset RecordingStartUtc,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset RecordingEndUtc,
    long DurationMs, int Width, int Height, int FrameRateNumerator, int FrameRateDenominator,
    string RecordingTimeZoneId, int RecordingUtcOffsetMinutes);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionJobHeartbeatRequest(string? SchemaVersion, string? WorkerId, string? LeaseToken, double? ProgressPercent);

public sealed record VisionJobHeartbeatResponse(string SchemaVersion, double ProgressPercent,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset LeaseExpiresAtUtc);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionJobFailRequest(string? SchemaVersion, string? WorkerId, string? LeaseToken,
    string? FailureCode, string? FailureMessage);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record WorkerHealthContract(string SchemaVersion, string WorkerId, string Status,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset TimestampUtc);
