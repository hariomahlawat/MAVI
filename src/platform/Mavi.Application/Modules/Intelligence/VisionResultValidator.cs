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

/// <summary>The completion schema a validated body was written in.</summary>
public enum CompletionSchema
{
    /// <summary>Completion 2.0: one Representative thumbnail per Track.</summary>
    V2,
    /// <summary>Completion 3.0: the bounded Track Evidence Set.</summary>
    V3,
    /// <summary>
    /// Completion 3.2: the same Evidence Set as 3.0 plus component-identity provenance,
    /// under its own digest domain (S2a plan P-7, §4.5).
    /// </summary>
    V32,
    /// <summary>
    /// Completion 3.3: the 3.2 body plus the detector-native vehicle subclass, under its
    /// own digest domain (Stage 3, ADR-016).
    /// </summary>
    V33,
}

public static class CompletionSchemaExtensions
{
    /// <summary>
    /// Whether a schema carries the bounded Track Evidence Set (3.0 and 3.2). Every
    /// evidence-shape rule branches on this, never on one version, so a new Evidence
    /// Set version cannot silently skip a check.
    /// </summary>
    public static bool IsEvidenceSet(this CompletionSchema schema) => schema switch
    {
        CompletionSchema.V2 => false,
        CompletionSchema.V3 or CompletionSchema.V32 or CompletionSchema.V33 => true,
        _ => throw new ArgumentOutOfRangeException(nameof(schema)),
    };

    /// <summary>Whether a schema's provenance carries component identity (3.2 and later).</summary>
    public static bool HasComponentIdentity(this CompletionSchema schema) => schema switch
    {
        CompletionSchema.V2 or CompletionSchema.V3 => false,
        CompletionSchema.V32 or CompletionSchema.V33 => true,
        _ => throw new ArgumentOutOfRangeException(nameof(schema)),
    };

    /// <summary>Whether a schema carries the detector-native vehicle subclass (3.3 and later).</summary>
    public static bool HasVehicleSubclass(this CompletionSchema schema) => schema switch
    {
        CompletionSchema.V2 or CompletionSchema.V3 or CompletionSchema.V32 => false,
        CompletionSchema.V33 => true,
        _ => throw new ArgumentOutOfRangeException(nameof(schema)),
    };
}

/// <summary>
/// One accepted observation of a Track. Completion 2.0 normalises to a single
/// Representative whose selection score equals its quality score.
/// </summary>
public sealed record ValidatedObservation(
    ObservationType Role,
    int Rank,
    long OffsetMs,
    long SourceFrameNumber,
    double Confidence,
    double QualityScore,
    double SelectionScore,
    double X,
    double Y,
    double Width,
    double Height,
    ValidatedArtifactDescriptor Crop);

public sealed record ValidatedTrackResult(
    string TrackId,
    ObjectClass ObjectClass,
    long StartOffsetMs,
    long EndOffsetMs,
    int DetectionCount,
    double MeanConfidence,
    double MaxConfidence,
    IReadOnlyList<ValidatedObservation> Observations,
    ValidatedArtifactDescriptor TrajectoryArtifact,
    // Completion 3.3 only: the resolved detector-native vehicle subclass, or null.
    string? ObjectSubclass = null)
{
    /// <summary>The mandatory rank-0 observation; always first.</summary>
    public ValidatedObservation Representative => Observations[0];
}

public sealed record ValidatedRoleAccounting(
    int Candidates,
    int Admitted,
    int Omitted,
    long CandidateBytes,
    long AdmittedBytes);

public sealed record ValidatedEvidenceAccounting(
    ValidatedRoleAccounting Representative,
    ValidatedRoleAccounting NearView,
    ValidatedRoleAccounting EarlyDiverse,
    ValidatedRoleAccounting LateDiverse);

