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
        if (request.Tracks.Count > WorkerContractRules.MaximumCompletionTracks)
            throw Invalid("track_count_invalid");
        if (request.FramesProcessed == 0 && request.Tracks.Count > 0)
            throw Invalid("tracks_without_frames");
        if (videoDurationMs <= 0)
            throw Invalid("video_duration_invalid");

        var provenance = VisionRuntimeProvenanceParser.Parse(request.Provenance);
        var trackIds = new HashSet<string>(StringComparer.Ordinal);
        var artifactKeys = new HashSet<string>(StringComparer.Ordinal);
        var tracks = new List<ValidatedTrackResult>(request.Tracks.Count);
        long aggregateEvidenceBytes = 0;

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
            if (contract.DetectionCount is not >= 1 ||
                contract.DetectionCount > request.FramesProcessed.Value)
                throw Invalid("detection_count_invalid");
            if (!Unit(contract.MeanConfidence) || !Unit(contract.MaxConfidence) ||
                contract.MeanConfidence > contract.MaxConfidence)
                throw Invalid("track_confidence_invalid");
            if (contract.Representative is null || contract.TrajectoryArtifact is null)
                throw Invalid("track_evidence_missing");

            var representative = contract.Representative;
            if (representative.OffsetMs is not { } repOffset || repOffset < startOffsetMs || repOffset > endOffsetMs ||
                representative.SourceFrameNumber is not >= 0 ||
                representative.SourceFrameNumber >= request.FramesProcessed.Value ||
                !Unit(representative.Confidence) || !Unit(representative.QualityScore) ||
                representative.Confidence > contract.MaxConfidence ||
                representative.BoundingBox is null || representative.Thumbnail is null)
                throw Invalid("representative_invalid");

            var box = representative.BoundingBox;
            if (!PersistableNormalizedBox(box.X, box.Y, box.Width, box.Height))
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

            try
            {
                aggregateEvidenceBytes = checked(
                    aggregateEvidenceBytes + thumbnail.SizeBytes + trajectory.SizeBytes);
            }
            catch (OverflowException)
            {
                throw Invalid("artifact_evidence_size_invalid");
            }
            if (aggregateEvidenceBytes > WorkerContractRules.MaximumCompletionEvidenceBytes)
                throw Invalid("artifact_evidence_size_invalid");

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

    private static ValidatedArtifactDescriptor ValidateArtifact(
        VisionArtifactDescriptorContract value,
        string expectedStorageKey,
        string expectedMediaType,
        HashSet<string> artifactKeys)
    {
        if (!string.Equals(value.StorageKey, expectedStorageKey, StringComparison.Ordinal) ||
            !string.Equals(value.MediaType, expectedMediaType, StringComparison.Ordinal) ||
            value.SizeBytes is not >= 0 ||
            value.SizeBytes > WorkerContractRules.MaximumCompletionArtifactBytes)
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
        List<ValidatedTrackResult> tracks)
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
            Span<byte> marker = stackalloc byte[1];
            marker[0] = value is null ? (byte)0 : (byte)1;
            hash.AppendData(marker);
            if (value is not null)
                Add(value);
        }

        void AddNumber<T>(T value) where T : IFormattable =>
            Add(value.ToString(null, CultureInfo.InvariantCulture));

        Add("mavi:vision-completion-digest:v2");
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
        AddNumber(provenance.DependencyVersions!.Count);
        foreach (var pair in provenance.DependencyVersions.OrderBy(pair => pair.Key, StringComparer.Ordinal))
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
        Span<byte> gpuMarker = stackalloc byte[1];
        gpuMarker[0] = provenance.Gpu is null ? (byte)0 : (byte)1;
        hash.AppendData(gpuMarker);
        if (provenance.Gpu is not null)
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

        AddNumber(tracks.Count);
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
        if (text.Length > 64 || !IsAsciiLowerAlphaNumeric(text[0]) ||
            text.Skip(1).Any(character => !IsAsciiLowerAlphaNumeric(character) && character is not '.' and not '_' and not '-'))
            throw Invalid(code);
        return text;
    }

    private static string Required(string? value, string code)
    {
        if (string.IsNullOrEmpty(value) ||
            value.Contains('\0') ||
            IsContractEdgeWhitespace(value[0]) ||
            IsContractEdgeWhitespace(value[^1]))
            throw Invalid(code);
        return value;
    }

    private static bool IsContractEdgeWhitespace(char value) =>
        value is >= '\u0009' and <= '\u000D' or
            '\u0020' or
            '\u0085' or
            '\u00A0' or
            '\u1680' or
            >= '\u2000' and <= '\u200A' or
            '\u2028' or
            '\u2029' or
            '\u202F' or
            '\u205F' or
            '\u3000' or
            '\uFEFF';

    private static string RequiredBounded(string? value, int maximumLength, string code)
    {
        var text = Required(value, code);
        if (text.EnumerateRunes().Count() > maximumLength)
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
    private static bool PersistablePositiveDimension(double? value) =>
        PositiveUnit(value) && value >= float.Epsilon;

    private static bool PersistableNormalizedBox(
        double? x,
        double? y,
        double? width,
        double? height)
    {
        if (!Unit(x) || !Unit(y) ||
            !PersistablePositiveDimension(width) ||
            !PersistablePositiveDimension(height) ||
            x!.Value + width!.Value > 1 ||
            y!.Value + height!.Value > 1)
            return false;

        var persistedX = (float)x.Value;
        var persistedY = (float)y.Value;
        var persistedWidth = (float)width.Value;
        var persistedHeight = (float)height.Value;
        return float.IsFinite(persistedX) &&
               float.IsFinite(persistedY) &&
               float.IsFinite(persistedWidth) &&
               float.IsFinite(persistedHeight) &&
               persistedWidth > 0 &&
               persistedHeight > 0 &&
               persistedX + persistedWidth <= 1 &&
               persistedY + persistedHeight <= 1;
    }

    private static bool Positive(double? value) =>
        value is { } item &&
        double.IsFinite(item) &&
        item >= WorkerContractRules.MinimumPositiveTrackerParameter &&
        item <= WorkerContractRules.MaximumPositiveTrackerParameter;
    private static bool IsAsciiLowerAlphaNumeric(char value) =>
        value is >= 'a' and <= 'z' or >= '0' and <= '9';

    private static VisionResultValidationException Invalid(string reason) => new(reason);
}
