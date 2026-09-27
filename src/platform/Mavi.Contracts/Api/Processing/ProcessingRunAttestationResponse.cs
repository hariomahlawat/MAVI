using System.Text.Json.Serialization;

namespace Mavi.Contracts.Api.Processing;

public sealed record ProcessingRunAttestationResponse(
    Guid ProcessingRunId,
    Guid VideoAssetId,
    DateTimeOffset CompletedAtUtc,
    string PipelineVersion,
    string ModelId,
    string ModelVersion,
    string ModelManifestSha256,
    string CheckpointSha256,
    string ResolvedConfigSha256,
    string PipelineProfileId,
    string PipelineProfileVersion,
    string PipelineProfileSha256,
    string? QualificationId,
    string? QualificationSha256,
    string VerificationStatus,
    string RuntimeProfileId,
    string RuntimeProfileSha256,
    string RuntimeVariant,
    string? PlatformLockSha256,
    string MaviBuild,
    string MaviCommit,
    string ConfiguredDevicePolicy,
    int ConfiguredDeviceIndex,
    string? DeviceResolutionReason,
    string ActualDevice,
    ProcessingRunPlatformAttestationResponse Platform,
    ProcessingRunGpuAttestationResponse? Gpu,
    IReadOnlyDictionary<string, string> DependencyVersions,
    string? DetectorName,
    string? DetectorVersion,
    string? TrackerName,
    string? TrackerVersion,
    long FramesProcessed,
    int TracksCreated,
    long ProcessingDurationMs,
    // Completion 3.2 component identity (S2a plan §4.5); absent for runs completed
    // under an earlier completion version.
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? CapabilityId = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? ModelPackId = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? RuntimePackId = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? RuntimePackSource = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? ComponentBindingSha256 = null);

public sealed record ProcessingRunPlatformAttestationResponse(
    string System,
    string Release,
    string Version,
    string Machine,
    string Processor,
    string PythonVersion,
    string PythonImplementation,
    IReadOnlyList<string> PythonBuild,
    string PythonCompiler);

public sealed record ProcessingRunGpuAttestationResponse(
    string Name,
    int Index,
    long VramBytes,
    string DriverVersion,
    string CudaRuntimeVersion,
    string Uuid,
    string PciBusId,
    string ComputeCapability);
