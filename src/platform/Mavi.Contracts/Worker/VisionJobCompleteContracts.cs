using System.Text.Json.Serialization;

namespace Mavi.Contracts.Worker;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionJobCompleteRequest(
    string? SchemaVersion,
    Guid? JobId,
    string? WorkerId,
    string? LeaseToken,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? AttemptCount,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? FramesProcessed,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? ProcessingDurationMs,
    VisionRuntimeProvenanceContract? Provenance,
    [property: JsonConverter(typeof(BoundedVisionTrackListJsonConverter))] IReadOnlyList<VisionTrackResultContract>? Tracks,
    // Completion 3.0 only. A 2.0 body omits it; a 3.0 body requires it.
    [property: JsonConverter(typeof(PresentObjectJsonConverter<VisionEvidenceAccountingContract>))]
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    VisionEvidenceAccountingContract? EvidenceAccounting = null);

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
    [property: JsonConverter(typeof(BoundedDependencyVersionsJsonConverter))]
    IReadOnlyDictionary<string, string>? DependencyVersions,
    string? FfmpegVersion,
    VisionPlatformIdentityContract? Platform,
    string? ConfiguredDevicePolicy,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? ConfiguredDeviceIndex,
    string? ActualDevice,
    VisionGpuIdentityContract? Gpu,
    string? MaviBuild,
    string? MaviCommit,
    string? FramePolicy,
    VisionTrackerParametersContract? TrackerParameters,
    string? InputColourSpace,
    string? DeviceResolutionReason = null);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionPlatformIdentityContract(
    string? System,
    string? Release,
    string? Version,
    string? Machine,
    string? Processor,
    string? PythonVersion,
    string? PythonImplementation,
    [property: JsonConverter(typeof(BoundedPythonBuildJsonConverter))]
    IReadOnlyList<string>? PythonBuild,
    string? PythonCompiler);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionGpuIdentityContract(
    string? Name,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? Index,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? VramBytes,
    string? DriverVersion,
    string? CudaRuntimeVersion,
    string? Uuid = null,
    string? PciBusId = null,
    string? ComputeCapability = null);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionTrackerParametersContract(
    double? ReferenceFrameRate,
    double? TrackActivationThreshold,
    double? HighConfidenceThreshold,
    double? MinimumIouThreshold,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? MinimumConsecutiveFrames,
    double? LostTrackBufferSeconds);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionTrackResultContract(
    string? TrackId,
    string? ObjectClass,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? StartOffsetMs,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? EndOffsetMs,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? DetectionCount,
    double? MeanConfidence,
    double? MaxConfidence,
    // Completion 2.0 carries exactly one Representative; completion 3.0 carries
    // the bounded Evidence Set in Observations instead. Each version requires its
    // own member and forbids the other, so one binding path serves both.
    // Version-exclusive members are omitted when null so each version round-trips exactly.
    [property: JsonConverter(typeof(PresentObjectJsonConverter<VisionRepresentativeObservationContract>))]
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    VisionRepresentativeObservationContract? Representative,
    VisionArtifactDescriptorContract? TrajectoryArtifact,
    [property: JsonConverter(typeof(BoundedVisionObservationListJsonConverter))]
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    IReadOnlyList<VisionTrackObservationContract>? Observations = null);

/// <summary>One accepted Evidence Set observation of a completion 3.0 Track.</summary>
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionTrackObservationContract(
    string? Role,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? Rank,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? OffsetMs,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? SourceFrameNumber,
    double? Confidence,
    double? QualityScore,
    double? SelectionScore,
    VisionBoundingBoxContract? BoundingBox,
    VisionArtifactDescriptorContract? Crop);

/// <summary>Per-role candidate/admission accounting of a completion 3.0 body.</summary>
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionEvidenceAccountingContract(
    [property: JsonPropertyName("representative")] VisionEvidenceRoleAccountingContract? Representative,
    [property: JsonPropertyName("near-view")] VisionEvidenceRoleAccountingContract? NearView,
    [property: JsonPropertyName("early-diverse")] VisionEvidenceRoleAccountingContract? EarlyDiverse,
    [property: JsonPropertyName("late-diverse")] VisionEvidenceRoleAccountingContract? LateDiverse);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionEvidenceRoleAccountingContract(
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? Candidates,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? Admitted,
    [property: JsonConverter(typeof(IntegralNullableInt32JsonConverter))] int? Omitted,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? CandidateBytes,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? AdmittedBytes);

/// <summary>What completion versions this platform accepts (GET /api/vision/contract).</summary>
public sealed record VisionContractCapabilitiesResponse(
    string SchemaVersion,
    IReadOnlyList<string> CompletionSchemaVersions);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionRepresentativeObservationContract(
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? OffsetMs,
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? SourceFrameNumber,
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
    [property: JsonConverter(typeof(IntegralNullableInt64JsonConverter))] long? SizeBytes,
    string? Sha256);

public sealed record VisionJobCompleteResponse(
    string SchemaVersion,
    Guid JobId,
    Guid ProcessingRunId,
    int TracksAccepted,
    [property: JsonConverter(typeof(UtcDateTimeOffsetJsonConverter))] DateTimeOffset CompletedAtUtc);