public sealed record ValidatedVisionResult(
    CompletionSchema Schema,
    int AttemptCount,
    long FramesProcessed,
    long ProcessingDurationMs,
    string RuntimeProvenanceJson,
    string DetectorName,
    string DetectorVersion,
    string TrackerName,
    string TrackerVersion,
    IReadOnlyList<ValidatedTrackResult> Tracks,
    ValidatedEvidenceAccounting? EvidenceAccounting,
    string CompletionDigest,
    // Completion 3.3 only (ADR-016); null for every older body.
    string? ObjectSubclassVocabulary = null,
    string? ObjectSubclassSource = null);

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

        // 3.1 is the asynchronous exchange of the same Evidence Set body: one semantic
        // shape, one digest domain (plan §5.1, §15.5). The version string never enters
        // the digest; only the schema-selected domain tag does. 3.2 adds component
        // identity to provenance and therefore has its own domain (S2a plan P-7).
        var schema = request.SchemaVersion switch
        {
            WorkerContractRules.CompletionSchemaVersionV2 => CompletionSchema.V2,
            WorkerContractRules.CompletionSchemaVersionV3 => CompletionSchema.V3,
            WorkerContractRules.CompletionSchemaVersionV31 => CompletionSchema.V3,
            WorkerContractRules.CompletionSchemaVersionV32 => CompletionSchema.V32,
            WorkerContractRules.CompletionSchemaVersionV33 => CompletionSchema.V33,
            _ => throw Invalid("schema_version_invalid"),
        };
        // Each version carries its own evidence members and forbids the other's,
        // so a body can never be read as the other version.
        if (schema == CompletionSchema.V2 && request.EvidenceAccounting is not null)
            throw Invalid("evidence_accounting_unexpected");
        if (schema.IsEvidenceSet() && request.EvidenceAccounting is null)
            throw Invalid("evidence_accounting_missing");

        var provenance = VisionRuntimeProvenanceParser.Parse(request.Provenance, schema);
        var (subclassVocabulary, subclassSource) = ValidateSubclassBody(schema, request);
        var trackIds = new HashSet<string>(StringComparer.Ordinal);
        var artifactKeys = new HashSet<string>(StringComparer.Ordinal);
        var tracks = new List<ValidatedTrackResult>(request.Tracks.Count);
        var expectedPrefix = $"staging/{routeJobId:D}/attempt-{request.AttemptCount.Value:0000}";
        // v2: thumbnails + trajectories share one 512 MiB bound. v3: trajectories
        // keep that bound; crops have their own 1 GiB quota (ADR-013 §6).
        long aggregateEvidenceBytes = 0;
        long aggregateCropBytes = 0;
        var admittedCountByRole = new int[RoleOrder.Count];
        var admittedBytesByRole = new long[RoleOrder.Count];

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
            // Only a vehicle Track may carry a subclass, and only a v1 vocabulary value
            // (ADR-016). Pre-3.3 bodies were already refused if any Track carried one.
            if (contract.ObjectSubclass is not null &&
                (objectClass != ObjectClass.Vehicle || !WorkerContractRules.VehicleSubclassValuesV1.Contains(contract.ObjectSubclass)))
                throw Invalid("object_subclass_invalid");

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
            if (contract.TrajectoryArtifact is null)
                throw Invalid("track_evidence_missing");

            var observations = schema == CompletionSchema.V2
                ? ValidateV2Evidence(contract, trackId, startOffsetMs, endOffsetMs,
                    request.FramesProcessed.Value, expectedPrefix, artifactKeys)
                : ValidateV3Evidence(contract, trackId, startOffsetMs, endOffsetMs,
                    request.FramesProcessed.Value, expectedPrefix, artifactKeys);

            var trajectory = ValidateArtifact(
                contract.TrajectoryArtifact,
                $"{expectedPrefix}/trajectories/{trackId}.msgpack",
                "application/msgpack",
                artifactKeys);

            try
            {
                if (schema == CompletionSchema.V2)
                {
                    aggregateEvidenceBytes = checked(
                        aggregateEvidenceBytes + observations[0].Crop.SizeBytes + trajectory.SizeBytes);
                }
                else
                {
                    aggregateEvidenceBytes = checked(aggregateEvidenceBytes + trajectory.SizeBytes);
                    foreach (var observation in observations)
                    {
                        aggregateCropBytes = checked(aggregateCropBytes + observation.Crop.SizeBytes);
                        var role = (int)observation.Role;
                        admittedCountByRole[role]++;
                        admittedBytesByRole[role] = checked(admittedBytesByRole[role] + observation.Crop.SizeBytes);
                    }
                }
            }
            catch (OverflowException)
            {
                throw Invalid("artifact_evidence_size_invalid");
            }
            if (aggregateEvidenceBytes > WorkerContractRules.MaximumCompletionEvidenceBytes ||
                aggregateCropBytes > WorkerContractRules.MaximumCompletionEvidenceCropBytes)
                throw Invalid("artifact_evidence_size_invalid");

            tracks.Add(new ValidatedTrackResult(
                trackId,
                objectClass,
                startOffsetMs,
                endOffsetMs,
                contract.DetectionCount.Value,
                contract.MeanConfidence!.Value,
                contract.MaxConfidence!.Value,
                observations,
                trajectory,
                contract.ObjectSubclass));
        }

        ValidatedEvidenceAccounting? accounting = null;
        if (schema.IsEvidenceSet())
            accounting = ValidateAccounting(
                request.EvidenceAccounting!, tracks.Count, admittedCountByRole, admittedBytesByRole);

        tracks.Sort((left, right) => StringComparer.Ordinal.Compare(left.TrackId, right.TrackId));

        var runtimeJson = JsonSerializer.Serialize(request.Provenance, _jsonOptions);
        var digest = ComputeDigest(
            schema,
            routeJobId,
            request.AttemptCount.Value,
            request.FramesProcessed.Value,
            request.ProcessingDurationMs.Value,
            request.Provenance,
            accounting,
            tracks,
            subclassVocabulary,
            subclassSource);

        return new ValidatedVisionResult(
            schema,
            request.AttemptCount.Value,
            request.FramesProcessed.Value,
            request.ProcessingDurationMs.Value,
            runtimeJson,
            provenance.DetectorName,
            provenance.DetectorVersion,
            "ByteTrack",
            provenance.TrackerVersion,
            tracks,
            accounting,
            digest,
            subclassVocabulary,
            subclassSource);
    }

    /// <summary>
    /// The body-level vehicle-subclass members (ADR-016). A pre-3.3 body must carry none of
    /// them, on the body or on any Track. A 3.3 body must declare the v1 vocabulary and a
    /// detector-native source naming exactly this body's pipeline profile.
    /// </summary>
    private static (string? Vocabulary, string? Source) ValidateSubclassBody(
        CompletionSchema schema,
        VisionJobCompleteRequest request)
    {
        if (!schema.HasVehicleSubclass())
        {
            if (request.ObjectSubclassVocabulary is not null ||
                request.ObjectSubclassSource is not null ||
                request.Tracks!.Any(track => track?.ObjectSubclass is not null))
                throw Invalid("object_subclass_field_in_pre_v33_body");
            return (null, null);
        }

        if (request.ObjectSubclassVocabulary != WorkerContractRules.VehicleSubclassVocabularyV1)
            throw Invalid("object_subclass_vocabulary_invalid");
        var source = request.ObjectSubclassSource;
        const string prefix = WorkerContractRules.DetectorNativeSubclassSourcePrefix;
        if (source is null || source.Length != prefix.Length + 64 ||
            !source.StartsWith(prefix, StringComparison.Ordinal) ||
            !source[prefix.Length..].All(character => char.IsAsciiDigit(character) || character is >= 'a' and <= 'f'))
            throw Invalid("object_subclass_source_invalid");
        if (!string.Equals(source, prefix + request.Provenance!.PipelineProfileSha256, StringComparison.Ordinal))
            throw Invalid("object_subclass_source_mismatch");
        return (request.ObjectSubclassVocabulary, source);
    }

    /// <summary>Canonical role order (ADR-013 §4); also the rank order.</summary>
    private static IReadOnlyList<ObservationType> RoleOrder => EvidenceRoleOrder.Canonical;

    /// <summary>Wire and storage-key token for each role.</summary>
    public static string RoleToken(ObservationType role) => role switch
    {
        ObservationType.Representative => "representative",
        ObservationType.NearView => "near-view",
        ObservationType.EarlyDiverse => "early-diverse",
        ObservationType.LateDiverse => "late-diverse",
        _ => throw new ArgumentOutOfRangeException(nameof(role)),
    };

    private static ObservationType ParseRole(string? token) => token switch
    {
        "representative" => ObservationType.Representative,
        "near-view" => ObservationType.NearView,
        "early-diverse" => ObservationType.EarlyDiverse,
        "late-diverse" => ObservationType.LateDiverse,
        _ => throw Invalid("observation_role_invalid"),
    };

    private static List<ValidatedObservation> ValidateV2Evidence(
        VisionTrackResultContract contract,
        string trackId,
        long startOffsetMs,
        long endOffsetMs,
        long framesProcessed,
        string expectedPrefix,
        HashSet<string> artifactKeys)
    {
        if (contract.Observations is not null)
            throw Invalid("observations_unexpected");
        if (contract.Representative is null)
            throw Invalid("track_evidence_missing");

        var representative = contract.Representative;
        if (representative.OffsetMs is not { } repOffset || repOffset < startOffsetMs || repOffset > endOffsetMs ||
            representative.SourceFrameNumber is not >= 0 ||
            representative.SourceFrameNumber >= framesProcessed ||
            !Unit(representative.Confidence) || !Unit(representative.QualityScore) ||
            representative.Confidence > contract.MaxConfidence ||
            representative.BoundingBox is null || representative.Thumbnail is null)
            throw Invalid("representative_invalid");

        var box = representative.BoundingBox;
        if (!PersistableNormalizedBox(box.X, box.Y, box.Width, box.Height))
            throw Invalid("bounding_box_invalid");

        var thumbnail = ValidateArtifact(
            representative.Thumbnail,
            $"{expectedPrefix}/thumbnails/{trackId}.jpg",
            "image/jpeg",
            artifactKeys);

        // A v2 Track is one Representative, rank 0; its selection score is its
        // quality score (the same rule the migration applies to historical rows).
        return
        [
            new ValidatedObservation(
                ObservationType.Representative,
                0,
                repOffset,
                representative.SourceFrameNumber!.Value,
                representative.Confidence!.Value,
                representative.QualityScore!.Value,
                representative.QualityScore!.Value,
                box.X!.Value,
                box.Y!.Value,
                box.Width!.Value,
                box.Height!.Value,
                thumbnail),
        ];
    }

    private static List<ValidatedObservation> ValidateV3Evidence(
        VisionTrackResultContract contract,
        string trackId,
        long startOffsetMs,
        long endOffsetMs,
        long framesProcessed,
        string expectedPrefix,
        HashSet<string> artifactKeys)
    {
        if (contract.Representative is not null)
            throw Invalid("representative_unexpected");
        if (contract.Observations is not { Count: >= 1 } items)
            throw Invalid("observations_missing");
        if (items.Count > WorkerContractRules.MaximumTrackObservations)
            throw Invalid("observation_count_invalid");

        var seenRoles = new HashSet<ObservationType>();
        var seenFrames = new HashSet<long>();
        var observations = new List<ValidatedObservation>(items.Count);
        foreach (var item in items)
        {
            if (item is null)
                throw Invalid("observation_missing");
            var role = ParseRole(item.Role);
            if (!seenRoles.Add(role))
                throw Invalid("observation_role_duplicate");
            if (item.Rank is not { } rank)
                throw Invalid("observation_rank_invalid");
            if (item.OffsetMs is not { } offset || offset < startOffsetMs || offset > endOffsetMs ||
                item.SourceFrameNumber is not { } frame || frame < 0 || frame >= framesProcessed ||
                !Unit(item.Confidence) || item.Confidence > contract.MaxConfidence ||
                !Unit(item.QualityScore) || !Unit(item.SelectionScore) ||
                item.BoundingBox is null || item.Crop is null)
                throw Invalid("observation_invalid");
            // One image never satisfies two roles (plan §4.3).
            if (!seenFrames.Add(frame))
                throw Invalid("observation_frame_duplicate");

            var box = item.BoundingBox;
            if (!PersistableNormalizedBox(box.X, box.Y, box.Width, box.Height))
                throw Invalid("bounding_box_invalid");

            var crop = ValidateArtifact(
                item.Crop,
                $"{expectedPrefix}/evidence/{trackId}-{RoleToken(role)}.jpg",
                "image/jpeg",
                artifactKeys);
            var cap = role == ObservationType.Representative
                ? WorkerContractRules.MaximumRepresentativeCropBytes
                : WorkerContractRules.MaximumSupplementalCropBytes;
            if (crop.SizeBytes is <= 0 || crop.SizeBytes > cap)
                throw Invalid("observation_crop_size_invalid");

            observations.Add(new ValidatedObservation(
                role,
                rank,
                offset,
                frame,
                item.Confidence!.Value,
                item.QualityScore!.Value,
                item.SelectionScore!.Value,
                box.X!.Value,
                box.Y!.Value,
                box.Width!.Value,
                box.Height!.Value,
                crop));
        }

        if (!seenRoles.Contains(ObservationType.Representative))
            throw Invalid("observation_representative_missing");

        // Ranks are contiguous 0..n-1 in canonical role order over the roles kept;
        // Representative is therefore rank 0 and supplementals are never rank 0.
        observations.Sort((left, right) =>
            EvidenceRoleOrder.PositionOf(left.Role).CompareTo(EvidenceRoleOrder.PositionOf(right.Role)));
        for (var index = 0; index < observations.Count; index++)
        {
            if (observations[index].Rank != index)
                throw Invalid("observation_rank_invalid");
        }

        return observations;
    }

    private static ValidatedEvidenceAccounting ValidateAccounting(
        VisionEvidenceAccountingContract contract,
        int trackCount,
        int[] admittedCountByRole,
        long[] admittedBytesByRole)
    {
        ValidatedRoleAccounting Role(VisionEvidenceRoleAccountingContract? value, ObservationType role)
        {
            if (value is null ||
                value.Candidates is not >= 0 || value.Admitted is not >= 0 || value.Omitted is not >= 0 ||
                value.CandidateBytes is not >= 0 || value.AdmittedBytes is not >= 0)
                throw Invalid("evidence_accounting_invalid");
            var index = (int)role;
            // The accounting must describe the descriptors actually sent: admitted
            // equals what is present, omitted is the remainder of the candidates.
            if (value.Admitted != admittedCountByRole[index] ||
                value.AdmittedBytes != admittedBytesByRole[index] ||
                value.Admitted > value.Candidates ||
                value.Omitted != value.Candidates - value.Admitted ||
                value.AdmittedBytes > value.CandidateBytes)
                throw Invalid("evidence_accounting_invalid");
            return new ValidatedRoleAccounting(
                value.Candidates.Value,
                value.Admitted.Value,
                value.Omitted.Value,
                value.CandidateBytes.Value,
                value.AdmittedBytes.Value);
        }

        var representative = Role(contract.Representative, ObservationType.Representative);
        // A Representative is mandatory for every accepted Track and never omitted.
        if (representative.Candidates != trackCount || representative.Omitted != 0)
            throw Invalid("evidence_accounting_invalid");

        return new ValidatedEvidenceAccounting(
            representative,
            Role(contract.NearView, ObservationType.NearView),
            Role(contract.EarlyDiverse, ObservationType.EarlyDiverse),
            Role(contract.LateDiverse, ObservationType.LateDiverse));
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
        CompletionSchema schema,
        Guid jobId,
        int attemptCount,
        long framesProcessed,
        long processingDurationMs,
        VisionRuntimeProvenanceContract provenance,
        ValidatedEvidenceAccounting? accounting,
        List<ValidatedTrackResult> tracks,
        string? subclassVocabulary,
        string? subclassSource)
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

        // Domain-separated per version: a stored v2 digest can only ever match a
        // v2 replay, a v3 digest only a v3 replay (plan §7.3) and a v3.2 digest only
        // a v3.2 replay (S2a plan §4.5), and a v3.3 digest only a v3.3 replay (ADR-016).
        Add(schema switch
        {
            CompletionSchema.V2 => "mavi:vision-completion-digest:v2",
            CompletionSchema.V3 => "mavi:vision-completion-digest:v3",
            CompletionSchema.V32 => "mavi:vision-completion-digest:v3.2",
            CompletionSchema.V33 => "mavi:vision-completion-digest:v3.3",
            _ => throw new ArgumentOutOfRangeException(nameof(schema)),
        });
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
        if (schema.HasComponentIdentity())
        {
            Add(provenance.CapabilityId!);
            Add(provenance.ModelPackId!);
            AddNullable(provenance.RuntimePackId);
            Add(provenance.RuntimePackSource!);
            Add(provenance.ComponentBindingSha256!);
        }
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
        if (provenance.DeviceResolutionReason is not null)
        {
            Add("device-resolution-reason");
            Add(provenance.DeviceResolutionReason);
        }
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
            Add(provenance.Gpu.Uuid!);
            Add(provenance.Gpu.PciBusId!);
            Add(provenance.Gpu.ComputeCapability!);
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
        if (schema.HasVehicleSubclass())
        {
            Add(subclassVocabulary!);
            Add(subclassSource!);
        }

        if (schema.IsEvidenceSet())
        {
            foreach (var role in new[] { accounting!.Representative, accounting.NearView, accounting.EarlyDiverse, accounting.LateDiverse })
            {
                AddNumber(role.Candidates);
                AddNumber(role.Admitted);
                AddNumber(role.Omitted);
                AddNumber(role.CandidateBytes);
                AddNumber(role.AdmittedBytes);
            }
        }

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
            if (schema.HasVehicleSubclass())
                AddNullable(track.ObjectSubclass);
            if (schema == CompletionSchema.V2)
            {
                // Byte-for-byte the historical v2 sequence: stored v2 digests must
                // keep matching their replays.
                var representative = track.Representative;
                AddNumber(representative.OffsetMs);
                AddNumber(representative.SourceFrameNumber);
                AddNumber(representative.Confidence);
                AddNumber(representative.QualityScore);
                AddNumber(representative.X);
                AddNumber(representative.Y);
                AddNumber(representative.Width);
                AddNumber(representative.Height);
                Add(representative.Crop.StorageKey);
                Add(representative.Crop.MediaType);
                AddNumber(representative.Crop.SizeBytes);
                Add(representative.Crop.Sha256);
                Add(track.TrajectoryArtifact.StorageKey);
                Add(track.TrajectoryArtifact.MediaType);
                AddNumber(track.TrajectoryArtifact.SizeBytes);
                Add(track.TrajectoryArtifact.Sha256);
                continue;
            }

            Add(track.TrajectoryArtifact.StorageKey);
            Add(track.TrajectoryArtifact.MediaType);
            AddNumber(track.TrajectoryArtifact.SizeBytes);
            Add(track.TrajectoryArtifact.Sha256);
            AddNumber(track.Observations.Count);
            foreach (var observation in track.Observations)
            {
                Add(RoleToken(observation.Role));
                AddNumber(observation.Rank);
                AddNumber(observation.OffsetMs);
                AddNumber(observation.SourceFrameNumber);
                AddNumber(observation.Confidence);
                AddNumber(observation.QualityScore);
                AddNumber(observation.SelectionScore);
                AddNumber(observation.X);
                AddNumber(observation.Y);
                AddNumber(observation.Width);
                AddNumber(observation.Height);
                Add(observation.Crop.StorageKey);
                Add(observation.Crop.MediaType);
                AddNumber(observation.Crop.SizeBytes);
                Add(observation.Crop.Sha256);
            }
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
