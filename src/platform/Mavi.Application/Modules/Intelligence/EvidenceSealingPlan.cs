using Mavi.Contracts.Worker;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>One staged object to seal into the accepted evidence root, and the key it is sealed under.</summary>
/// <param name="Category"><c>crops</c>, <c>thumbnails</c> or <c>trajectories</c>: the accepted-root directory.</param>
/// <param name="TrackIndex">The zero-based validated track the object belongs to (safe to log; never a path).</param>
public sealed record EvidenceSealingUnit(
    string SourceStorageKey,
    string AcceptedStorageKey,
    long ExpectedSizeBytes,
    string ExpectedSha256,
    string Category,
    int TrackIndex);

/// <summary>
/// The accepted-evidence key rule and sealing order shared by the synchronous completion store
/// and the asynchronous finalizer (ADR-006 §3–§4; F3 plan §6.5). Pure: it plans, it never seals.
/// </summary>
/// <remarks>
/// Keys are content-addressed per job and attempt
/// (<c>evidence/{job}/attempt-NNNN/{category}/{stem}-{sha256}.{ext}</c>), which is what makes a
/// retry adopt what an earlier claimant already sealed instead of creating a second object.
/// Order is crops in rank order then the trajectory, track by track: the historical v2 order,
/// kept for both schema versions so the two paths seal identically.
/// </remarks>
public static class EvidenceSealingPlan
{
    public const string CropsCategory = "crops";
    public const string ThumbnailsCategory = "thumbnails";
    public const string TrajectoriesCategory = "trajectories";

    public static string AcceptedEvidenceKey(
        Guid jobId,
        int attemptCount,
        string category,
        string trackId,
        string sha256,
        string extension) =>
        $"evidence/{jobId:D}/attempt-{attemptCount:0000}/{category}/{trackId}-{sha256}.{extension}";

    /// <summary>
    /// Defence in depth behind the validator: a v3 result whose admitted crop bytes exceed the
    /// run quota is refused before anything is sealed, even if validation were bypassed.
    /// </summary>
    public static bool ExceedsAdmittedCropQuota(ValidatedVisionResult result)
    {
        ArgumentNullException.ThrowIfNull(result);
        if (result.Schema != CompletionSchema.V3)
            return false;
        long admittedCropBytes = 0;
        foreach (var track in result.Tracks)
            foreach (var observation in track.Observations)
                admittedCropBytes += observation.Crop.SizeBytes;
        return admittedCropBytes > WorkerContractRules.MaximumCompletionEvidenceCropBytes;
    }

    /// <summary>The ordered sealing units of a validated result.</summary>
    public static IReadOnlyList<EvidenceSealingUnit> Build(Guid jobId, ValidatedVisionResult result)
    {
        ArgumentNullException.ThrowIfNull(result);
        var units = new List<EvidenceSealingUnit>();
        for (var index = 0; index < result.Tracks.Count; index++)
        {
            var track = result.Tracks[index];
            foreach (var observation in track.Observations)
            {
                var (category, stem) = result.Schema == CompletionSchema.V2
                    ? (ThumbnailsCategory, track.TrackId)
                    : (CropsCategory, $"{track.TrackId}-{VisionResultValidator.RoleToken(observation.Role)}");
                units.Add(new EvidenceSealingUnit(
                    observation.Crop.StorageKey,
                    AcceptedEvidenceKey(jobId, result.AttemptCount, category, stem, observation.Crop.Sha256, "jpg"),
                    observation.Crop.SizeBytes,
                    observation.Crop.Sha256,
                    category,
                    index));
            }

            units.Add(new EvidenceSealingUnit(
                track.TrajectoryArtifact.StorageKey,
                AcceptedEvidenceKey(jobId, result.AttemptCount, TrajectoriesCategory, track.TrackId, track.TrajectoryArtifact.Sha256, "msgpack"),
                track.TrajectoryArtifact.SizeBytes,
                track.TrajectoryArtifact.Sha256,
                TrajectoriesCategory,
                index));
        }

        return units;
    }
}
