using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence;

public static class ProcessingVisibilityBarrier
{
    // One repository-wide advisory-lock namespace for the transition from
    // uncommitted processing completion to search-visible completed intelligence.
    // Completion transactions hold the shared form; first-page Track search holds
    // the exclusive form while it samples its snapshot and executes the query.
    private const string CompletionSharedSql =
        "SELECT pg_advisory_xact_lock_shared(1296127561, 1412505908)";
    private const string SearchExclusiveSql =
        "SELECT pg_advisory_xact_lock(1296127561, 1412505908)";

    public static Task AcquireCompletionSharedAsync(
        MaviDbContext db,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(db);
        if (db.Database.CurrentTransaction is null)
            throw new InvalidOperationException(
                "Processing completion visibility lock requires an active database transaction.");

        return db.Database.ExecuteSqlRawAsync(
            CompletionSharedSql,
            cancellationToken);
    }

    public static Task AcquireSearchExclusiveAsync(
        MaviDbContext db,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(db);
        if (db.Database.CurrentTransaction is null)
            throw new InvalidOperationException(
                "Track search visibility lock requires an active database transaction.");

        return db.Database.ExecuteSqlRawAsync(
            SearchExclusiveSql,
            cancellationToken);
    }
}
