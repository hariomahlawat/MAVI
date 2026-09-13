using System.Buffers.Binary;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Contracts.Worker;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Intelligence;

public sealed record ValidatedArtifactDescriptor(
    string StorageKey,
    string MediaType,
    long SizeBytes,
    string Sha256);

public sealed record ValidatedRepresentativeObservation(
    long OffsetMs,
    long SourceFrameNumber,
    double Confidence,
    double QualityScore,
    double X,
    double Y,
    double Width,
    double Height,
    ValidatedArtifactDescriptor Thumbnail);

public sealed record ValidatedTrackResult(
    string TrackId,
    ObjectClass ObjectClass,
    long StartOffsetMs,
    long EndOffsetMs,
    int DetectionCount,
    double MeanConfidence,
    double MaxConfidence,
    ValidatedRepresentativeObservation Representative,
    ValidatedArtifactDescriptor TrajectoryArtifact);

public sealed record ValidatedVisionResult(
    int AttemptCount,
    long FramesProcessed,
    long ProcessingDurationMs,
    string RuntimeProvenanceJson,
    string DetectorName,
    string DetectorVersion,
    string TrackerName,
    string TrackerVersion,
    IReadOnlyList<ValidatedTrackResult> Tracks,
    string CompletionDigest);

public sealed class VisionResultValidationException(string reasonCode)
    : Exception("The vision result is invalid.")
{
    public string ReasonCode { get; } = reasonCode;
}

public sealed class VisionResultValidator
{
    private readonly JsonSerializerOptions _jsonOptions = new(JsonSerializerDefaults.Web);

    public ValidatedVisionResult Validate(Guid routeJobId, VisionJobCompleteRequest request, long videoDurationMs)
    {
        ArgumentNullException.ThrowIfNull(request);

        if (routeJobId == Guid.Empty || request.JobId != routeJobId)
            throw Invalid("job_id_mismatch");
        if (request.AttemptCount is not >= 1)
            throw Invalid("attempt_count_invalid");
        if (request.FramesProcessed is not >= 0)
            throw Invalid("frames_processed_invalid");
        if (request.ProcessingDurationMs is not >= 0)
            throw Invalid("processing_duration_invalid");
        if (request.Provenance is null || request.Tracks is null)
            throw Invalid("required_member_missing");
        if (request.FramesProcessed == 0 && request.Tracks.Count > 0)
            throw Invalid("tracks_without_frames");
        if (videoDurationMs <= 0)
            throw Invalid("video_duration_invalid");

        var provenance = ValidateProvenance(request.Provenance);
        var trackIds = new HashSet<string>(StringComparer.Ordinal);
        var artifactKeys = new HashSet<string>(StringComparer.Ordinal);
        var tracks = new List<ValidatedTrackResult>(request.Tracks.Count);

        foreach (var contract in request.Tracks)
        {
            if (contract is null)
                throw Invalid("track_missing");

            var trackId = RequiredSafeIdentifier(contract.TrackId, "track_id_invalid");
            if (!trackIds.Add(trackId))
                throw Invalid("track_id_duplicate");

            var objectClass = contract.ObjectClass switch
            {
                "person" => ObjectClass.Person,
                "vehicle" => ObjectClass.Vehicle,
                _ => throw Invalid("object_class_invalid"),
            };

            if (contract.StartOffsetMs is not { } startOffsetMs || startOffsetMs < 0 ||
                contract.EndOffsetMs is not { } endOffsetMs || endOffsetMs < startOffsetMs ||
                endOffsetMs > videoDurationMs)
                throw Invalid("track_offsets_invalid");
            if (contract.DetectionCount is not >= 1)
                throw Invalid("detection_count_invalid");
            if (!Unit(contract.MeanConfidence) || !Unit(contract.MaxConfidence) ||
                contract.MeanConfidence > contract.MaxConfidence)
                throw Invalid("track_confidence_invalid");
            if (contract.Representative is null || contract.TrajectoryArtifact is null)
                throw Invalid("track_evidence_missing");

            var representative = contract.Representative;
            if (representative.OffsetMs is not { } repOffset || repOffset < startOffsetMs || repOffset > endOffsetMs ||
                representative.SourceFrameNumber is not >= 0 ||
                !Unit(representative.Confidence) || !Unit(representative.QualityScore) ||
                representative.Confidence > contract.MaxConfidence ||
                representative.BoundingBox is null || representative.Thumbnail is null)
                throw Invalid("representative_invalid");

            var box = representative.BoundingBox;
            if (!Unit(box.X) || !Unit(box.Y) || !PositiveUnit(box.Width) || !PositiveUnit(box.Height) ||
                box.X!.Value + box.Width!.Value > 1 || box.Y!.Value + box.Height!.Value > 1)
                throw Invalid("bounding_box_invalid");

            var expectedPrefix = $"staging/{routeJobId:D}/attempt-{request.AttemptCount.Value:0000}";
            var thumbnail = ValidateArtifact(
                representative.Thumbnail,
                $"{expectedPrefix}/thumbnails/{trackId}.jpg",
                "image/jpeg",
                artifactKeys);
            var trajectory = ValidateArtifact(
                contract.TrajectoryArtifact,
                $"{expectedPrefix}/trajectories/{trackId}.msgpack",
                "application/msgpack",
                artifactKeys);

            tracks.Add(new ValidatedTrackResult(
                trackId,
                objectClass,
                startOffsetMs,
                endOffsetMs,
                contract.DetectionCount.Value,
                contract.MeanConfidence!.Value,
                contract.MaxConfidence!.Value,
                new ValidatedRepresentativeObservation(
                    repOffset,
                    representative.SourceFrameNumber!.Value,
                    representative.Confidence!.Value,
                    representative.QualityScore!.Value,
                    box.X!.Value,
                    box.Y!.Value,
                    box.Width!.Value,
                    box.Height!.Value,
                    thumbnail),
                trajectory));
        }

        tracks.Sort((left, right) => StringComparer.Ordinal.Compare(left.TrackId, right.TrackId));

        var runtimeJson = JsonSerializer.Serialize(request.Provenance, _jsonOptions);
        var digest = ComputeDigest(
            routeJobId,
            request.AttemptCount.Value,
            request.FramesProcessed.Value,
            request.ProcessingDurationMs.Value,
            request.Provenance,
            tracks);

        return new ValidatedVisionResult(
            request.AttemptCount.Value,
            request.FramesProcessed.Value,
            request.ProcessingDurationMs.Value,
            runtimeJson,
            provenance.DetectorName,
            provenance.DetectorVersion,
            "ByteTrack",
            provenance.TrackerVersion,
            tracks,
            digest);
    }

