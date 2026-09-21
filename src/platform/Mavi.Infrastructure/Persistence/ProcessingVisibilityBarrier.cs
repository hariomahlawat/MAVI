using System.Data;
using System.Globalization;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;

namespace Mavi.Infrastructure.Persistence;

public static class ProcessingVisibilityBarrier
{
    // The visibility sequence is database-owned and monotonic. Advisory locking
    // establishes the commit boundary around sequence allocation:
    // - concurrent first-page searches take the shared lock and may run together;
    // - completion takes the exclusive lock before allocating its sequence and
    //   holds it through commit.
    //
    // A first-page snapshot sequence is therefore strictly lower than every
    // completion that can commit after that search transaction releases its lock,
    // without depending on host clocks.
    //
    // The exclusive side is not "completion" but publication: every commit that can
    // change what a search snapshot means takes it. There are two. A processing run
    // completing publishes Tracks and analytic facts. A scene activation publishes a
    // new active revision, which is what an analytic search without an explicit
    // revision pins its identity to and what coverage classifies missing units
    // against. A search that resolved its scope outside this lock could pin one
    // revision and count against a snapshot taken in a world where another is active,
    // so both publication paths must hold the exclusive lock through commit and every
    // first page must hold the shared lock before it reads any scope.
    public const string SequenceName = "processing_visibility_sequence";

    private const string PublicationExclusiveSql =
        "SELECT pg_advisory_xact_lock(1296127561, 1412505908)";
    private const string SearchSharedSql =
        "SELECT pg_advisory_xact_lock_shared(1296127561, 1412505908)";
    private const string NextSequenceSql =
        "SELECT nextval('processing_visibility_sequence')";

    /// <summary>
    /// Taken by a processing run publishing its Tracks and facts, and held through commit.
    /// </summary>
    public static Task AcquireCompletionExclusiveAsync(
        MaviDbContext db,
        CancellationToken cancellationToken)
    {
        RequireTransaction(db, "Processing completion visibility lock");
        return db.Database.ExecuteSqlRawAsync(
            PublicationExclusiveSql,
            cancellationToken);
    }

    /// <summary>
    /// Taken by a scene activation publishing a new active revision, and held through
    /// commit. This is the same lock the completion path takes, because it is the same
    /// question: whether a first-page search sees this change wholly or not at all.
    /// </summary>
    public static Task AcquireSceneActivationExclusiveAsync(
        MaviDbContext db,
        CancellationToken cancellationToken)
    {
        RequireTransaction(db, "Scene activation visibility lock");
        return db.Database.ExecuteSqlRawAsync(
            PublicationExclusiveSql,
            cancellationToken);
    }

    public static Task AcquireSearchSharedAsync(
        MaviDbContext db,
        CancellationToken cancellationToken)
    {
        RequireTransaction(db, "Track search visibility lock");
        return db.Database.ExecuteSqlRawAsync(
            SearchSharedSql,
            cancellationToken);
    }

    public static async Task<long> AllocateSequenceAsync(
        MaviDbContext db,
        CancellationToken cancellationToken)
    {
        RequireTransaction(db, "Processing visibility sequence allocation");

        var connection = db.Database.GetDbConnection();
        if (connection.State != ConnectionState.Open)
            await connection.OpenAsync(cancellationToken);

        await using var command = connection.CreateCommand();
        command.CommandText = NextSequenceSql;
        command.Transaction = db.Database.CurrentTransaction!.GetDbTransaction();

        var scalar = await command.ExecuteScalarAsync(cancellationToken);
        if (scalar is null or DBNull)
            throw new InvalidOperationException(
                "Processing visibility sequence allocation returned no value.");

        return Convert.ToInt64(scalar, CultureInfo.InvariantCulture);
    }

    private static void RequireTransaction(MaviDbContext db, string operation)
    {
        ArgumentNullException.ThrowIfNull(db);
        if (db.Database.CurrentTransaction is null)
            throw new InvalidOperationException(
                $"{operation} requires an active database transaction.");
    }
}
