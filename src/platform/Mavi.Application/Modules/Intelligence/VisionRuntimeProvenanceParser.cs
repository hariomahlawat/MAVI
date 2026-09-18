using System.Text.Json;
using Mavi.Contracts.Worker;

namespace Mavi.Application.Modules.Intelligence;

public sealed record ParsedVisionRuntimeProvenance(
    VisionRuntimeProvenanceContract Contract,
    string DetectorName,
    string DetectorVersion,
    string TrackerVersion);

public sealed class VisionRuntimeProvenanceParser
{
    private static readonly HashSet<string> AttestationDependencyAllowlist =
    [
        "python", "torch", "torchvision", "mmdet", "mmcv", "mmengine", "trackers",
        "supervision", "scipy", "numpy", "opencv", "opencvPython", "av", "pillow"
    ];

    private readonly JsonSerializerOptions _jsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false
    };

    public ParsedVisionRuntimeProvenance ParsePersisted(string runtimeProvenanceJson)
    {
        if (string.IsNullOrWhiteSpace(runtimeProvenanceJson))
            throw Invalid("provenance_missing");

        VisionRuntimeProvenanceContract? contract;
        try
        {
            contract = JsonSerializer.Deserialize<VisionRuntimeProvenanceContract>(
                runtimeProvenanceJson,
                _jsonOptions);
        }
        catch (JsonException)
        {
            throw new VisionResultValidationException("provenance_json_invalid");
        }

        if (contract is null)
            throw Invalid("provenance_json_invalid");

        return Parse(contract);
    }

    public static ParsedVisionRuntimeProvenance Parse(VisionRuntimeProvenanceContract value)
    {
        ArgumentNullException.ThrowIfNull(value);

        var modelId = RequiredBounded(value.ModelId, 128, "provenance_model_id_invalid");
        var modelVersion = RequiredBounded(value.ModelVersion, 128, "provenance_model_version_invalid");
        Sha(value.ModelManifestSha256, "provenance_model_manifest_invalid");
        Sha(value.CheckpointSha256, "provenance_checkpoint_invalid");
        Sha(value.ResolvedConfigSha256, "provenance_config_invalid");
        RequiredBounded(value.PipelineProfileId, 128, "provenance_pipeline_profile_invalid");
        RequiredBounded(value.PipelineProfileVersion, 128, "provenance_pipeline_profile_version_invalid");
        Sha(value.PipelineProfileSha256, "provenance_pipeline_profile_hash_invalid");
        RequiredBounded(value.RuntimeProfileId, 128, "provenance_runtime_profile_invalid");
        Sha(value.RuntimeProfileSha256, "provenance_runtime_profile_hash_invalid");
        RequiredBounded(value.RuntimeVariant, 128, "provenance_runtime_variant_invalid");
        RequiredBounded(value.DetectorBackend, 128, "provenance_detector_invalid");
        RequiredBounded(value.MaviBuild, 128, "provenance_mavi_build_invalid");
        RequiredBounded(value.MaviCommit, 128, "provenance_mavi_commit_invalid");

        if (value.VerificationStatus is not ("verified" or "unverified"))
            throw Invalid("provenance_verification_status_invalid");
        if (value.VerificationStatus == "verified")
        {
            RequiredBounded(value.QualificationId, 128, "provenance_qualification_required");
            Sha(value.QualificationSha256, "provenance_qualification_hash_required");
            Sha(value.PlatformLockSha256, "provenance_platform_lock_required");
        }
        else
        {
            OptionalBounded(value.QualificationId, 128, "provenance_qualification_invalid");
            OptionalSha(value.QualificationSha256, "provenance_qualification_hash_invalid");
            OptionalSha(value.PlatformLockSha256, "provenance_platform_lock_invalid");
        }

        if (value.DependencyVersions is null ||
            value.DependencyVersions.Count == 0 ||
            value.DependencyVersions.Count > WorkerContractRules.MaximumCompletionDependencyVersions)
            throw Invalid("provenance_dependencies_invalid");

        foreach (var pair in value.DependencyVersions)
        {
            RequiredBounded(pair.Key, 128, "provenance_dependency_key_invalid");
            RequiredBounded(pair.Value, 128, "provenance_dependency_version_invalid");
        }

        if (!value.DependencyVersions.TryGetValue("trackers", out var trackerVersion))
            throw Invalid("provenance_tracker_version_missing");
        trackerVersion = RequiredBounded(trackerVersion, 128, "provenance_tracker_version_invalid");
        OptionalBounded(value.FfmpegVersion, 256, "provenance_ffmpeg_version_invalid");

        if (value.Platform is null || value.Platform.PythonBuild is not { Count: 2 })
            throw Invalid("provenance_platform_invalid");
        RequiredBounded(value.Platform.System, 256, "provenance_platform_invalid");
        RequiredBounded(value.Platform.Release, 256, "provenance_platform_invalid");
        RequiredBounded(value.Platform.Version, 256, "provenance_platform_invalid");
        RequiredBounded(value.Platform.Machine, 256, "provenance_platform_invalid");
        RequiredBounded(value.Platform.Processor, 256, "provenance_platform_invalid");
        RequiredBounded(value.Platform.PythonVersion, 256, "provenance_platform_invalid");
        RequiredBounded(value.Platform.PythonImplementation, 256, "provenance_platform_invalid");
        foreach (var buildPart in value.Platform.PythonBuild)
            RequiredBounded(buildPart, 256, "provenance_platform_invalid");
        RequiredBounded(value.Platform.PythonCompiler, 256, "provenance_platform_invalid");

        if (value.ConfiguredDevicePolicy is not ("cpu" or "cuda" or "auto") ||
            value.ConfiguredDeviceIndex is not >= 0)
            throw Invalid("provenance_device_invalid");
        OptionalBounded(
            value.DeviceResolutionReason,
            64,
            "provenance_device_resolution_reason_invalid");
        if (value.DeviceResolutionReason is not null &&
            (!char.IsAsciiLetterLower(value.DeviceResolutionReason[0]) ||
             value.DeviceResolutionReason.Any(character =>
                 !(char.IsAsciiLetterLower(character) ||
                   char.IsAsciiDigit(character) ||
                   character == '_'))))
            throw Invalid("provenance_device_resolution_reason_invalid");
        RequiredBounded(value.ActualDevice, 128, "provenance_device_invalid");
        if (value.FramePolicy != "every-frame" || value.InputColourSpace != "RGB")
            throw Invalid("provenance_pipeline_semantics_invalid");

        var tracker = value.TrackerParameters;
        if (tracker is null ||
            !Positive(tracker.ReferenceFrameRate) ||
            !Unit(tracker.TrackActivationThreshold) ||
            !Unit(tracker.HighConfidenceThreshold) ||
            !Unit(tracker.MinimumIouThreshold) ||
            tracker.MinimumConsecutiveFrames is not >= 1 ||
            !Positive(tracker.LostTrackBufferSeconds))
            throw Invalid("provenance_tracker_parameters_invalid");

        if (value.Gpu is not null)
        {
            if (value.Gpu.Index is not >= 0 || value.Gpu.VramBytes is not > 0)
                throw Invalid("provenance_gpu_invalid");
            RequiredBounded(value.Gpu.Name, 256, "provenance_gpu_invalid");
            RequiredBounded(value.Gpu.DriverVersion, 256, "provenance_gpu_invalid");
            RequiredBounded(value.Gpu.CudaRuntimeVersion, 256, "provenance_gpu_invalid");
            RequiredBounded(value.Gpu.Uuid, 256, "provenance_gpu_invalid");
            RequiredBounded(value.Gpu.PciBusId, 128, "provenance_gpu_invalid");
            var computeCapability = RequiredBounded(
                value.Gpu.ComputeCapability,
                16,
                "provenance_gpu_invalid");
            // Must stay identical to the published schema pattern
            // ^[0-9]+\.[0-9]+$; int.TryParse would also accept signs and
            // surrounding whitespace, which the contract does not.
            var computeParts = computeCapability.Split('.');
            if (computeParts.Length != 2 ||
                computeParts.Any(part =>
                    part.Length == 0 ||
                    part.Any(character => !char.IsAsciiDigit(character))))
                throw Invalid("provenance_gpu_invalid");
        }

        return new ParsedVisionRuntimeProvenance(
            value,
            modelId,
            modelVersion,
            trackerVersion);
    }

    public static IReadOnlyDictionary<string, string> GetAttestationDependencies(
        VisionRuntimeProvenanceContract value)
    {
        if (value.DependencyVersions is null)
            throw Invalid("provenance_dependencies_invalid");

        var result = new SortedDictionary<string, string>(StringComparer.Ordinal);
        foreach (var pair in value.DependencyVersions)
        {
            if (!AttestationDependencyAllowlist.Contains(pair.Key))
                throw Invalid("provenance_dependency_not_allowlisted");
            result[pair.Key] = pair.Value;
        }

        return result;
    }

    private static string Required(string? value, string code)
    {
        if (string.IsNullOrEmpty(value) ||
            value.Contains('\0') ||
            char.IsWhiteSpace(value[0]) ||
            char.IsWhiteSpace(value[^1]))
            throw Invalid(code);
        return value;
    }

    private static string RequiredBounded(string? value, int maximumLength, string code)
    {
        var text = Required(value, code);
        if (text.EnumerateRunes().Count() > maximumLength)
            throw Invalid(code);
        return text;
    }

    private static string Sha(string? value, string code)
    {
        if (value is not { Length: 64 } ||
            value.Any(character => !(character is >= '0' and <= '9' or >= 'a' and <= 'f')))
            throw Invalid(code);
        return value;
    }

    private static void OptionalBounded(string? value, int maximumLength, string code)
    {
        if (value is not null)
            RequiredBounded(value, maximumLength, code);
    }

    private static void OptionalSha(string? value, string code)
    {
        if (value is not null)
            Sha(value, code);
    }

    private static bool Unit(double? value) =>
        value is { } item && double.IsFinite(item) && item is >= 0 and <= 1;

    private static bool Positive(double? value) =>
        value is { } item &&
        double.IsFinite(item) &&
        item >= WorkerContractRules.MinimumPositiveTrackerParameter &&
        item <= WorkerContractRules.MaximumPositiveTrackerParameter;

    private static VisionResultValidationException Invalid(string code) => new(code);
}
