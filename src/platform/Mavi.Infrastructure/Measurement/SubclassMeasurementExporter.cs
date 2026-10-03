using System.Data;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Processing;
using Mavi.Contracts.Api.Processing;
using Mavi.Domain.Cameras;
using Mavi.Domain.Common;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Storage;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Measurement;

/// <summary>
/// The read-only vehicle subclass measurement export (Stage 3, S3.2 plan T1): one
/// completed processing run's Tracks, Evidence Set and subclass facts, bound to the
/// run's attestation and to the verified pipeline profile, as a canonical
/// <c>vehicle-subclass-measurement-export-v1</c> document plus its evidence files.
/// </summary>
/// <remarks>
/// It writes nothing to the database. Every database fact comes from one read-only
/// <c>REPEATABLE READ</c> transaction, the attestation is built from that same
/// snapshot by <see cref="ProcessingRunAttestationFactory"/>, and every evidence file
/// and the source video are re-hashed against their artifact rows. Any gap refuses
/// with a stable <see cref="SubclassMeasurementExportCodes">code</see>; nothing is
/// inferred and no output survives a refusal.
/// </remarks>
public sealed class SubclassMeasurementExporter
{
    public const string SchemaVersion = "vehicle-subclass-measurement-export-v1";
    public const string ExportFileName = "subclass-measurement-export.json";
    public const string EvidenceDirectoryName = "evidence";

    private const string EvidenceMimeType = "image/jpeg";
    private static readonly JsonSerializerOptions WebJson = new(JsonSerializerDefaults.Web)
    {
        NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.Strict,
    };

    private readonly MaviDbContext _db;
    private readonly VisionRuntimeProvenanceParser _provenanceParser;
    private readonly IMediaStore _mediaStore;
    private readonly IAcceptedEvidenceReader _evidenceReader;

    public SubclassMeasurementExporter(
        MaviDbContext db,
        VisionRuntimeProvenanceParser provenanceParser,
        IMediaStore mediaStore,
        IAcceptedEvidenceReader evidenceReader)
    {
        _db = db ?? throw new ArgumentNullException(nameof(db));
        _provenanceParser = provenanceParser ?? throw new ArgumentNullException(nameof(provenanceParser));
        _mediaStore = mediaStore ?? throw new ArgumentNullException(nameof(mediaStore));
        _evidenceReader = evidenceReader ?? throw new ArgumentNullException(nameof(evidenceReader));
    }

    /// <summary>
    /// Test seam: observes the open snapshot transaction after every read, so integration
    /// tests can assert its isolation level and read-only mode. Never set in production.
    /// </summary>
    internal Func<MaviDbContext, CancellationToken, Task>? SnapshotObserver { get; init; }

    /// <summary>Exports the run into a new directory, which exists afterwards only on success.</summary>
    public async Task<SubclassMeasurementExportResult> RunAsync(
        Guid runId,
        string pipelineProfilePath,
        string outputDirectory,
        CancellationToken cancellationToken)
    {
        var target = ValidateOutputDirectory(outputDirectory);
        var export = await ExportAsync(runId, pipelineProfilePath, cancellationToken);
        // Everything that can fail happens before the directory is moved into place.
        var trackCount = JsonNode.Parse(export.Json)!["tracks"]!.AsArray().Count;
        await WriteAsync(export, target, cancellationToken);
        return new SubclassMeasurementExportResult(target, export.ExportSha256, trackCount, export.Evidence.Count);
    }

    /// <summary>Builds and verifies the export without writing anything.</summary>
    public async Task<SubclassMeasurementExport> ExportAsync(
        Guid runId,
        string pipelineProfilePath,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(pipelineProfilePath);
        var snapshot = await ReadSnapshotAsync(runId, cancellationToken);
        var profile = VerifyPipelineProfile(pipelineProfilePath, snapshot.Attestation.PipelineProfileSha256);
        ValidateSubclassStates(snapshot.Tracks, SubclassSourceFor(snapshot.Attestation.PipelineProfileSha256));

        var evidence = await VerifyEvidenceAsync(snapshot, cancellationToken);
        await VerifySourceAsync(snapshot.SourceArtifact, cancellationToken);

        var json = CanonicalJson.Serialize(BuildDocument(snapshot, profile));
        return new SubclassMeasurementExport(json, Sha256Hex(json), evidence);
    }

