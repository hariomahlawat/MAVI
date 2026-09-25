using Mavi.Application.Modules.Intelligence;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// Writes a built graph into the current transaction: the one relational publication routine,
/// used by the synchronous completion store and the asynchronous finalizer alike. Nothing here
/// commits; the caller owns the transaction and the barrier ordering around it.
/// </summary>
internal static class FinalizationGraphPersistence
{
    /// <summary>
    /// Adds every artifact, track and observation, saves once so the observation ids exist,
    /// then attaches each track's representative. The second save is the caller's, so it lands
    /// in the same save as the completion facts.
    /// </summary>
    public static async Task AddAsync(MaviDbContext db, FinalizationGraphPlan plan, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(db);
        ArgumentNullException.ThrowIfNull(plan);

        foreach (var track in plan.Tracks)
        {
            db.Artifacts.Add(track.TrajectoryArtifact);
            db.Tracks.Add(track.Track);
            foreach (var observation in track.Observations)
            {
                db.Artifacts.Add(observation.CropArtifact);
                db.Observations.Add(observation.Observation);
            }
        }

        await db.SaveChangesAsync(cancellationToken);

        foreach (var track in plan.Tracks)
            track.Track.AttachRepresentativeObservation(track.Representative.Id);
    }
}
