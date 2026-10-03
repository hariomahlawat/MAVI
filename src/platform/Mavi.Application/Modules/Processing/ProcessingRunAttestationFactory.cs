using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Processing;

namespace Mavi.Application.Modules.Processing;

/// <summary>
/// The one construction of a completed processing run's attestation. The attestation
/// endpoint and the read-only measurement export both build it here, so an exported
/// attestation is the endpoint's response for the same persisted run.
/// </summary>
public static class ProcessingRunAttestationFactory
{
    /// <exception cref="VisionResultValidationException">The persisted dependency versions are invalid.</exception>
    public static ProcessingRunAttestationResponse Build(
        ProcessingRunAttestationSource source,
        ParsedVisionRuntimeProvenance parsed)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentNullException.ThrowIfNull(parsed);

        var dependencies = VisionRuntimeProvenanceParser.GetAttestationDependencies(parsed.Contract);
        var value = parsed.Contract;
        var platform = value.Platform!;
        return new ProcessingRunAttestationResponse(
            source.ProcessingRunId,
            source.VideoAssetId,
            source.CompletedAtUtc,
            source.PipelineVersion,
            value.ModelId!,
            value.ModelVersion!,
            value.ModelManifestSha256!,
            value.CheckpointSha256!,
            value.ResolvedConfigSha256!,
            value.PipelineProfileId!,
            value.PipelineProfileVersion!,
            value.PipelineProfileSha256!,
            value.QualificationId,
            value.QualificationSha256,
            value.VerificationStatus!,
            value.RuntimeProfileId!,
            value.RuntimeProfileSha256!,
            value.RuntimeVariant!,
            value.PlatformLockSha256,
            value.MaviBuild!,
            value.MaviCommit!,
            value.ConfiguredDevicePolicy!,
            value.ConfiguredDeviceIndex!.Value,
            value.DeviceResolutionReason,
            value.ActualDevice!,
            new ProcessingRunPlatformAttestationResponse(
                platform.System!,
                platform.Release!,
                platform.Version!,
                platform.Machine!,
                platform.Processor!,
                platform.PythonVersion!,
                platform.PythonImplementation!,
                platform.PythonBuild!,
                platform.PythonCompiler!),
            value.Gpu is null
                ? null
                : new ProcessingRunGpuAttestationResponse(
                    value.Gpu.Name!,
                    value.Gpu.Index!.Value,
                    value.Gpu.VramBytes!.Value,
                    value.Gpu.DriverVersion!,
                    value.Gpu.CudaRuntimeVersion!,
                    value.Gpu.Uuid!,
                    value.Gpu.PciBusId!,
                    value.Gpu.ComputeCapability!),
            dependencies,
            source.DetectorName,
            source.DetectorVersion,
            source.TrackerName,
            source.TrackerVersion,
            source.FramesProcessed,
            source.TracksCreated,
            source.ProcessingDurationMs,
            value.CapabilityId,
            value.ModelPackId,
            value.RuntimePackId,
            value.RuntimePackSource,
            value.ComponentBindingSha256);
    }
}
