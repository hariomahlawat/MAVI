using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.SceneAnalytics;

/// <summary>
/// Reads a run's Tracks and their sealed trajectories through the accepted-evidence
/// reader, which is the only sanctioned way into the evidence root.
/// </summary>
public sealed class SceneAnalysisEvidenceReader(MaviDbContext db, IAcceptedEvidenceReader evidence)
    : ISceneAnalysisEvidenceReader
{
    public async Task<IReadOnlyList<SceneAnalysisTrackEvidence>> ListRunTracksAsync(
        Guid processingRunId,
        CancellationToken cancellationToken) =>
        await (from track in db.Tracks.AsNoTracking()
               where track.ProcessingRunId == processingRunId
               join video in db.VideoAssets.AsNoTracking() on track.VideoAssetId equals video.Id
               // A left join: a Track with no trajectory artefact is evidence about that
               // Track, not a reason to leave it out of its own analysis.
               join artifact in db.Artifacts.AsNoTracking() on track.TrajectoryArtifactId equals artifact.Id
                   into trajectories
               from trajectory in trajectories.DefaultIfEmpty()
               // Stable order, so two executions of one unit see the same Tracks in the
               // same sequence and produce byte-identical facts.
               orderby track.LocalTrackNumber, track.Id
               select new SceneAnalysisTrackEvidence(
                   track.Id,
                   track.ObjectClass,
                   video.RecordingStartUtc,
                   trajectory == null ? null : trajectory.StorageKey,
                   trajectory == null ? null : trajectory.Sha256))
            .ToListAsync(cancellationToken);

    public async Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken)
    {
        try
        {
            await using var stream = await evidence.OpenReadAsync(storageKey, cancellationToken);
            using var buffer = new MemoryStream();
            await stream.CopyToAsync(buffer, cancellationToken);
            return buffer.ToArray();
        }
        catch (FileNotFoundException)
        {
            // The artefact is not there. That is a permanent property of this Track's
            // evidence, and the caller records it as such; every other I/O fault is a
            // host problem and is left to propagate so the attempt is retried.
            return null;
        }
        catch (DirectoryNotFoundException)
        {
            return null;
        }
    }
}
