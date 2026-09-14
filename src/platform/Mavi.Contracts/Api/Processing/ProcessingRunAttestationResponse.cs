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
    string ActualDevice,
    ProcessingRunPlatformAttestationResponse Platform,
    ProcessingRunGpuAttestationResponse? Gpu,
    IReadOnlyDictionary<string, string> DependencyVersions,
    string? DetectorName,
    string? DetectorVersion,
    string? TrackerName,
    string? TrackerVersion);

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
    string CudaRuntimeVersion);
