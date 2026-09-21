using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.Intelligence;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// Properties of the final fact commit that only show up against a real server: how long
/// the completion barrier is held, and what happens when the database refuses the write.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneAnalyticsCommitBoundaryTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    /// <summary>
    /// The exclusive completion barrier blocks every first-page search and every run
    /// completion for as long as it is held, so the bulk fact insert must happen
    /// <i>before</i> it is taken — which is what the existing run-completion path does.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Proven by holding the barrier from another session and then asking
    /// <c>pg_locks</c> what the blocked completion has already touched. Inserting a fact
    /// checks its foreign key to <c>tracks</c>, which takes a <c>RowShareLock</c> on that
    /// table; nothing else in the transaction goes near <c>tracks</c>. So the lock is
    /// present only if the inserts ran before the barrier.
    /// </para>
    /// <para>
    /// Two more obvious probes were tried first and both passed against the defect, which
    /// is why the indirection is worth it. A <c>RowExclusiveLock</c> on the fact tables is
    /// taken by the idempotent delete that precedes the insert, and a conflicting insert
    /// on a unique fact key blocks on the foreign key to the unit row, which the
    /// completion already holds <c>FOR UPDATE</c>. Neither says anything about the insert.
    /// </para>
    /// </remarks>
    [Fact]
    public async Task TheFactInsertHappensBeforeTheCompletionBarrierIsTaken()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(Policy, default);
        var facts = world.Facts(claim!.AnalysisId);

        // Another session holds the barrier, so the completion cannot get past it.
        await using var holder = new NpgsqlConnection(fixture.ConnectionString);
        await holder.OpenAsync();
        await using var holding = await holder.BeginTransactionAsync();
        await using (var acquire = new NpgsqlCommand(
            "SELECT pg_advisory_xact_lock(1296127561, 1412505908)", holder, holding))
        {
            await acquire.ExecuteNonQueryAsync();
        }

        var completion = Task.Run(() => lifecycle.CommitFactsAsync(claim, facts, default));
        var blocked = await WaitForBlockedCompletionAsync();
        Assert.True(blocked > 0, "No backend ever blocked on the completion barrier.");

        var touchedTracks = await HoldsTrackTableLockAsync(blocked);

        await holding.RollbackAsync();
        Assert.True((await completion).IsSuccess);

        Assert.True(
            touchedTracks,
            "The completion was waiting on the exclusive barrier before writing its facts, "
                + "so the bulk insert runs inside a lock that blocks every search and every run completion.");
    }

    /// <summary>
    /// A database failure inside the final transaction must leave the unit recoverable and
    /// say so, with the stable code plan §AE names for it.
    /// </summary>
    /// <remarks>
    /// Nothing may be half-written, and the attempt must not be left <c>Running</c> with
    /// no explanation until its lease and grace expire — that is sixteen minutes of an
    /// operator seeing a unit that is not progressing and no reason why.
    /// </remarks>
    [Fact]
    public async Task ADatabaseFailureDuringTheFactCommitIsReportedAndRecoverable()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing());
        var (_, lifecycle, db) = world.Executor();
        await using var __ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(Policy, default);

        // A fact that references a Track which does not exist: the foreign key to tracks
        // is Restrict, so the database refuses the insert inside the final transaction.
        var executor = world.ExecutorWith(new PhantomTrackEvidenceReader(world), lifecycle);
        var result = await executor.ExecuteAsync(claim!, new SceneAnalyticsOptions(), default);

        Assert.False(result.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.PersistenceFailed, result.FailureCode);

        var unit = await world.UnitAsync(claim!.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Queued, unit.Status);
        Assert.Equal(SceneAnalyticsErrorCodes.PersistenceFailed, unit.FailureCode);
        Assert.Null(unit.ClaimTokenHash);
        Assert.Null(unit.VisibilitySequence);

        // Nothing partial survived the rollback.
        await using var reader = world.Read();
        Assert.Empty(await reader.TrackAnalysisOutcomes.ToListAsync());
        Assert.Empty(await reader.TrackZoneVisits.ToListAsync());
    }

    // --- Helpers -----------------------------------------------------------

    private static Task<int> QueueAsync(Mavi.Infrastructure.Persistence.Repositories.SceneAnalysisLifecycle lifecycle) =>
        lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            null,
            Now.AddDays(-1),
            50,
            default);

    /// <summary>The backend waiting on the completion barrier, or 0 if none appears.</summary>
    private async Task<int> WaitForBlockedCompletionAsync()
    {
        for (var attempt = 0; attempt < 200; attempt++)
        {
            await using var connection = new NpgsqlConnection(fixture.ConnectionString);
            await connection.OpenAsync();
            await using var command = new NpgsqlCommand(
                """
                SELECT pid FROM pg_locks
                WHERE locktype = 'advisory'
                  AND classid = 1296127561
                  AND objid = 1412505908
                  AND NOT granted
                LIMIT 1;
                """,
                connection);
            if (await command.ExecuteScalarAsync() is int pid)
            {
                return pid;
            }

            await Task.Delay(50);
        }

        return 0;
    }

    /// <summary>Whether the backend has already checked a foreign key into <c>tracks</c>.</summary>
    private async Task<bool> HoldsTrackTableLockAsync(int pid)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            """
            SELECT count(*) FROM pg_locks
            WHERE pid = @pid AND relation = 'tracks'::regclass AND granted;
            """,
            connection);
        command.Parameters.AddWithValue("pid", pid);
        return (long)(await command.ExecuteScalarAsync() ?? 0L) > 0;
    }

    /// <summary>Reports a Track that is not in the database, so its facts cannot be stored.</summary>
    private sealed class PhantomTrackEvidenceReader(SceneAnalyticsWorld world) : ISceneAnalysisEvidenceReader
    {
        public Task<IReadOnlyList<SceneAnalysisTrackEvidence>> ListRunTracksAsync(
            Guid processingRunId,
            CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<SceneAnalysisTrackEvidence>>(
                [new SceneAnalysisTrackEvidence(
                    Guid.CreateVersion7(),
                    ObjectClass.Person,
                    world.RecordingStartUtc,
                    "evidence/phantom/attempt-0001/trajectories/person-000001.msgpack",
                    null)]);

        public Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken) =>
            Task.FromResult<byte[]?>(TrajectoryPayload.StraightCrossing());
    }
}
