using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Application.Modules.Entities;
using Mavi.Domain.Intelligence;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// ADR-027 §4 through the real API host and PostgreSQL: unlink (the Entity is kept with its remaining members, option (a)),
/// reopen, merge (every cross pair physically plausible, else refused with nothing written), concurrent opposite merges,
/// the append-only membership and candidate-decision histories with <c>Track.EntityId</c> as their projection, and the
/// back-fill of S7's decisions by the migration.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class EntityCorrectionApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset T0 = new(2026, 10, 31, 12, 0, 0, TimeSpan.Zero);

    private static EntitySeedTrack Person(double start, double end, double tilt = 0, int axis = 1) =>
        new(ObjectClass.Person, start, end, EntityApiHost.Vector(axis, tilt));

    /// <summary>
    /// Cameras A, B, C, D of one site. Axis 1: a0 (A 0–10), b0 (B 40–50), c0 (C 3–12, overlaps a0 elsewhere by 7 s), d0 (D 60–70).
    /// Axis 2: a1 (A 200–210), b1 (B 300–310), e1 (C 400–410).
    /// </summary>
    private sealed record World(EntityApiHost Host, Guid A0, Guid B0, Guid C0, Guid D0, Guid A1, Guid B1, Guid E1, List<JsonElement> Candidates)
    {
        public Guid Candidate(Guid x, Guid y) =>
            Candidates.Single(item => Pair(item) == (x.CompareTo(y) < 0 ? (x, y) : (y, x))).GetProperty("candidateId").GetGuid();

        private static (Guid, Guid) Pair(JsonElement candidate) =>
            (candidate.GetProperty("lower").GetProperty("trackId").GetGuid(), candidate.GetProperty("higher").GetProperty("trackId").GetGuid());
    }

    private async Task<World> SeedAsync()
    {
        var host = await EntityApiHost.CreateAsync(fixture, T0);
        var cameraB = await host.CameraAsync("CAM-COR-B");
        var cameraC = await host.CameraAsync("CAM-COR-C");
        var cameraD = await host.CameraAsync("CAM-COR-D");
        var a = await host.SeedAsync(host.World.CameraId, [Person(0, 10), Person(200, 210, tilt: 0.1, axis: 2)]);
        var b = await host.SeedAsync(cameraB, [Person(40, 50, tilt: 0.1), Person(300, 310, tilt: 0.15, axis: 2)]);
        var c = await host.SeedAsync(cameraC, [Person(3, 12, tilt: 0.05), Person(400, 410, tilt: 0.12, axis: 2)]);
        var d = await host.SeedAsync(cameraD, [Person(60, 70, tilt: 0.08)]);
        await host.EmbedAllAsync();
        await host.DeriveAsync();
        return new World(host, a.TrackIds[0], b.TrackIds[0], c.TrackIds[0], d.TrackIds[0], a.TrackIds[1], b.TrackIds[1], c.TrackIds[1],
            await host.CandidatesAsync("?limit=200"));
    }

    private static async Task<Guid> ConfirmAsync(World world, Guid x, Guid y)
    {
        using var response = await world.Host.DecideAsync(world.Candidate(x, y), "confirm");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return (await response.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("entityId").GetGuid();
    }

    [Fact]
    public async Task UnlinkKeepsTheEntityWithItsRemainingMemberAndRecordsTheLeave()
    {
        var world = await SeedAsync();
        await using var host = world.Host;
        var entity = await ConfirmAsync(world, world.A0, world.B0);

        using var unlinked = await host.Client.PostAsJsonAsync($"/api/entities/{entity}/unlink", new { trackId = world.B0, note = "different coat" });

        Assert.Equal(HttpStatusCode.OK, unlinked.StatusCode);
        var body = await unlinked.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal("Active", body.GetProperty("state").GetString());
        Assert.Equal([world.A0], body.GetProperty("members").EnumerateArray().Select(x => x.GetProperty("trackId").GetGuid()).ToList());
        Assert.Equal(["Joined:CandidateConfirmed", "Joined:CandidateConfirmed", "Left:Unlinked"],
            body.GetProperty("history").EnumerateArray().Select(x => x.GetProperty("change").GetString() + ":" + x.GetProperty("cause").GetString()));
        Assert.Equal("different coat", body.GetProperty("history")[2].GetProperty("note").GetString());
        var ids = await host.EntityIdsAsync(world.A0, world.B0);
        Assert.Equal(entity, ids[world.A0]);
        Assert.Null(ids[world.B0]);
        // The confirming candidate stays Confirmed in history; nothing was rewritten.
        Assert.Equal("confirmed", (await host.GetJsonAsync($"/api/entity-candidates/{world.Candidate(world.A0, world.B0)}")).GetProperty("status").GetString());
        await using (var db = host.World.Read())
        {
            var audit = await db.AuditEntries.SingleAsync(x => x.Action == "entities.track-unlinked");
            Assert.Equal(("entity", entity.ToString("D")), (audit.SubjectType, audit.SubjectId));
        }

        // The last member can go too: the Entity stays, empty, as the record of its decisions (option (a)).
        using (var last = await host.Client.PostAsJsonAsync($"/api/entities/{entity}/unlink", new { trackId = world.A0 }))
            Assert.Equal(HttpStatusCode.OK, last.StatusCode);
        Assert.Empty((await host.GetJsonAsync($"/api/entities/{entity}")).GetProperty("members").EnumerateArray());
        using (var again = await host.Client.PostAsJsonAsync($"/api/entities/{entity}/unlink", new { trackId = world.A0 }))
            Assert.Equal(EntityCorrectionRules.TrackNotMember, await VisualAttributeApiHost.ProblemCodeAsync(again));

        // The empty Entity is not merged: there is nothing to move and no membership row would carry the merge (Codex P2).
        var other = await ConfirmAsync(world, world.A1, world.B1);
        var audits = await host.AuditCountAsync();
        using (var empty = await host.Client.PostAsJsonAsync($"/api/entities/{entity}/merge", new { intoEntityId = other, note = "tidy up" }))
            Assert.Equal(EntityCorrectionRules.MergeSourceEmpty, await VisualAttributeApiHost.ProblemCodeAsync(empty));
        Assert.Equal(audits, await host.AuditCountAsync());
        Assert.Equal("Active", (await host.GetJsonAsync($"/api/entities/{entity}")).GetProperty("state").GetString());
        await AssertProjectionInvariantAsync(host);
    }

    [Fact]
    public async Task ReopenReturnsADismissedOrNoLongerLinkedCandidateToOpenAndKeepsItsHistory()
    {
        var world = await SeedAsync();
        await using var host = world.Host;
        var entity = await ConfirmAsync(world, world.A0, world.B0);
        var linked = world.Candidate(world.A0, world.B0);

        using (var stillLinked = await host.Client.PostAsJsonAsync($"/api/entity-candidates/{linked}/reopen", new { note = "x" }))
            Assert.Equal(EntityCorrectionRules.CandidateStillLinked, await VisualAttributeApiHost.ProblemCodeAsync(stillLinked));
        var open = world.Candidate(world.B0, world.D0);
        using (var notDecided = await host.Client.PostAsJsonAsync($"/api/entity-candidates/{open}/reopen", new { note = (string?)null }))
            Assert.Equal(EntityCorrectionRules.CandidateNotDecided, await VisualAttributeApiHost.ProblemCodeAsync(notDecided));

        using (await host.Client.PostAsJsonAsync($"/api/entities/{entity}/unlink", new { trackId = world.B0 })) { }
        using (var reopened = await host.Client.PostAsJsonAsync($"/api/entity-candidates/{linked}/reopen", new { note = "it was the same coat" }))
            Assert.Equal(HttpStatusCode.OK, reopened.StatusCode);
        Assert.Equal("open", (await host.GetJsonAsync($"/api/entity-candidates/{linked}")).GetProperty("status").GetString());

        // Confirmed again: b0 rejoins the Entity a0 still holds (an extension), and every decision is in the history.
        Assert.Equal(entity, await ConfirmAsync(world, world.A0, world.B0));
        var history = (await host.GetJsonAsync($"/api/entity-candidates/{linked}/history")).GetProperty("decisions").EnumerateArray()
            .Select(x => x.GetProperty("decision").GetString()).ToList();
        Assert.Equal(["Confirmed", "Reopened", "Confirmed"], history);

        // The Entity's audit subjects keep every candidate ever linked to it, read from the histories: after the reopen the
        // candidate stood Open, yet its first confirmation and the reopen belong to this Entity's trail (Codex P2).
        using (await host.Client.PostAsJsonAsync($"/api/entities/{entity}/unlink", new { trackId = world.B0 })) { }
        using (await host.Client.PostAsJsonAsync($"/api/entity-candidates/{linked}/reopen", new { note = "again" })) { }
        var related = (await host.GetJsonAsync($"/api/entities/{entity}")).GetProperty("relatedCandidateIds").EnumerateArray()
            .Select(x => x.GetGuid()).ToList();
        Assert.Equal([linked], related);
        Assert.Empty((await host.GetJsonAsync($"/api/entities/{entity}")).GetProperty("confirmations").EnumerateArray());

        // A dismissal can be reopened too.
        using (var dismissed = await host.DecideAsync(open, "dismiss")) Assert.Equal(HttpStatusCode.OK, dismissed.StatusCode);
        using (var reopenDismissed = await host.Client.PostAsJsonAsync($"/api/entity-candidates/{open}/reopen", new { note = "look again" }))
            Assert.Equal(HttpStatusCode.OK, reopenDismissed.StatusCode);
        Assert.Equal(1, await host.AuditCountAsync("entities.candidate-dismissed"));
        Assert.Equal(3, await host.AuditCountAsync("entities.candidate-reopened"));
        await AssertProjectionInvariantAsync(host);
    }

    [Fact]
    public async Task AMergeMovesEveryMemberKeepsTheSourceAsMergedAndRecordsLeavesAndJoins()
    {
        var world = await SeedAsync();
        await using var host = world.Host;
        var first = await ConfirmAsync(world, world.A0, world.B0);
        var second = await ConfirmAsync(world, world.A1, world.B1);

        using (var self = await host.Client.PostAsJsonAsync($"/api/entities/{first}/merge", new { intoEntityId = first }))
            Assert.Equal(EntityCorrectionRules.MergeInvalid, await VisualAttributeApiHost.ProblemCodeAsync(self));
        using var merged = await host.Client.PostAsJsonAsync($"/api/entities/{second}/merge", new { intoEntityId = first, note = "same jacket" });

        Assert.Equal(HttpStatusCode.OK, merged.StatusCode);
        var target = await merged.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal(first, target.GetProperty("entityId").GetGuid());
        Assert.Equal(4, target.GetProperty("members").GetArrayLength());
        Assert.Equal(2, target.GetProperty("confirmations").GetArrayLength());
        Assert.Equal([second], target.GetProperty("mergedFromEntityIds").EnumerateArray().Select(x => x.GetGuid()).ToList());
        var source = await host.GetJsonAsync($"/api/entities/{second}");
        Assert.Equal("Merged", source.GetProperty("state").GetString());
        Assert.Equal(first, source.GetProperty("mergedIntoEntityId").GetGuid());
        Assert.Empty(source.GetProperty("members").EnumerateArray());
        Assert.Equal(["Joined:CandidateConfirmed", "Joined:CandidateConfirmed", "Left:Merged", "Left:Merged"],
            source.GetProperty("history").EnumerateArray().Select(x => x.GetProperty("change").GetString() + ":" + x.GetProperty("cause").GetString()));
        Assert.Equal("Unknown", target.GetProperty("identityStatus").GetString());
        var ids = await host.EntityIdsAsync(world.A0, world.B0, world.A1, world.B1);
        Assert.All(ids.Values, value => Assert.Equal(first, value));

        // A merged Entity no longer changes.
        using (var again = await host.Client.PostAsJsonAsync($"/api/entities/{second}/merge", new { intoEntityId = first }))
            Assert.Equal(EntityCorrectionRules.EntityNotActive, await VisualAttributeApiHost.ProblemCodeAsync(again));
        using (var unlink = await host.Client.PostAsJsonAsync($"/api/entities/{second}/unlink", new { trackId = world.A1 }))
            Assert.Equal(EntityCorrectionRules.EntityNotActive, await VisualAttributeApiHost.ProblemCodeAsync(unlink));
        await using (var db = host.World.Read())
        {
            var audit = await db.AuditEntries.SingleAsync(x => x.Action == "entities.merged");
            Assert.Equal(("entity", second.ToString("D")), (audit.SubjectType, audit.SubjectId));
            Assert.True(await db.EntityMembershipChanges.Where(x => x.Cause == EntityMembershipCause.Merged).AllAsync(x => x.AuditEntryId == audit.Id));
        }

        await AssertProjectionInvariantAsync(host);
    }

    [Fact]
    public async Task AMergeWithAnImpossibleCrossPairIsRefusedAndWritesNothing()
    {
        var world = await SeedAsync();
        await using var host = world.Host;
        var first = await ConfirmAsync(world, world.A0, world.B0);
        var third = await ConfirmAsync(world, world.C0, world.D0);
        var audits = await host.AuditCountAsync();

        using var refused = await host.Client.PostAsJsonAsync($"/api/entities/{third}/merge", new { intoEntityId = first });

        Assert.Equal(HttpStatusCode.Conflict, refused.StatusCode);
        var problem = await refused.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal(EntityCorrectionRules.MergeImplausible, problem.GetProperty("code").GetString());
        Assert.Equal(world.C0, problem.GetProperty("conflictingTrackId").GetGuid());
        Assert.Equal(world.A0, problem.GetProperty("otherConflictingTrackId").GetGuid());
        Assert.Equal(audits, await host.AuditCountAsync());
        var ids = await host.EntityIdsAsync(world.C0, world.D0);
        Assert.All(ids.Values, value => Assert.Equal(third, value));
        Assert.Equal("Active", (await host.GetJsonAsync($"/api/entities/{third}")).GetProperty("state").GetString());
    }

    [Fact]
    public async Task OppositeMergesAtTheSameTimeAreSerialisedSoExactlyOneHappens()
    {
        var world = await SeedAsync();
        await using var host = world.Host;
        var first = await ConfirmAsync(world, world.A0, world.B0);
        var second = await ConfirmAsync(world, world.A1, world.B1);

        var responses = await Task.WhenAll(
            host.Client.PostAsJsonAsync($"/api/entities/{second}/merge", new { intoEntityId = first }),
            host.Client.PostAsJsonAsync($"/api/entities/{first}/merge", new { intoEntityId = second }));

        Assert.Equal(1, responses.Count(r => r.StatusCode == HttpStatusCode.OK));
        Assert.Equal(1, responses.Count(r => r.StatusCode == HttpStatusCode.Conflict));
        foreach (var response in responses) response.Dispose();
        Assert.Equal(1, await host.AuditCountAsync("entities.merged"));
        await using (var db = host.World.Read())
            Assert.Equal(1, await db.Entities.CountAsync(x => x.State == EntityMergeState.Merged));
        await AssertProjectionInvariantAsync(host);
    }

    [Fact]
    public async Task TheHistoriesAreAppendOnlyAndTheMigrationBackFillsS7Decisions()
    {
        var world = await SeedAsync();
        await using var host = world.Host;
        var entity = await ConfirmAsync(world, world.A0, world.B0);
        using (await host.DecideAsync(world.Candidate(world.B0, world.D0), "dismiss")) { }
        List<(Guid TrackId, Guid EntityId, string OperatorId, DateTimeOffset At, Guid Audit)> live;
        await using (var db = host.World.Read())
            live = (await db.EntityMembershipChanges.OrderBy(x => x.TrackId).ToListAsync())
                .Select(x => (x.TrackId, x.EntityId, x.OperatorId, x.AtUtc, x.AuditEntryId)).ToList();
        Assert.Equal(2, live.Count);

        await using (var connection = new NpgsqlConnection(host.Factory.ConnectionString))
        {
            await connection.OpenAsync();
            foreach (var sql in new[]
                     {
                         "UPDATE entity_membership_changes SET note = 'edited'", "DELETE FROM entity_membership_changes",
                         "TRUNCATE entity_membership_changes", "UPDATE entity_candidate_decisions SET note = 'edited'",
                         "DELETE FROM entity_candidate_decisions",
                     })
            {
                await using var command = new NpgsqlCommand(sql, connection);
                var exception = await Assert.ThrowsAsync<PostgresException>(() => command.ExecuteNonQueryAsync());
                Assert.Equal(PostgresErrorCodes.ObjectNotInPrerequisiteState, exception.SqlState);
            }
        }

        // Down to S7's schema and up again: the back-fill rebuilds both histories from S7's own decision fields.
        await using (var scope = host.Factory.Services.CreateAsyncScope())
        {
            var migrator = scope.ServiceProvider.GetRequiredService<MaviDbContext>().GetService<IMigrator>();
            await migrator.MigrateAsync("20261030195205_AddReviewAndCases");
            await migrator.MigrateAsync();
        }

        await using (var db = host.World.Read())
        {
            var rebuilt = (await db.EntityMembershipChanges.OrderBy(x => x.TrackId).ToListAsync())
                .Select(x => (x.TrackId, x.EntityId, x.OperatorId, x.AtUtc, x.AuditEntryId)).ToList();
            Assert.Equal(live, rebuilt);
            Assert.True(await db.EntityMembershipChanges.AllAsync(x => x.Cause == EntityMembershipCause.CandidateConfirmed &&
                                                                    x.Change == EntityMembershipChangeKind.Joined && x.EntityId == entity));
            Assert.Equal([EntityCandidateDecisionKind.Confirmed, EntityCandidateDecisionKind.Dismissed],
                (await db.EntityCandidateDecisions.OrderBy(x => x.Sequence).ToListAsync()).Select(x => x.Decision).ToList());
            Assert.True(await db.Entities.AllAsync(x => x.State == EntityMergeState.Active));
        }

        await AssertProjectionInvariantAsync(host);
    }

    [Fact]
    public async Task AnEntityCanBeAddedToACaseWithoutTouchingItsMembership()
    {
        var world = await SeedAsync();
        await using var host = world.Host;
        var entity = await ConfirmAsync(world, world.A0, world.B0);
        using var created = await host.Client.PostAsJsonAsync("/api/cases", new { title = "Gate" });
        var caseId = (await created.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("caseId").GetGuid();

        using var added = await host.Client.PostAsJsonAsync($"/api/cases/{caseId}/items", new { kind = "Entity", subjectId = entity, note = "follow up" });

        Assert.Equal(HttpStatusCode.Created, added.StatusCode);
        var item = await added.Content.ReadFromJsonAsync<JsonElement>();
        Assert.True(item.GetProperty("subject").GetProperty("available").GetBoolean());
        Assert.StartsWith("P-", item.GetProperty("subject").GetProperty("entityDisplayCode").GetString(), StringComparison.Ordinal);
        await using var db = host.World.Read();
        Assert.Equal(2, await db.EntityMembershipChanges.CountAsync());
        Assert.Equal(2, await db.Tracks.CountAsync(x => x.EntityId == entity));
    }

    [Fact]
    public async Task AnExtensionAndAnUnlinkOfTheSameEntityAtTheSameTimeLeaveConsistentHistories()
    {
        var world = await SeedAsync();
        await using var host = world.Host;
        var entity = await ConfirmAsync(world, world.A0, world.B0);

        // b0–d0 extends the Entity with d0 while b0 is unlinked: either order is a valid outcome, never a mixture.
        var responses = await Task.WhenAll(
            host.DecideAsync(world.Candidate(world.B0, world.D0), "confirm"),
            host.Client.PostAsJsonAsync($"/api/entities/{entity}/unlink", new { trackId = world.B0 }));

        Assert.All(responses, r => Assert.Equal(HttpStatusCode.OK, r.StatusCode));
        foreach (var response in responses) response.Dispose();
        var ids = await host.EntityIdsAsync(world.A0, world.B0, world.D0);
        Assert.Equal(entity, ids[world.A0]);
        // Extension first: d0 joins, then b0 leaves. Unlink first: b0 and d0 form a new Entity.
        Assert.True((ids[world.B0] is null && ids[world.D0] == entity) ||
                    (ids[world.B0] is { } other && other != entity && ids[world.D0] == other));
        Assert.Equal(2, await host.AuditCountAsync("entities.candidate-confirmed"));
        Assert.Equal(1, await host.AuditCountAsync("entities.track-unlinked"));
        await AssertProjectionInvariantAsync(host);
    }

    [Fact]
    public async Task AnExtensionOfTheKeptEntityAndAMergeAtTheSameTimeNeverLoseAMember()
    {
        var world = await SeedAsync();
        await using var host = world.Host;
        var first = await ConfirmAsync(world, world.A0, world.B0);
        var second = await ConfirmAsync(world, world.A1, world.B1);

        var responses = await Task.WhenAll(
            host.DecideAsync(world.Candidate(world.B0, world.D0), "confirm"),
            host.Client.PostAsJsonAsync($"/api/entities/{second}/merge", new { intoEntityId = first }));

        // The confirm always applies. The merge applies, or (when the confirm committed between the merge's read of the members
        // and its locks) is refused as entity_changed_concurrently with nothing written: both are correct serialisations.
        Assert.Equal(HttpStatusCode.OK, responses[0].StatusCode);
        var merged = responses[1].StatusCode == HttpStatusCode.OK;
        if (!merged) Assert.Equal(EntityCorrectionRules.ChangedConcurrently, await VisualAttributeApiHost.ProblemCodeAsync(responses[1]));
        foreach (var response in responses) response.Dispose();
        var ids = await host.EntityIdsAsync(world.A0, world.B0, world.D0, world.A1, world.B1);
        Assert.Equal(first, ids[world.D0]);
        Assert.Equal(merged ? first : second, ids[world.A1]);
        Assert.Equal(merged ? first : second, ids[world.B1]);
        Assert.Equal(merged ? 1 : 0, await host.AuditCountAsync("entities.merged"));
        await AssertProjectionInvariantAsync(host);
    }

    [Fact]
    public async Task AJoinIntoTheEntityBeingMergedAwayIsNeverLeftInAMergedEntity()
    {
        var world = await SeedAsync();
        await using var host = world.Host;
        var first = await ConfirmAsync(world, world.A0, world.B0);
        var second = await ConfirmAsync(world, world.A1, world.B1);

        // b1–e1 extends the Entity that is being merged away. Whatever the order, e1 must end in an active Entity: the kept
        // one if the merge moved it (or ran first and the confirm then extended the kept Entity), else the second.
        var responses = await Task.WhenAll(
            host.DecideAsync(world.Candidate(world.B1, world.E1), "confirm"),
            host.Client.PostAsJsonAsync($"/api/entities/{second}/merge", new { intoEntityId = first }));

        Assert.Equal(HttpStatusCode.OK, responses[0].StatusCode);
        var merged = responses[1].StatusCode == HttpStatusCode.OK;
        if (!merged) Assert.Equal(EntityCorrectionRules.ChangedConcurrently, await VisualAttributeApiHost.ProblemCodeAsync(responses[1]));
        foreach (var response in responses) response.Dispose();
        var ids = await host.EntityIdsAsync(world.A1, world.B1, world.E1);
        Assert.All(ids.Values, value => Assert.Equal(merged ? first : second, value));
        await using (var db = host.World.Read())
        {
            var holder = ids[world.E1]!.Value;
            Assert.Equal(EntityMergeState.Active, (await db.Entities.SingleAsync(x => x.Id == holder)).State);
        }

        await AssertProjectionInvariantAsync(host);
    }

    [Fact]
    public async Task AReopenAndAConfirmOfTheSameCandidateAtTheSameTimeAreSerialised()
    {
        var world = await SeedAsync();
        await using var host = world.Host;
        var entity = await ConfirmAsync(world, world.A0, world.B0);
        using (await host.Client.PostAsJsonAsync($"/api/entities/{entity}/unlink", new { trackId = world.B0 })) { }
        var candidate = world.Candidate(world.A0, world.B0);

        var responses = await Task.WhenAll(
            host.Client.PostAsJsonAsync($"/api/entity-candidates/{candidate}/reopen", new { note = "again" }),
            host.DecideAsync(candidate, "confirm"));

        // The reopen always applies (the pair was apart); the confirm applies only if it came second.
        Assert.Equal(HttpStatusCode.OK, responses[0].StatusCode);
        var confirmed = responses[1].StatusCode == HttpStatusCode.OK;
        if (!confirmed) Assert.Equal(EntityConfirmationRules.AlreadyDecided, await VisualAttributeApiHost.ProblemCodeAsync(responses[1]));
        foreach (var response in responses) response.Dispose();
        var status = (await host.GetJsonAsync($"/api/entity-candidates/{candidate}")).GetProperty("status").GetString();
        Assert.Equal(confirmed ? "confirmed" : "open", status);
        Assert.Equal(confirmed ? entity : null, (await host.EntityIdsAsync(world.B0))[world.B0]);
        await AssertProjectionInvariantAsync(host);
    }

    /// <summary>
    /// ADR-027 §4, §6: every projection equals its history. A Track's <c>entity_id</c> is its latest membership change (a join's
    /// Entity, null after a leave or none); a candidate's status, Entity and decision audit entry are its latest decision's (Open
    /// with none or after a reopen); a Merged Entity names another, has no members and a recorded merge; an Active one names none.
    /// </summary>
    private static async Task AssertProjectionInvariantAsync(EntityApiHost host)
    {
        await using var connection = new NpgsqlConnection(host.Factory.ConnectionString);
        await connection.OpenAsync();
        foreach (var sql in ProjectionChecks)
        {
            await using var command = new NpgsqlCommand(sql, connection);
            Assert.Equal(0L, (long)(await command.ExecuteScalarAsync())!);
        }
    }

    private static readonly string[] ProjectionChecks =
    [
        """
        SELECT count(*) FROM tracks t
        LEFT JOIN LATERAL (SELECT m.change, m.entity_id FROM entity_membership_changes m WHERE m.track_id = t.id
                           ORDER BY m.sequence DESC LIMIT 1) latest ON TRUE
        WHERE t.entity_id IS DISTINCT FROM (CASE WHEN latest.change = 'Joined' THEN latest.entity_id END)
        """,
        """
        SELECT count(*) FROM entity_candidates c
        LEFT JOIN LATERAL (SELECT d.decision, d.entity_id, d.audit_entry_id FROM entity_candidate_decisions d
                           WHERE d.candidate_id = c.id ORDER BY d.sequence DESC LIMIT 1) latest ON TRUE
        WHERE c.status <> COALESCE(CASE latest.decision WHEN 'Reopened' THEN 'Open' ELSE latest.decision END, 'Open')
           OR c.entity_id IS DISTINCT FROM latest.entity_id
           OR c.decision_audit_entry_id IS DISTINCT FROM (CASE WHEN latest.decision IN ('Confirmed', 'Dismissed') THEN latest.audit_entry_id END)
        """,
        """
        SELECT count(*) FROM entities e
        WHERE (e.state = 'Merged') <> (e.merged_into_entity_id IS NOT NULL)
           OR (e.state = 'Merged' AND EXISTS (SELECT 1 FROM tracks t WHERE t.entity_id = e.id))
           OR (e.state = 'Merged' AND NOT EXISTS (SELECT 1 FROM entity_membership_changes m WHERE m.entity_id = e.id AND m.cause = 'Merged'))
        """,
    ];
}
