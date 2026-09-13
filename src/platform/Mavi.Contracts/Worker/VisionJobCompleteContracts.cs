using System.Text.Json.Serialization;

namespace Mavi.Contracts.Worker;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionJobCompleteRequest(
    string? SchemaVersion,
    Guid? JobId,
    string? WorkerId,
    string? LeaseToken,
    int? AttemptCount,
    long? FramesProcessed,
    long? ProcessingDurationMs,
    VisionRuntimeProvenanceContract? Provenance,
    IReadOnlyList<VisionTrackResultContract>? Tracks);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionRuntimeProvenanceContract(
    string? ModelId,
    string? ModelVersion,
    string? ModelManifestSha256,
    string? CheckpointSha256,
    string? ResolvedConfigSha256,
    string? PipelineProfileId,
    string? PipelineProfileVersion,
    string? PipelineProfileSha256,
    string? QualificationId,
    string? QualificationSha256,
    string? VerificationStatus,
    string? RuntimeProfileId,
    string? RuntimeProfileSha256,
    string? RuntimeVariant,
    string? PlatformLockSha256,
    string? DetectorBackend,
    IReadOnlyDictionary<string, string>? DependencyVersions,
    string? FfmpegVersion,
    VisionPlatformIdentityContract? Platform,
    string? ConfiguredDevicePolicy,
    int? ConfiguredDeviceIndex,
    string? ActualDevice,
    VisionGpuIdentityContract? Gpu,
    string? MaviBuild,
    string? MaviCommit,
    string? FramePolicy,
    VisionTrackerParametersContract? TrackerParameters,
    string? InputColourSpace);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionPlatformIdentityContract(
    string? System,
    string? Release,
    string? Version,
    string? Machine,
    string? Processor,
    string? PythonVersion,
    string? PythonImplementation,
    IReadOnlyList<string>? PythonBuild,
    string? PythonCompiler);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionGpuIdentityContract(
    string? Name,
    int? Index,
    long? VramBytes,
    string? DriverVersion,
    string? CudaRuntimeVersion);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionTrackerParametersContract(
    double? ReferenceFrameRate,
    double? TrackActivationThreshold,
    double? HighConfidenceThreshold,
    double? MinimumIouThreshold,
    int? MinimumConsecutiveFrames,
    double? LostTrackBufferSeconds);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionTrackResultContract(
    string? TrackId,
    string? ObjectClass,
    long? StartOffsetMs,
    long? EndOffsetMs,
    int? DetectionCount,
    double? MeanConfidence,
    double? MaxConfidence,
    VisionRepresentativeObservationContract? Representative,
    VisionArtifactDescriptorContract? TrajectoryArtifact);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionRepresentativeObservationContract(
    long? OffsetMs,
    long? SourceFrameNumber,
    double? Confidence,
    double? QualityScore,
    VisionBoundingBoxContract? BoundingBox,
    VisionArtifactDescriptorContract? Thumbnail);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionBoundingBoxContract(double? X, double? Y, double? Width, double? Height);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionArtifactDescriptorContract(
    string? StorageKey,
    string? MediaType,
    long? SizeBytes,
    string? Sha256);

public sealed record VisionJobCompleteResponse(
    string SchemaVersion,
    Guid JobId,
    Guid ProcessingRunId,
    int TracksAccepted,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset CompletedAtUtc);