    /// <summary>Writes a verified export into a new directory, re-verifying every evidence file as it is copied.</summary>
    public async Task WriteAsync(
        SubclassMeasurementExport export,
        string outputDirectory,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(export);
        var target = ValidateOutputDirectory(outputDirectory);
        var parent = Path.GetDirectoryName(target)!;
        var staging = Path.Combine(parent, $".{Path.GetFileName(target)}.partial-{Guid.NewGuid():N}");
        Directory.CreateDirectory(staging);
        try
        {
            var evidenceDirectory = Path.Combine(staging, EvidenceDirectoryName);
            Directory.CreateDirectory(evidenceDirectory);
            foreach (var item in export.Evidence)
                await CopyEvidenceAsync(item, Path.Combine(evidenceDirectory, item.Sha256 + ".jpg"), cancellationToken);

            await File.WriteAllBytesAsync(Path.Combine(staging, ExportFileName), export.Json, cancellationToken);
            try
            {
                Directory.Move(staging, target);
            }
            catch (IOException exception) when (Directory.Exists(target) || File.Exists(target))
            {
                throw new SubclassMeasurementExportException(
                    SubclassMeasurementExportCodes.OutputExists,
                    "The output directory already exists; exports are written once.",
                    exception);
            }
        }
        catch
        {
            TryDeleteDirectory(staging);
            throw;
        }
    }

    // Pipeline profile

    internal sealed record VerifiedPipelineProfile(string Sha256, string EvidenceSelectorVersion, string EvidenceScorerVersion);

    /// <summary>
    /// The supplied profile file, accepted only when its bytes are the attested profile.
    /// The path is always given; nothing is inferred from a hash.
    /// </summary>
    internal static VerifiedPipelineProfile VerifyPipelineProfile(string path, string attestedSha256)
    {
        byte[] bytes;
        try
        {
            bytes = File.ReadAllBytes(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or ArgumentException or NotSupportedException)
        {
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.PipelineProfileInvalid,
                "The pipeline profile file cannot be read.",
                exception);
        }

        var sha256 = Sha256Hex(bytes);
        if (!string.Equals(sha256, attestedSha256, StringComparison.Ordinal))
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.PipelineProfileMismatch,
                "The pipeline profile file is not the profile the run attests.");

        try
        {
            using var document = JsonDocument.Parse(bytes);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object ||
                !root.TryGetProperty("evidence", out var evidence) ||
                evidence.ValueKind != JsonValueKind.Object)
                throw ProfileInvalid("The pipeline profile has no evidence configuration.");
            var selector = RequiredText(evidence, "selectorVersion");
            var scorer = RequiredText(evidence, "scorerVersion");

            if (!root.TryGetProperty("vehicleSubclass", out var subclass) || subclass.ValueKind == JsonValueKind.Null)
                throw new SubclassMeasurementExportException(
                    SubclassMeasurementExportCodes.ProfileNotStage3,
                    "The pipeline profile has no vehicle-subclass configuration.");
            if (subclass.ValueKind != JsonValueKind.Object ||
                !subclass.TryGetProperty("vocabularyId", out var vocabulary) ||
                vocabulary.ValueKind != JsonValueKind.String ||
                !string.Equals(vocabulary.GetString(), VehicleSubclass.VocabularyV1, StringComparison.Ordinal))
                throw ProfileInvalid("The pipeline profile's vehicle-subclass configuration is invalid.");

