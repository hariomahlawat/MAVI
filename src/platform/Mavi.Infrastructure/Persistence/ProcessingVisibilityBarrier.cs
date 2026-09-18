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
    public const string SequenceName = "processing_visibility_sequence";

    private const string CompletionExclusiveSql =
        "SELECT pg_advisory_xact_lock(1296127561, 1412505908)";
    private const string SearchSharedSql =
        "SELECT pg_advisory_xact_lock_shared(1296127561, 1412505908)";
    private const string NextSequenceSql =
        "SELECT nextval('processing_visibility_sequence')";

    public static Task AcquireCompletionExclusiveAsync(
        MaviDbContext db,
        CancellationToken cancellationToken)
    {
        RequireTransaction(db, "Processing completion visibility lock");
        return db.Database.ExecuteSqlRawAsync(
            CompletionExclusiveSql,
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