    private static (string DetectorName, string DetectorVersion, string TrackerVersion) ValidateProvenance(
        VisionRuntimeProvenanceContract value)
    {
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

        if (value.DependencyVersions is null || value.DependencyVersions.Count == 0)
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
        }

        return (modelId, modelVersion, trackerVersion);
    }

    private static ValidatedArtifactDescriptor ValidateArtifact(
        VisionArtifactDescriptorContract value,
        string expectedStorageKey,
        string expectedMediaType,
        HashSet<string> artifactKeys)
    {
        if (!string.Equals(value.StorageKey, expectedStorageKey, StringComparison.Ordinal) ||
            !string.Equals(value.MediaType, expectedMediaType, StringComparison.Ordinal) ||
            value.SizeBytes is not >= 0)
            throw Invalid("artifact_descriptor_invalid");

        var sha = Sha(value.Sha256, "artifact_sha256_invalid");
        if (!artifactKeys.Add(expectedStorageKey))
            throw Invalid("artifact_storage_key_duplicate");

        return new ValidatedArtifactDescriptor(expectedStorageKey, expectedMediaType, value.SizeBytes.Value, sha);
    }

    private static string ComputeDigest(
        Guid jobId,
        int attemptCount,
        long framesProcessed,
        long processingDurationMs,
        VisionRuntimeProvenanceContract provenance,
        IReadOnlyList<ValidatedTrackResult> tracks)
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);

        void Add(string value)
        {
            var bytes = Encoding.UTF8.GetBytes(value);
            Span<byte> length = stackalloc byte[4];
            BinaryPrimitives.WriteInt32BigEndian(length, bytes.Length);
            hash.AppendData(length);
            hash.AppendData(bytes);
        }

        void AddNullable(string? value)
        {
            Add(value is null ? "<null>" : value);
        }

        void AddNumber<T>(T value) where T : IFormattable =>
            Add(value.ToString(null, CultureInfo.InvariantCulture));

        Add(jobId.ToString("D"));
        AddNumber(attemptCount);
        AddNumber(framesProcessed);
        AddNumber(processingDurationMs);

        Add(Required(provenance.ModelId, "provenance_model_id_invalid"));
        Add(Required(provenance.ModelVersion, "provenance_model_version_invalid"));
        Add(provenance.ModelManifestSha256!);
        Add(provenance.CheckpointSha256!);
        Add(provenance.ResolvedConfigSha256!);
        Add(provenance.PipelineProfileId!);
        Add(provenance.PipelineProfileVersion!);
        Add(provenance.PipelineProfileSha256!);
        AddNullable(provenance.QualificationId);
        AddNullable(provenance.QualificationSha256);
        Add(provenance.VerificationStatus!);
        Add(provenance.RuntimeProfileId!);
        Add(provenance.RuntimeProfileSha256!);
        Add(provenance.RuntimeVariant!);
        AddNullable(provenance.PlatformLockSha256);
        Add(provenance.DetectorBackend!);
        foreach (var pair in provenance.DependencyVersions!.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            Add(pair.Key);
            Add(pair.Value);
        }
        AddNullable(provenance.FfmpegVersion);

        var platform = provenance.Platform!;
        Add(platform.System!);
        Add(platform.Release!);
        Add(platform.Version!);
        Add(platform.Machine!);
        Add(platform.Processor!);
        Add(platform.PythonVersion!);
        Add(platform.PythonImplementation!);
        foreach (var item in platform.PythonBuild!) Add(item);
        Add(platform.PythonCompiler!);

        Add(provenance.ConfiguredDevicePolicy!);
        AddNumber(provenance.ConfiguredDeviceIndex!.Value);
        Add(provenance.ActualDevice!);
        if (provenance.Gpu is null)
        {
            Add("<no-gpu>");
        }
        else
        {
            Add(provenance.Gpu.Name!);
            AddNumber(provenance.Gpu.Index!.Value);
            AddNumber(provenance.Gpu.VramBytes!.Value);
            Add(provenance.Gpu.DriverVersion!);
            Add(provenance.Gpu.CudaRuntimeVersion!);
        }

        Add(provenance.MaviBuild!);
        Add(provenance.MaviCommit!);
        Add(provenance.FramePolicy!);
        var tracker = provenance.TrackerParameters!;
        AddNumber(tracker.ReferenceFrameRate!.Value);
        AddNumber(tracker.TrackActivationThreshold!.Value);
        AddNumber(tracker.HighConfidenceThreshold!.Value);
        AddNumber(tracker.MinimumIouThreshold!.Value);
        AddNumber(tracker.MinimumConsecutiveFrames!.Value);
        AddNumber(tracker.LostTrackBufferSeconds!.Value);
        Add(provenance.InputColourSpace!);

        foreach (var track in tracks)
        {
            Add(track.TrackId);
            Add(track.ObjectClass.ToString());
            AddNumber(track.StartOffsetMs);
            AddNumber(track.EndOffsetMs);
            AddNumber(track.DetectionCount);
            AddNumber(track.MeanConfidence);
            AddNumber(track.MaxConfidence);
            AddNumber(track.Representative.OffsetMs);
            AddNumber(track.Representative.SourceFrameNumber);
            AddNumber(track.Representative.Confidence);
            AddNumber(track.Representative.QualityScore);
            AddNumber(track.Representative.X);
            AddNumber(track.Representative.Y);
            AddNumber(track.Representative.Width);
            AddNumber(track.Representative.Height);
            Add(track.Representative.Thumbnail.StorageKey);
            Add(track.Representative.Thumbnail.MediaType);
            AddNumber(track.Representative.Thumbnail.SizeBytes);
            Add(track.Representative.Thumbnail.Sha256);
            Add(track.TrajectoryArtifact.StorageKey);
            Add(track.TrajectoryArtifact.MediaType);
            AddNumber(track.TrajectoryArtifact.SizeBytes);
            Add(track.TrajectoryArtifact.Sha256);
        }

        return Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
    }

    private static string RequiredSafeIdentifier(string? value, string code)
    {
        var text = Required(value, code);
        if (text.Length > 64 || !IsAsciiAlphaNumeric(text[0]) ||
            text.Skip(1).Any(character => !IsAsciiAlphaNumeric(character) && character is not '.' and not '_' and not '-'))
            throw Invalid(code);
        return text;
    }

    private static string Required(string? value, string code)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw Invalid(code);
        return value;
    }

    private static string RequiredBounded(string? value, int maximumLength, string code)
    {
        var text = Required(value, code);
        if (text.Length > maximumLength)
            throw Invalid(code);
        return text;
    }

    private static string Sha(string? value, string code)
    {
        if (value is not { Length: 64 } || value.Any(character => !(character is >= '0' and <= '9' or >= 'a' and <= 'f')))
            throw Invalid(code);
        return value;
    }

    private static void OptionalBounded(
        string? value,
        int maximumLength,
        string code)
    {
        if (value is not null)
            RequiredBounded(value, maximumLength, code);
    }

    private static void OptionalSha(string? value, string code)
    {
        if (value is not null) Sha(value, code);
    }

    private static bool Unit(double? value) => value is { } item && double.IsFinite(item) && item is >= 0 and <= 1;
    private static bool PositiveUnit(double? value) => Unit(value) && value > 0;
    private static bool Positive(double? value) => value is { } item && double.IsFinite(item) && item > 0;
    private static bool IsAsciiAlphaNumeric(char value) =>
        value is >= 'A' and <= 'Z' or >= 'a' and <= 'z' or >= '0' and <= '9';

    private static VisionResultValidationException Invalid(string reason) => new(reason);
}