            return new VerifiedPipelineProfile(sha256, selector, scorer);
        }
        catch (JsonException exception)
        {
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.PipelineProfileInvalid,
                "The pipeline profile is not valid JSON.",
                exception);
        }
    }

    private static string RequiredText(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String)
            throw ProfileInvalid($"The pipeline profile has no evidence {name}.");
        var text = value.GetString()!;
        if (text.Length == 0 || !string.Equals(text, text.Trim(), StringComparison.Ordinal))
            throw ProfileInvalid($"The pipeline profile's evidence {name} is invalid.");
        return text;
    }

    private static SubclassMeasurementExportException ProfileInvalid(string message) =>
        new(SubclassMeasurementExportCodes.PipelineProfileInvalid, message);

    // Snapshot

    private sealed record Snapshot(
        ProcessingRun Run,
        ProcessingRunAttestationResponse Attestation,
        VideoAsset Video,
        Camera Camera,
        Artifact SourceArtifact,
        IReadOnlyList<Track> Tracks,
        IReadOnlyDictionary<Guid, IReadOnlyList<Observation>> ObservationsByTrack,
        IReadOnlyDictionary<Guid, Artifact> Artifacts);

    private async Task<Snapshot> ReadSnapshotAsync(Guid runId, CancellationToken cancellationToken)
    {
        await using var transaction = await _db.Database.BeginTransactionAsync(IsolationLevel.RepeatableRead, cancellationToken);
        // Before any read, so the whole snapshot is one read-only transaction.
        await _db.Database.ExecuteSqlRawAsync("SET TRANSACTION READ ONLY", cancellationToken);

        var run = await _db.ProcessingRuns.AsNoTracking().SingleOrDefaultAsync(x => x.Id == runId, cancellationToken)
            ?? throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.RunNotFound,
                "The processing run does not exist.");
        if (run.Status != ProcessingRunStatus.Completed || run.CompletedAtUtc is null)
            throw NotTerminal();
        var jobStatuses = await _db.VisionJobs.AsNoTracking()
            .Where(x => x.ProcessingRunId == runId)
            .Select(x => x.Status)
            .ToListAsync(cancellationToken);
        // Finalisation is done only when the run's job has completed too.
        if (jobStatuses.Count == 0 || jobStatuses.Any(status => status != VisionJobStatus.Completed))
            throw NotTerminal();

        var attestation = BuildAttestation(run);
        if (attestation.ProcessingRunId != run.Id || attestation.VideoAssetId != run.VideoAssetId)
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.AttestationIntegrity,
                "The attestation does not describe this run.");

        var video = await _db.VideoAssets.AsNoTracking().SingleOrDefaultAsync(x => x.Id == run.VideoAssetId, cancellationToken)
            ?? throw ProvenanceIncomplete("The run's video asset is missing.");
        // Defensive: the run names exactly one video, so with the foreign keys in place this
        // holds by construction; a Track on another video is export_track_run_mismatch.
        if (video.Id != attestation.VideoAssetId)
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.VideoMismatch,
                "The video asset is not the run's.");
        var camera = await _db.Cameras.AsNoTracking().SingleOrDefaultAsync(x => x.Id == video.CameraId, cancellationToken)
            ?? throw ProvenanceIncomplete("The video's camera is missing.");

        var tracks = await _db.Tracks.AsNoTracking()
            .Where(x => x.ProcessingRunId == runId)
            .OrderBy(x => x.LocalTrackNumber)
            .ToListAsync(cancellationToken);
        // The run records how many Tracks it published; a Track moved to or from it shows here.
        if (tracks.Count != run.TracksCreated || tracks.Any(x => x.VideoAssetId != run.VideoAssetId))
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.TrackRunMismatch,
                "The run's Tracks do not match the run.");

        var trackIds = tracks.Select(x => x.Id).ToList();
        var observations = await _db.Observations.AsNoTracking()
            .Where(x => trackIds.Contains(x.TrackId))
            .ToListAsync(cancellationToken);
        var observationsByTrack = tracks.ToDictionary(
            track => track.Id,
            track => (IReadOnlyList<Observation>)observations
                .Where(x => x.TrackId == track.Id)
                .OrderBy(x => x.EvidenceRank)
                .ThenBy(x => EvidenceRoleOrder.PositionOf(x.ObservationType))
                .ThenBy(x => x.Id)
                .ToList());
        foreach (var track in tracks)
        {
            if (track.RepresentativeObservationId is { } representative &&
                observationsByTrack[track.Id].All(x => x.Id != representative))
                throw new SubclassMeasurementExportException(
                    SubclassMeasurementExportCodes.ObservationOrphan,
                    "A Track's Representative observation is not one of its own observations.");
        }

        if (observations.Any(x => x.ThumbnailArtifactId is null))
            throw ProvenanceIncomplete("An exported observation has no evidence artifact.");
        var artifactIds = observations.Select(x => x.ThumbnailArtifactId!.Value)
            .Concat(tracks.Where(x => x.TrajectoryArtifactId is not null).Select(x => x.TrajectoryArtifactId!.Value))
            .Append(video.SourceArtifactId)
            .Distinct()
            .ToList();
        var artifacts = await _db.Artifacts.AsNoTracking()
            .Where(x => artifactIds.Contains(x.Id))
            .ToDictionaryAsync(x => x.Id, cancellationToken);
        if (artifactIds.Any(id => !artifacts.ContainsKey(id)))
            throw ProvenanceIncomplete("An artifact the run names is missing.");
        var source = artifacts[video.SourceArtifactId];
        if (source.ArtifactType != ArtifactType.SourceVideo)
            throw ProvenanceIncomplete("The video's source artifact is not a source video.");

        if (SnapshotObserver is not null)
            await SnapshotObserver(_db, cancellationToken);
        await transaction.RollbackAsync(cancellationToken);
        return new Snapshot(run, attestation, video, camera, source, tracks, observationsByTrack, artifacts);
    }

    private ProcessingRunAttestationResponse BuildAttestation(ProcessingRun run)
    {
        // The same source the attestation endpoint reads, taken from this snapshot.
        var source = new ProcessingRunAttestationSource(
            run.Id,
            run.VideoAssetId,
            run.CompletedAtUtc!.Value,
            run.PipelineVersion,
            run.DetectorName,
            run.DetectorVersion,
            run.TrackerName,
            run.TrackerVersion,
            run.FramesProcessed,
            run.TracksCreated,
            run.ProcessingDurationMs ?? 0,
            run.RuntimeProvenanceJson);
        try
        {
            var parsed = _provenanceParser.ParsePersisted(source.RuntimeProvenanceJson ?? string.Empty);
            return ProcessingRunAttestationFactory.Build(source, parsed);
        }
        catch (VisionResultValidationException exception)
        {
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.AttestationIntegrity,
                "The completed run's provenance is invalid.",
                exception);
        }
    }

    // Subclass state

    private static string SubclassSourceFor(string pipelineProfileSha256) =>
        VehicleSubclass.DetectorNativeSourcePrefix + pipelineProfileSha256;

    /// <summary>
    /// Every Track must be in a valid domain state for a Stage-3 run: a Person carries no
    /// subclass data; a Vehicle carries the v1 vocabulary and this run's detector-native
    /// source, with a v1 value or none (the vote abstained).
    /// </summary>
    private static void ValidateSubclassStates(IReadOnlyList<Track> tracks, string expectedSource)
    {
        foreach (var track in tracks)
        {
            var valid = track.ObjectClass == ObjectClass.Vehicle
                ? string.Equals(track.ObjectSubclassVocabulary, VehicleSubclass.VocabularyV1, StringComparison.Ordinal) &&
                  string.Equals(track.ObjectSubclassSource, expectedSource, StringComparison.Ordinal) &&
                  (track.ObjectSubclass is null || VehicleSubclass.ValuesV1.Contains(track.ObjectSubclass))
                : track.ObjectSubclass is null && track.ObjectSubclassVocabulary is null && track.ObjectSubclassSource is null;
            if (!valid)
                throw new SubclassMeasurementExportException(
                    SubclassMeasurementExportCodes.SubclassStateInvalid,
                    $"Track {track.LocalTrackNumber} has an invalid subclass state for this run.");
        }
    }

    // Bytes

    private async Task<IReadOnlyList<SubclassMeasurementExportEvidence>> VerifyEvidenceAsync(
        Snapshot snapshot,
        CancellationToken cancellationToken)
    {
        var bySha = new SortedDictionary<string, SubclassMeasurementExportEvidence>(StringComparer.Ordinal);
        var artifactIds = snapshot.ObservationsByTrack.Values
            .SelectMany(x => x)
            .Select(x => x.ThumbnailArtifactId!.Value)
            .Distinct()
            .OrderBy(x => x);
        foreach (var artifactId in artifactIds)
        {
            var artifact = snapshot.Artifacts[artifactId];
            if (artifact.ArtifactType is not (ArtifactType.EvidenceCrop or ArtifactType.Thumbnail) ||
                !string.Equals(artifact.MimeType, EvidenceMimeType, StringComparison.Ordinal) ||
                !CanonicalSha256.IsCanonical(artifact.Sha256))
                throw ProvenanceIncomplete("An evidence artifact is not an accepted evidence image.");

            var (sha256, size) = await HashAsync(
                () => _evidenceReader.OpenReadAsync(artifact.StorageKey, cancellationToken),
                "An evidence file is missing.",
                cancellationToken);
            if (!string.Equals(sha256, artifact.Sha256, StringComparison.Ordinal) || size != artifact.SizeBytes)
                throw new SubclassMeasurementExportException(
                    SubclassMeasurementExportCodes.EvidenceChanged,
                    "An evidence file no longer matches its artifact.");

            if (bySha.TryGetValue(sha256, out var existing) && existing.SizeBytes != size)
                throw new SubclassMeasurementExportException(
                    SubclassMeasurementExportCodes.EvidenceChanged,
                    "Two evidence artifacts disagree about one digest.");
            bySha.TryAdd(sha256, new SubclassMeasurementExportEvidence(sha256, size, artifact.StorageKey));
        }

        return bySha.Values.ToList();
    }

    private async Task VerifySourceAsync(Artifact source, CancellationToken cancellationToken)
    {
        if (!CanonicalSha256.IsCanonical(source.Sha256))
            throw ProvenanceIncomplete("The source video artifact has no canonical digest.");
        var (sha256, size) = await HashAsync(
            () => _mediaStore.OpenReadAsync(source.StorageKey, cancellationToken),
            "The source video file is missing.",
            cancellationToken);
        if (!string.Equals(sha256, source.Sha256, StringComparison.Ordinal) || size != source.SizeBytes)
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.SourceChanged,
                "The source video no longer matches its artifact.");
    }

    private async Task CopyEvidenceAsync(
        SubclassMeasurementExportEvidence item,
        string destination,
        CancellationToken cancellationToken)
    {
        await using var input = await OpenAsync(
            () => _evidenceReader.OpenReadAsync(item.StorageKey, cancellationToken),
            "An evidence file is missing.");
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        long size = 0;
        var buffer = new byte[81_920];
        await using (var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        {
            int read;
            while ((read = await input.ReadAsync(buffer, cancellationToken)) > 0)
            {
                hash.AppendData(buffer, 0, read);
                size += read;
                await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
            }
        }

        if (!string.Equals(CanonicalSha256.ToHex(hash.GetHashAndReset()), item.Sha256, StringComparison.Ordinal) ||
            size != item.SizeBytes)
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.EvidenceChanged,
                "An evidence file changed while it was being exported.");
    }

    private static async Task<(string Sha256, long Size)> HashAsync(
        Func<Task<Stream>> open,
        string missingMessage,
        CancellationToken cancellationToken)
    {
        await using var stream = await OpenAsync(open, missingMessage);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        long size = 0;
        var buffer = new byte[81_920];
        int read;
        while ((read = await stream.ReadAsync(buffer, cancellationToken)) > 0)
        {
            hash.AppendData(buffer, 0, read);
            size += read;
        }

        return (CanonicalSha256.ToHex(hash.GetHashAndReset()), size);
    }

    private static async Task<Stream> OpenAsync(Func<Task<Stream>> open, string missingMessage)
    {
        try
        {
            return await open();
        }
        catch (Exception exception) when (exception is FileNotFoundException or DirectoryNotFoundException
                                              or UnsafeMediaPathException or ArgumentException)
        {
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.ProvenanceIncomplete,
                missingMessage,
                exception);
        }
    }

    // Document

    private static JsonObject BuildDocument(Snapshot snapshot, VerifiedPipelineProfile profile)
    {
        var tracks = new JsonArray();
        foreach (var track in snapshot.Tracks)
            tracks.Add(BuildTrack(track, snapshot));

        return new JsonObject
        {
            ["schemaVersion"] = SchemaVersion,
            ["processingRun"] = new JsonObject
            {
                ["processingRunId"] = snapshot.Run.Id.ToString("D"),
                ["videoAssetId"] = snapshot.Run.VideoAssetId.ToString("D"),
                ["status"] = nameof(ProcessingRunStatus.Completed),
                ["completedAtUtc"] = JsonSerializer.SerializeToNode(snapshot.Run.CompletedAtUtc!.Value, WebJson),
                ["attestation"] = JsonSerializer.SerializeToNode(snapshot.Attestation, WebJson),
            },
            ["video"] = new JsonObject
            {
                ["videoAssetId"] = snapshot.Video.Id.ToString("D"),
                ["cameraCode"] = snapshot.Camera.Code,
                ["sourceSha256"] = snapshot.SourceArtifact.Sha256,
                ["sourceSizeBytes"] = snapshot.SourceArtifact.SizeBytes,
                ["durationMs"] = snapshot.Video.DurationMs,
                ["width"] = snapshot.Video.Width,
                ["height"] = snapshot.Video.Height,
                ["frameRateNumerator"] = snapshot.Video.FrameRateNumerator,
                ["frameRateDenominator"] = snapshot.Video.FrameRateDenominator,
            },
            ["profile"] = new JsonObject
            {
                ["pipelineProfileSha256"] = snapshot.Attestation.PipelineProfileSha256,
                ["evidenceSelectorVersion"] = profile.EvidenceSelectorVersion,
                ["evidenceScorerVersion"] = profile.EvidenceScorerVersion,
            },
            ["tracks"] = tracks,
        };
    }

    private static JsonObject BuildTrack(Track track, Snapshot snapshot)
    {
        var trackObservations = snapshot.ObservationsByTrack[track.Id];
        var observations = new JsonArray();
        foreach (var observation in trackObservations)
        {
            var artifact = snapshot.Artifacts[observation.ThumbnailArtifactId!.Value];
            observations.Add(new JsonObject
            {
                ["evidenceRole"] = observation.ObservationType.ToString(),
                ["evidenceRank"] = observation.EvidenceRank,
                ["sourceFrameNumber"] = observation.SourceFrameNumber,
                ["videoOffsetMs"] = observation.VideoOffsetMs,
                ["boundingBox"] = BoundingBox(observation),
                ["qualityScore"] = observation.QualityScore,
                ["evidenceSha256"] = artifact.Sha256,
                ["evidenceSizeBytes"] = artifact.SizeBytes,
                ["evidencePath"] = $"{EvidenceDirectoryName}/{artifact.Sha256}.jpg",
            });
        }

        var representative = track.RepresentativeObservationId is { } representativeId
            ? trackObservations.Single(x => x.Id == representativeId)
            : null;
        return new JsonObject
        {
            ["id"] = track.Id.ToString("D"),
            ["localTrackNumber"] = track.LocalTrackNumber,
            ["objectClass"] = track.ObjectClass.ToString(),
            ["startOffsetMs"] = track.StartOffsetMs,
            ["endOffsetMs"] = track.EndOffsetMs,
            ["detectionCount"] = track.DetectionCount,
            ["meanConfidence"] = track.MeanConfidence,
            ["maxConfidence"] = track.MaxConfidence,
            ["representative"] = representative is null
                ? null
                : new JsonObject
                {
                    ["videoOffsetMs"] = representative.VideoOffsetMs,
                    ["boundingBox"] = BoundingBox(representative),
                },
            ["objectSubclass"] = track.ObjectSubclass,
            ["objectSubclassVocabulary"] = track.ObjectSubclassVocabulary,
            ["objectSubclassSource"] = track.ObjectSubclassSource,
            ["observations"] = observations,
            ["trajectorySha256"] = track.TrajectoryArtifactId is { } trajectoryId
                ? snapshot.Artifacts[trajectoryId].Sha256
                : null,
        };
    }

    // Stored single-precision values, written in their shortest round-trip form.
    private static JsonObject BoundingBox(Observation observation) => new()
    {
        ["x"] = observation.BoundingBoxX,
        ["y"] = observation.BoundingBoxY,
        ["width"] = observation.BoundingBoxWidth,
        ["height"] = observation.BoundingBoxHeight,
    };

    // Helpers

    private static string ValidateOutputDirectory(string outputDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(outputDirectory);
        string target;
        try
        {
            target = Path.TrimEndingDirectorySeparator(Path.GetFullPath(outputDirectory));
        }
        catch (Exception exception) when (exception is ArgumentException or NotSupportedException or PathTooLongException)
        {
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.OutputInvalid,
                "The output directory path is invalid.",
                exception);
        }

        if (Directory.Exists(target) || File.Exists(target))
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.OutputExists,
                "The output directory already exists; exports are written once.");
        var parent = Path.GetDirectoryName(target);
        if (string.IsNullOrEmpty(parent) || !Directory.Exists(parent))
            throw new SubclassMeasurementExportException(
                SubclassMeasurementExportCodes.OutputInvalid,
                "The output directory's parent does not exist.");
        return target;
    }

    private static void TryDeleteDirectory(string path)
    {
        try
        {
            if (Directory.Exists(path))
                Directory.Delete(path, recursive: true);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private static string Sha256Hex(byte[] bytes) => CanonicalSha256.ToHex(SHA256.HashData(bytes));

    private static SubclassMeasurementExportException NotTerminal() =>
        new(SubclassMeasurementExportCodes.RunNotTerminal, "The processing run and its job have not both completed.");

    private static SubclassMeasurementExportException ProvenanceIncomplete(string message) =>
        new(SubclassMeasurementExportCodes.ProvenanceIncomplete, message);
}
