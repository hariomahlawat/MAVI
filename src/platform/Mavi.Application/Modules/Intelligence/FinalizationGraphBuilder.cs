using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>One accepted observation and the sealed crop artifact it references.</summary>
public sealed record FinalizationGraphObservation(Artifact CropArtifact, Observation Observation);

/// <summary>One track, its trajectory artifact, its observations and the representative among them.</summary>
public sealed record FinalizationGraphTrack(
    Artifact TrajectoryArtifact,
    Track Track,
    IReadOnlyList<FinalizationGraphObservation> Observations,
    Observation Representative);

/// <summary>
/// The relational graph of a validated result, built in memory and not yet persisted. The
/// representative observation is attached to its track only after the observation row exists,
/// so the pairing is carried here for the publisher to apply after its first save.
/// </summary>
public sealed record FinalizationGraphPlan(IReadOnlyList<FinalizationGraphTrack> Tracks)
{
    public int TrackCount => Tracks.Count;

    public int ObservationCount => Tracks.Sum(track => track.Observations.Count);

    public int ArtifactCount => TrackCount + ObservationCount;
}

/// <summary>
/// Builds the Track/Observation/Artifact graph of a validated result from the accepted keys its
/// objects were sealed under. Shared by the synchronous completion store and the asynchronous
/// finalizer (F3 plan §6.7); pure, deterministic for the same inputs, and blind to persistence.
/// </summary>
public static class FinalizationGraphBuilder
{
    public static FinalizationGraphPlan Build(
        ValidatedVisionResult result,
        IReadOnlyDictionary<string, string> acceptedStorageKeys,
        Guid processingRunId,
        Guid videoAssetId,
        DateTimeOffset recordingStartUtc,
        DateTimeOffset createdAtUtc)
    {
        ArgumentNullException.ThrowIfNull(result);
        ArgumentNullException.ThrowIfNull(acceptedStorageKeys);

        // v2 crops keep the historical Thumbnail type; v3 crops are EvidenceCrop.
        var cropArtifactType = result.Schema == CompletionSchema.V2 ? ArtifactType.Thumbnail : ArtifactType.EvidenceCrop;
        var tracks = new List<FinalizationGraphTrack>(result.Tracks.Count);

        for (var index = 0; index < result.Tracks.Count; index++)
        {
            var accepted = result.Tracks[index];

            var trajectoryArtifact = Artifact.Create(
                ArtifactType.TrackTrajectory,
                acceptedStorageKeys[accepted.TrajectoryArtifact.StorageKey],
                accepted.TrajectoryArtifact.MediaType,
                accepted.TrajectoryArtifact.SizeBytes,
                accepted.TrajectoryArtifact.Sha256,
                createdAtUtc: createdAtUtc);

            var track = Track.Create(
                processingRunId,
                videoAssetId,
                index + 1,
                accepted.ObjectClass,
                accepted.StartOffsetMs,
                accepted.EndOffsetMs,
                recordingStartUtc,
                accepted.DetectionCount,
                accepted.MeanConfidence,
                accepted.MaxConfidence,
                createdAtUtc);
            track.AttachTrajectoryArtifact(trajectoryArtifact.Id);

            var observations = new List<FinalizationGraphObservation>(accepted.Observations.Count);
            Observation? representative = null;
            foreach (var validated in accepted.Observations)
            {
                var cropArtifact = Artifact.Create(
                    cropArtifactType,
                    acceptedStorageKeys[validated.Crop.StorageKey],
                    validated.Crop.MediaType,
                    validated.Crop.SizeBytes,
                    validated.Crop.Sha256,
                    createdAtUtc: createdAtUtc);

                var observation = Observation.Create(
                    track.Id,
                    validated.Role,
                    validated.SourceFrameNumber,
                    validated.OffsetMs,
                    recordingStartUtc,
                    checked((float)validated.X),
                    checked((float)validated.Y),
                    checked((float)validated.Width),
                    checked((float)validated.Height),
                    validated.Confidence,
                    validated.QualityScore,
                    validated.Rank,
                    validated.SelectionScore,
                    createdAtUtc);
                observation.AttachEvidenceArtifact(cropArtifact.Id);
                observations.Add(new FinalizationGraphObservation(cropArtifact, observation));
                if (validated.Role == ObservationType.Representative)
                    representative = observation;
            }

            if (representative is null)
                throw new InvalidOperationException("A validated track always carries its representative observation.");
            tracks.Add(new FinalizationGraphTrack(trajectoryArtifact, track, observations, representative));
        }

        return new FinalizationGraphPlan(tracks);
    }
}
