using Mavi.Application.Modules.Intelligence;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// The one invariant an analytic search rests on: the identity it establishes —
/// camera, scene revision, algorithm version and snapshot sequence — describes a
/// single world. Both publication events take the exclusive processing-visibility
/// barrier and hold it through commit, and a first page takes the shared counterpart
/// before it reads any scope at all.
/// </summary>
/// <remarks>
/// <para>
/// These are properties of two transactions racing, so they need a real server and a
/// second session. Coverage of what a single search then returns is in
/// <c>TrackSearchAnalyticsRepositoryTests</c>.
/// </para>
/// <para>
/// Both tests fail if either half of the scheme is missing. Resolving scope before
/// taking the shared lock pins the revision that was active in the earlier world while
/// counting against a snapshot taken in the later one; leaving activation outside the
/// exclusive lock means the search's lock orders nothing, because the party it is meant
/// to be ordered against never takes the other side.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class TrackSearchAnalyticsSerializationTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    /// <summary>
    /// A first page that starts while an activation is in flight must resolve its scope
    /// on the far side of that activation, because it blocked before reading anything.
    /// </summary>
    /// <remarks>
    /// The activation holds the exclusive barrier and has already written revision 2,
    /// but has not committed. The search therefore blocks at its very first statement.
    /// When the activation commits and the search proceeds, everything it reads is from
    /// the later world — so it must pin revision 2. A search that read its scope before
    /// the lock would have seen revision 1 (uncommitted writes are invisible) and would
    /// pin revision 1 against a snapshot allocated after the activation committed:
    /// coverage would then call a revision-1 gap Pending although reconciliation will
    /// only ever create revision-2 units.
    /// </remarks>
    [Fact]
    public async Task AFirstPageResolvesItsScopeOnTheFarSideOfAnActivationItWaitedFor()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var repository = new TrackSearchRepository(fixture.CreateDbContext(), world.Clock);

        // An activation in flight: barrier held, revision 2 written, not yet committed.
        await using var activationDb = fixture.CreateDbContext();
        await using var activation = await activationDb.Database.BeginTransactionAsync();
        var secondRevisionId = await world.ActivateNewRevisionAsync(activationDb, Now.AddMinutes(1));

        var search = Task.Run(() => repository.SearchAnalyticsAsync(
            new TrackSearchQuery(world.CameraId, null, null, null, null, null, null, null, null, 50,
                TrackAnalyticsQuery.Empty with { Loitering = true }),
            null,
            51,
            default));

        Assert.True(
            await WaitForBlockedBarrierAsync(),
            "The first page never blocked on the visibility barrier, so it was reading scope outside it.");

        await activation.CommitAsync();

        var result = await search;
        var page = Assert.IsType<TrackAnalyticsSearchRepositoryPage>(result.Page);
        Assert.Equal(secondRevisionId, page.Identity.SceneRevisionId);
        Assert.Equal(secondRevisionId, page.Coverage.SceneRevisionId);
    }

    /// <summary>
    /// A scene activation cannot commit while a first page holds the shared barrier.
    /// </summary>
    /// <remarks>
    /// Held from a second session so nothing depends on search timing. An activation
    /// that took no lock would finish immediately, which is the whole defect: the search
    /// side would be locking against a party that never participates.
    /// </remarks>
    [Fact]
    public async Task ASceneActivationWaitsForAFirstPageThatIsInFlight()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);

        await using var reader = new NpgsqlConnection(fixture.ConnectionString);
        await reader.OpenAsync();
        await using var holding = await reader.BeginTransactionAsync();
        await using (var acquire = new NpgsqlCommand(
            "SELECT pg_advisory_xact_lock_shared(1296127561, 1412505908)", reader, holding))
        {
            await acquire.ExecuteNonQueryAsync();
        }

        var activating = Task.Run(() => world.ActivateNewRevisionAsync(Now.AddMinutes(1)));

        Assert.True(
            await WaitForBlockedBarrierAsync(),
            "The activation never blocked on the visibility barrier, so it publishes outside the scheme.");
        Assert.False(activating.IsCompleted, "The activation committed while a first page held the barrier.");

        await holding.RollbackAsync();
        Assert.NotEqual(Guid.Empty, await activating);
    }

    /// <summary>The barrier is the advisory lock both publication paths and search take.</summary>
    private async Task<bool> WaitForBlockedBarrierAsync()
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
            if (await command.ExecuteScalarAsync() is int)
            {
                return true;
            }

            await Task.Delay(50);
        }

        return false;
    }
}
