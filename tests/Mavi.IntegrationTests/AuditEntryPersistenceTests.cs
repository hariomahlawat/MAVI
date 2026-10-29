using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Identity;
using Mavi.Domain.Cameras;
using Mavi.Infrastructure.Audit;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// ADR-010 §4 against PostgreSQL: an audit entry commits and rolls back with the mutation it records (even one that
/// saves repeatedly and clears the change tracker),
/// takes its time from the server's <see cref="TimeProvider"/>, and the table refuses UPDATE, DELETE
/// and TRUNCATE from any client.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class AuditEntryPersistenceTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset ServerNow = new(2026, 10, 29, 9, 30, 0, TimeSpan.Zero);
    private static readonly string[] BatchCodes = ["AUDIT-B1", "AUDIT-B2"];
    private static readonly OperatorIdentity Alice = new("S-1-5-21-1-2-3-1001", "HOST\\alice", OperatorIdentityModes.WindowsNegotiate);

    [Fact]
    public async Task TheEntryCommitsWithTheMutationItRecords()
    {
        await using var db = await MigratedAsync();
        var camera = Camera.Create("AUDIT-01", "Audited camera", "UTC");

        var (_, receipt) = await Writer(db).RecordAsync(new AuditRecord("cameras.created", "camera", camera.Id.ToString(), new { camera.Code }),
            async cancellationToken =>
            {
                db.Cameras.Add(camera);
                return await db.SaveChangesAsync(cancellationToken);
            }, CancellationToken.None);

        await using var read = fixture.CreateDbContext();
        Assert.True(await read.Cameras.AnyAsync(x => x.Id == camera.Id));
        var entry = await read.AuditEntries.SingleAsync();
        Assert.Equal(receipt.AuditEntryId, entry.Id);
        Assert.Equal(Alice.OperatorId, entry.OperatorId);
        Assert.Equal(Alice.DisplayName, entry.OperatorDisplayName);
        Assert.Equal(OperatorIdentityModes.WindowsNegotiate, entry.IdentitySource);
        Assert.Equal("cameras.created", entry.Action);
        Assert.Equal(camera.Id.ToString(), entry.SubjectId);
        Assert.Equal(ServerNow, entry.RecordedAtUtc);
        Assert.Equal(AuditPayload.Sha256(new { camera.Code }), entry.PayloadSha256);
        Assert.Equal("correlation-1", entry.CorrelationId);
    }

    [Fact]
    public async Task AMutationThatSavesRepeatedlyAndClearsTheTrackerKeepsItsEntry()
    {
        // The shape of PlateLifecycle.RequestReanalysisAsync: clear the tracker, then one save per unit.
        await using var db = await MigratedAsync();
        await Writer(db).RecordAsync(new AuditRecord("cameras.created", "camera", "batch", null), async cancellationToken =>
        {
            db.ChangeTracker.Clear();
            foreach (var code in BatchCodes)
            {
                db.ChangeTracker.Clear();
                db.Cameras.Add(Camera.Create(code, code, "UTC"));
                await db.SaveChangesAsync(cancellationToken);
            }

            db.ChangeTracker.Clear();
            return 0;
        }, CancellationToken.None);

        await using var read = fixture.CreateDbContext();
        Assert.Equal(2, await read.Cameras.CountAsync());
        Assert.Equal(1, await read.AuditEntries.CountAsync());
    }

    [Fact]
    public async Task AFailedMutationLeavesNoEntryAndUndoesItsEarlierSaves()
    {
        await using var db = await MigratedAsync();
        db.Cameras.Add(Camera.Create("AUDIT-02", "First", "UTC"));
        await db.SaveChangesAsync();
        db.ChangeTracker.Clear();

        // One camera saves, then the duplicate code is refused: the whole mutation and its entry roll back.
        await Assert.ThrowsAsync<DbUpdateException>(() => Writer(db).RecordAsync(
            new AuditRecord("cameras.created", "camera", "batch", null), async cancellationToken =>
            {
                db.Cameras.Add(Camera.Create("AUDIT-03", "Saved first", "UTC"));
                await db.SaveChangesAsync(cancellationToken);
                db.Cameras.Add(Camera.Create("AUDIT-02", "Duplicate", "UTC"));
                return await db.SaveChangesAsync(cancellationToken);
            }, CancellationToken.None));

        await using var read = fixture.CreateDbContext();
        Assert.Equal(0, await read.AuditEntries.CountAsync());
        Assert.Equal(["AUDIT-02"], await read.Cameras.Select(x => x.Code).ToListAsync());
    }

    [Fact]
    public async Task AnEntryJoinsTheCallersTransactionAndRollsBackWithIt()
    {
        await using var db = await MigratedAsync();
        await using (var transaction = await db.Database.BeginTransactionAsync())
        {
            var camera = Camera.Create("AUDIT-04", "Rolled back", "UTC");
            db.Cameras.Add(camera);
            await db.SaveChangesAsync();
            await Writer(db).AppendInTransactionAsync(new AuditRecord("cameras.created", "camera", camera.Id.ToString(), null), CancellationToken.None);
            await Writer(db).RecordAsync(new AuditRecord("system.check", "system", "1", null), _ => Task.FromResult(0), CancellationToken.None);
            await transaction.RollbackAsync();
        }

        await using var read = fixture.CreateDbContext();
        Assert.Equal(0, await read.AuditEntries.CountAsync());
        Assert.Equal(0, await read.Cameras.CountAsync());
    }

    [Fact]
    public async Task OutsideATransactionAnEntryIsRefused()
    {
        await using var db = await MigratedAsync();

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            Writer(db).AppendInTransactionAsync(new AuditRecord("system.check", "system", "1", null), CancellationToken.None));

        await using var read = fixture.CreateDbContext();
        Assert.Equal(0, await read.AuditEntries.CountAsync());
    }

    [Theory]
    [InlineData("UPDATE audit_entries SET operator_id = 'someone-else'", "UPDATE")]
    [InlineData("DELETE FROM audit_entries", "DELETE")]
    [InlineData("TRUNCATE audit_entries", "TRUNCATE")]
    public async Task TheDatabaseRefusesToChangeOrRemoveAnEntry(string sql, string operation)
    {
        await using var db = await MigratedAsync();
        var (_, receipt) = await Writer(db).RecordAsync(new AuditRecord("system.check", "system", "1", null), _ => Task.FromResult(0),
            CancellationToken.None);

        // Raw SQL on its own connection: the guard is the database's, not the application's.
        await using (var connection = new NpgsqlConnection(fixture.ConnectionString))
        {
            await connection.OpenAsync();
            await using var command = new NpgsqlCommand(sql, connection);
            var exception = await Assert.ThrowsAsync<PostgresException>(() => command.ExecuteNonQueryAsync());
            Assert.Equal(PostgresErrorCodes.ObjectNotInPrerequisiteState, exception.SqlState);
            Assert.Contains($"append-only: {operation} is refused", exception.MessageText, StringComparison.Ordinal);
        }

        await using var read = fixture.CreateDbContext();
        var entry = await read.AuditEntries.SingleAsync();
        Assert.Equal(receipt.AuditEntryId, entry.Id);
        Assert.Equal(Alice.OperatorId, entry.OperatorId);
    }

    [Fact]
    public async Task TheMigrationRoundTripsAndRemovesItsGuard()
    {
        await using var db = await MigratedAsync();
        var migrations = db.Database.GetMigrations().ToList();
        var audit = migrations.Single(name => name.EndsWith("_AddAuditEntries", StringComparison.Ordinal));
        var preceding = migrations[migrations.IndexOf(audit) - 1];

        await db.GetService<Microsoft.EntityFrameworkCore.Migrations.IMigrator>().MigrateAsync(preceding);
        Assert.Equal(0L, await ScalarAsync("SELECT count(*) FROM pg_tables WHERE tablename = 'audit_entries'"));
        Assert.Equal(0L, await ScalarAsync("SELECT count(*) FROM pg_proc WHERE proname = 'audit_entries_refuse_change'"));

        await db.Database.MigrateAsync();
        Assert.Equal(2L, await ScalarAsync(
            "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'audit_entries'::regclass AND NOT tgisinternal"));
    }

    [Fact]
    public async Task WithoutAnOperatorTheMutationDoesNotRun()
    {
        await using var db = await MigratedAsync();
        var writer = new AuditWriter(db, new FixedOperator(null), new FixedCorrelation(), new FixedClock());
        var ran = false;

        await Assert.ThrowsAsync<InvalidOperationException>(() => writer.RecordAsync(new AuditRecord("system.check", "system", "1", null),
            _ => Task.FromResult(ran = true), CancellationToken.None));

        Assert.False(ran);
        await using var read = fixture.CreateDbContext();
        Assert.Equal(0, await read.AuditEntries.CountAsync());
    }

    private async Task<MaviDbContext> MigratedAsync()
    {
        await fixture.ResetDatabaseAsync();
        var db = fixture.CreateDbContext();
        await db.Database.MigrateAsync();
        return db;
    }

    private async Task<long> ScalarAsync(string sql)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        return Convert.ToInt64(await command.ExecuteScalarAsync(), System.Globalization.CultureInfo.InvariantCulture);
    }

    private static AuditWriter Writer(MaviDbContext db) => new(db, new FixedOperator(Alice), new FixedCorrelation(), new FixedClock());

    private sealed class FixedOperator(OperatorIdentity? identity) : ICurrentOperator
    {
        public OperatorIdentity? Current => identity;
    }

    private sealed class FixedCorrelation : IAuditCorrelation
    {
        public string CorrelationId => "correlation-1";
    }

    private sealed class FixedClock : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => ServerNow;
    }
}
