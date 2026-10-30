using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Application.Deployment;
using Mavi.Domain.Cameras;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// PoC S11-full (ADR-027 §1–§3, §5) at the HTTP boundary against PostgreSQL: Track review decisions (one transaction with
/// the audit row, expectation conflict, idempotent replay, serialised concurrency, server time, the operator from the
/// principal), the review plan §5 invariants, cases (append-only items whose removal is recorded, notes, no identity
/// write), the audit read surface, and reprocessing awareness.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class ReviewAndCaseApiTests : IDisposable
{
    private static readonly DateTimeOffset Start = new(2026, 10, 31, 8, 0, 0, TimeSpan.Zero);
    private readonly string _root = Path.Combine(Path.GetTempPath(), $"mavi-review-api-{Guid.NewGuid():N}");
    private readonly MutableClock _clock = new(Start);

    public ReviewAndCaseApiTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); }
        catch (IOException) { }
    }

    // --- Track review decisions ------------------------------------------------------------------

    [Fact]
    public async Task ADecisionIsRecordedWithItsAuditRowServerTimeAndTheOperatorFromThePrincipal()
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();
        _clock.Now = Start.AddMinutes(7);

        // A reviewer or time in the body is ignored: both come from the server.
        using var response = await client.PostAsJsonAsync($"/api/tracks/{world.TrackA}/review", new
        {
            decisionId = Guid.CreateVersion7(), decision = "Confirmed", expectedReviewStatus = "Unreviewed", note = "  person at gate  ",
            operatorId = "mallory", decidedAtUtc = "2001-01-01T00:00:00Z",
        });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal("Confirmed", body.RootElement.GetProperty("reviewStatus").GetString());
        var latest = body.RootElement.GetProperty("latestDecision");
        Assert.Equal("development-unattributed", latest.GetProperty("operatorId").GetString());
        Assert.Equal("person at gate", latest.GetProperty("note").GetString());

        await using var db = Db(factory);
        var decision = await db.TrackReviewDecisions.SingleAsync();
        var audit = await db.AuditEntries.SingleAsync();
        Assert.Equal(audit.Id, decision.AuditEntryId);
        Assert.Equal("tracks.review-decided", audit.Action);
        Assert.Equal(("track", world.TrackA.ToString("D")), (audit.SubjectType, audit.SubjectId));
        Assert.Equal(_clock.Now, decision.DecidedAtUtc);
        Assert.Equal(audit.RecordedAtUtc, decision.DecidedAtUtc);
        Assert.Equal("development-unattributed", decision.IdentitySource);
        Assert.Equal(ReviewStatus.Confirmed, (await db.Tracks.SingleAsync(x => x.Id == world.TrackA)).ReviewStatus);

        // The anonymous detail and search read the same persisted column.
        using var detail = JsonDocument.Parse(await client.GetStringAsync($"/api/tracks/{world.TrackA}"));
        Assert.Equal("Confirmed", detail.RootElement.GetProperty("reviewStatus").GetString());
        Assert.False(detail.RootElement.TryGetProperty("latestDecision", out _));
        using var search = JsonDocument.Parse(await client.GetStringAsync($"/api/tracks?processingRunId={world.RunB:D}"));
        var item = search.RootElement.GetProperty("items").EnumerateArray().Single(x => x.GetProperty("id").GetGuid() == world.TrackA);
        Assert.Equal("Confirmed", item.GetProperty("reviewStatus").GetString());
        await AssertProjectionInvariantAsync(factory);
    }

    [Fact]
    public async Task AnIdenticalReplayWritesNothingAndAReusedIdWithAnotherPayloadIsAConflict()
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();
        var decisionId = Guid.CreateVersion7();
        var request = new { decisionId, decision = "Rejected", expectedReviewStatus = "Unreviewed", note = "glare" };

        using var first = await client.PostAsJsonAsync($"/api/tracks/{world.TrackA}/review", request);
        _clock.Now = Start.AddMinutes(1);
        using var replay = await client.PostAsJsonAsync($"/api/tracks/{world.TrackA}/review", request);
        using var reused = await client.PostAsJsonAsync($"/api/tracks/{world.TrackA}/review",
            new { decisionId, decision = "Rejected", expectedReviewStatus = "Unreviewed", note = "different" });
        using var elsewhere = await client.PostAsJsonAsync($"/api/tracks/{world.TrackB}/review", request);

        Assert.Equal(HttpStatusCode.OK, first.StatusCode);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        using (var body = JsonDocument.Parse(await replay.Content.ReadAsStringAsync()))
        {
            Assert.True(body.RootElement.GetProperty("replayed").GetBoolean());
            Assert.Equal(Start, body.RootElement.GetProperty("latestDecision").GetProperty("decidedAtUtc").GetDateTimeOffset());
        }

        await AssertProblemAsync(reused, HttpStatusCode.Conflict, "track_review_decision_conflict");
        await AssertProblemAsync(elsewhere, HttpStatusCode.Conflict, "track_review_decision_conflict");
        await using var db = Db(factory);
        Assert.Equal(1, await db.TrackReviewDecisions.CountAsync());
        Assert.Equal(1, await db.AuditEntries.CountAsync());
        Assert.Equal(ReviewStatus.Unreviewed, (await db.Tracks.SingleAsync(x => x.Id == world.TrackB)).ReviewStatus);
    }

    [Fact]
    public async Task AStaleExpectationIsRefusedWithTheCurrentDecisionAndWritesNothing()
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();
        await DecideAsync(client, world.TrackA, "Confirmed", "Unreviewed");

        using var stale = await client.PostAsJsonAsync($"/api/tracks/{world.TrackA}/review",
            new { decisionId = Guid.CreateVersion7(), decision = "Rejected", expectedReviewStatus = "Unreviewed" });

        Assert.Equal(HttpStatusCode.Conflict, stale.StatusCode);
        using var body = JsonDocument.Parse(await stale.Content.ReadAsStringAsync());
        Assert.Equal("track_review_conflict", body.RootElement.GetProperty("code").GetString());
        Assert.Equal("Confirmed", body.RootElement.GetProperty("currentReviewStatus").GetString());
        Assert.Equal("Confirmed", body.RootElement.GetProperty("currentDecision").GetProperty("decision").GetString());
        await using var db = Db(factory);
        Assert.Equal(1, await db.TrackReviewDecisions.CountAsync());
        Assert.Equal(1, await db.AuditEntries.CountAsync());
    }

    [Fact]
    public async Task ConcurrentDecisionsOnOneTrackAreSerialisedSoExactlyOneWins()
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();

        var attempts = Enumerable.Range(0, 8).Select(index => client.PostAsJsonAsync($"/api/tracks/{world.TrackA}/review", new
        {
            decisionId = Guid.CreateVersion7(), decision = index % 2 == 0 ? "Confirmed" : "Rejected", expectedReviewStatus = "Unreviewed",
        })).ToArray();
        var responses = await Task.WhenAll(attempts);

        Assert.Equal(1, responses.Count(r => r.StatusCode == HttpStatusCode.OK));
        Assert.Equal(7, responses.Count(r => r.StatusCode == HttpStatusCode.Conflict));
        foreach (var response in responses) response.Dispose();
        await using var db = Db(factory);
        Assert.Equal(1, await db.TrackReviewDecisions.CountAsync());
        Assert.Equal(1, await db.AuditEntries.CountAsync());
        await AssertProjectionInvariantAsync(factory);
    }

    [Fact]
    public async Task HistoryIsPreservedNewestFirstAndClearNeedsADecisionToClear()
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();

        using var nothing = await client.PostAsJsonAsync($"/api/tracks/{world.TrackA}/review",
            new { decisionId = Guid.CreateVersion7(), decision = "Cleared", expectedReviewStatus = "Unreviewed" });
        await AssertProblemAsync(nothing, HttpStatusCode.Conflict, "track_review_nothing_to_clear");
        await DecideAsync(client, world.TrackA, "Confirmed", "Unreviewed");
        _clock.Now = Start.AddMinutes(1);
        await DecideAsync(client, world.TrackA, "Rejected", "Confirmed");
        _clock.Now = Start.AddMinutes(2);
        await DecideAsync(client, world.TrackA, "Cleared", "Rejected");

        using var page1 = JsonDocument.Parse(await client.GetStringAsync($"/api/tracks/{world.TrackA}/review-history?limit=2"));
        var items1 = page1.RootElement.GetProperty("items").EnumerateArray().Select(x => x.GetProperty("decision").GetString()).ToList();
        Assert.Equal(["Cleared", "Rejected"], items1);
        var cursor = page1.RootElement.GetProperty("nextCursor").GetString();
        using var page2 = JsonDocument.Parse(await client.GetStringAsync($"/api/tracks/{world.TrackA}/review-history?limit=2&cursor={cursor}"));
        Assert.Equal(["Confirmed"],
            page2.RootElement.GetProperty("items").EnumerateArray().Select(x => x.GetProperty("decision").GetString()).ToList());
        Assert.Equal(JsonValueKind.Null, page2.RootElement.GetProperty("nextCursor").ValueKind);

        using var state = JsonDocument.Parse(await client.GetStringAsync($"/api/tracks/{world.TrackA}/review"));
        Assert.Equal("Unreviewed", state.RootElement.GetProperty("reviewStatus").GetString());
        Assert.Equal("Cleared", state.RootElement.GetProperty("latestDecision").GetProperty("decision").GetString());
        await AssertProjectionInvariantAsync(factory);
    }

    [Theory]
    [InlineData("1", "Unreviewed")]
    [InlineData("confirmed", "Unreviewed")]
    [InlineData("Confirmed", "0")]
    [InlineData("Confirmed", null)]
    public async Task OnlyNamedDecisionsAndStatusesAreAccepted(string decision, string? expected)
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();

        using var response = await client.PostAsJsonAsync($"/api/tracks/{world.TrackA}/review",
            new { decisionId = Guid.CreateVersion7(), decision, expectedReviewStatus = expected });

        await AssertProblemAsync(response, HttpStatusCode.BadRequest, "track_review_invalid");
    }

    [Fact]
    public async Task ATooLongNoteIsRefusedAndAnUnknownTrackIsNotFound()
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();

        using var tooLong = await client.PostAsJsonAsync($"/api/tracks/{world.TrackA}/review",
            new { decisionId = Guid.CreateVersion7(), decision = "Confirmed", expectedReviewStatus = "Unreviewed", note = new string('x', 1001) });
        using var unknown = await client.PostAsJsonAsync($"/api/tracks/{Guid.CreateVersion7()}/review",
            new { decisionId = Guid.CreateVersion7(), decision = "Confirmed", expectedReviewStatus = "Unreviewed" });

        await AssertProblemAsync(tooLong, HttpStatusCode.BadRequest, "track_review_note_too_long");
        await AssertProblemAsync(unknown, HttpStatusCode.NotFound, "track_not_found");
        await using var db = Db(factory);
        Assert.Equal(0, await db.AuditEntries.CountAsync());
    }

    [Fact]
    public async Task WithIdentityDisabledEveryReviewCaseAndAuditRouteIsRefused()
    {
        using var factory = await CreateAsync(identityMode: "disabled");
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();

        using var decide = await client.PostAsJsonAsync($"/api/tracks/{world.TrackA}/review",
            new { decisionId = Guid.CreateVersion7(), decision = "Confirmed", expectedReviewStatus = "Unreviewed" });
        using var review = await client.GetAsync($"/api/tracks/{world.TrackA}/review");
        using var cases = await client.PostAsJsonAsync("/api/cases", new { title = "x" });
        using var audit = await client.GetAsync("/api/audit");

        Assert.All(new[] { decide, review, cases, audit }, r => Assert.Equal(HttpStatusCode.Unauthorized, r.StatusCode));
        await using var db = Db(factory);
        Assert.Equal(0, await db.TrackReviewDecisions.CountAsync());
        Assert.Equal(0, await db.Cases.CountAsync());
    }

    [Fact]
    public async Task ReprocessingCarriesNothingOverAndTheNewRunShowsTheEarlierRunsDecisions()
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();
        await DecideAsync(client, world.EarlierRunTrack, "Confirmed", "Unreviewed");

        using var state = JsonDocument.Parse(await client.GetStringAsync($"/api/tracks/{world.TrackA}/review"));

        Assert.Equal("Unreviewed", state.RootElement.GetProperty("reviewStatus").GetString());
        Assert.Equal(JsonValueKind.Null, state.RootElement.GetProperty("latestDecision").ValueKind);
        var other = Assert.Single(state.RootElement.GetProperty("otherRuns").EnumerateArray());
        Assert.Equal(world.RunA, other.GetProperty("processingRunId").GetGuid());
        Assert.Equal(1, other.GetProperty("reviewedTrackCount").GetInt32());
        await using var db = Db(factory);
        Assert.Equal(1, await db.TrackReviewDecisions.CountAsync());
        Assert.Equal(ReviewStatus.Unreviewed, (await db.Tracks.SingleAsync(x => x.Id == world.TrackA)).ReviewStatus);
    }

    // --- Append-only guards and invariants ---------------------------------------------------------

    [Theory]
    [InlineData("UPDATE track_review_decisions SET note = 'edited'")]
    [InlineData("DELETE FROM track_review_decisions")]
    [InlineData("TRUNCATE track_review_decisions CASCADE")]
    [InlineData("UPDATE cases SET title = 'edited'")]
    [InlineData("DELETE FROM cases")]
    [InlineData("TRUNCATE cases CASCADE")]
    [InlineData("UPDATE case_notes SET body = 'edited'")]
    [InlineData("DELETE FROM case_notes")]
    [InlineData("DELETE FROM case_items")]
    [InlineData("TRUNCATE case_items")]
    [InlineData("UPDATE case_items SET note = 'edited'")]
    [InlineData("UPDATE case_items SET subject_id = gen_random_uuid()")]
    public async Task TheDatabaseRefusesEveryChangeToReviewAndCaseHistory(string sql)
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();
        await DecideAsync(client, world.TrackA, "Confirmed", "Unreviewed");
        var caseId = await CreateCaseAsync(client, "Gate");
        await AddItemAsync(client, caseId, "Track", world.TrackA, "first");
        using (await client.PostAsJsonAsync($"/api/cases/{caseId}/notes", new { body = "seen twice" })) { }

        await using var connection = new NpgsqlConnection(factory.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        var exception = await Assert.ThrowsAsync<PostgresException>(() => command.ExecuteNonQueryAsync());
        Assert.Equal(PostgresErrorCodes.ObjectNotInPrerequisiteState, exception.SqlState);
    }

    [Fact]
    public async Task ARemovedCaseItemCannotBeRestoredOrRemovedAgainInTheDatabase()
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();
        var caseId = await CreateCaseAsync(client, "Gate");
        var itemId = await AddItemAsync(client, caseId, "Track", world.TrackA, null);
        using (await client.PostAsJsonAsync($"/api/cases/{caseId}/items/{itemId}/remove", new { note = "wrong clip" })) { }

        await using var connection = new NpgsqlConnection(factory.ConnectionString);
        await connection.OpenAsync();
        foreach (var sql in new[]
                 {
                     "UPDATE case_items SET removed_at_utc = NULL, removed_by_operator_id = NULL, removed_by_display_name = NULL, " +
                     "removed_by_identity_source = NULL, removed_audit_entry_id = NULL, removal_note = NULL",
                     "UPDATE case_items SET removal_note = 'again'",
                 })
        {
            await using var command = new NpgsqlCommand(sql, connection);
            var exception = await Assert.ThrowsAsync<PostgresException>(() => command.ExecuteNonQueryAsync());
            Assert.Equal(PostgresErrorCodes.ObjectNotInPrerequisiteState, exception.SqlState);
        }
    }

    // --- Cases -----------------------------------------------------------------------------------

    [Fact]
    public async Task CasesCollectItemsWithNotesRecordRemovalAndNeverWriteIdentityOrReview()
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();
        var caseId = await CreateCaseAsync(client, "Gate incident 31 Oct");

        var first = await AddItemAsync(client, caseId, "Track", world.TrackA, "arrives 09:01");
        await AddItemAsync(client, caseId, "Track", world.TrackB, "leaves 09:05");
        using var duplicate = await client.PostAsJsonAsync($"/api/cases/{caseId}/items", new { kind = "Track", subjectId = world.TrackA });
        await AssertProblemAsync(duplicate, HttpStatusCode.Conflict, "case_item_already_present");
        using var missing = await client.PostAsJsonAsync($"/api/cases/{caseId}/items", new { kind = "AnalyticEvent", subjectId = Guid.CreateVersion7() });
        await AssertProblemAsync(missing, HttpStatusCode.NotFound, "case_subject_not_found");
        using var unknownCase = await client.PostAsJsonAsync($"/api/cases/{Guid.CreateVersion7()}/items", new { kind = "Track", subjectId = world.TrackA });
        await AssertProblemAsync(unknownCase, HttpStatusCode.NotFound, "case_not_found");

        _clock.Now = Start.AddMinutes(3);
        using var removed = await client.PostAsJsonAsync($"/api/cases/{caseId}/items/{first}/remove", new { note = "different person" });
        Assert.Equal(HttpStatusCode.OK, removed.StatusCode);
        using var again = await client.PostAsJsonAsync($"/api/cases/{caseId}/items/{first}/remove", new { note = "x" });
        await AssertProblemAsync(again, HttpStatusCode.Conflict, "case_item_already_removed");
        var readded = await AddItemAsync(client, caseId, "Track", world.TrackA, "it was the same clip after all");
        Assert.NotEqual(first, readded);
        using var note = await client.PostAsJsonAsync($"/api/cases/{caseId}/notes", new { body = "Reviewed with the duty officer." });
        Assert.Equal(HttpStatusCode.Created, note.StatusCode);

        using var detail = JsonDocument.Parse(await client.GetStringAsync($"/api/cases/{caseId}"));
        Assert.Contains("not asserted to show the same person or vehicle", detail.RootElement.GetProperty("statement").GetString(),
            StringComparison.Ordinal);
        var items = detail.RootElement.GetProperty("items").EnumerateArray().ToList();
        Assert.Equal(3, items.Count);
        var removedItem = items.Single(x => x.GetProperty("itemId").GetGuid() == first);
        Assert.Equal("different person", removedItem.GetProperty("removalNote").GetString());
        Assert.Equal(Start.AddMinutes(3), removedItem.GetProperty("removedBy").GetProperty("atUtc").GetDateTimeOffset());
        Assert.True(items.All(x => x.GetProperty("subject").GetProperty("available").GetBoolean()));
        Assert.Equal(2, detail.RootElement.GetProperty("case").GetProperty("activeItemCount").GetInt32());
        Assert.Single(detail.RootElement.GetProperty("notes").EnumerateArray());

        using var holding = JsonDocument.Parse(await client.GetStringAsync($"/api/cases?subjectKind=Track&subjectId={world.TrackB}"));
        Assert.Equal(caseId, Assert.Single(holding.RootElement.GetProperty("cases").EnumerateArray()).GetProperty("caseId").GetGuid());

        await using var db = Db(factory);
        // Entries recorded at one server instant have no defined order between them, so compare the set of actions.
        var actions = (await db.AuditEntries.Select(x => x.Action).ToListAsync()).Order(StringComparer.Ordinal).ToList();
        Assert.Equal(["cases.created", "cases.item-added", "cases.item-added", "cases.item-added", "cases.item-removed", "cases.note-added"], actions);
        Assert.True(await db.AuditEntries.AllAsync(x => x.SubjectType == "case" && x.SubjectId == caseId.ToString("D")));
        // No path writes identity: cases never touch Entity membership, identity or review status.
        Assert.True(await db.Tracks.AllAsync(x => x.EntityId == null && x.ReviewStatus == ReviewStatus.Unreviewed));
        Assert.Equal(0, await db.Entities.CountAsync());
    }

    [Fact]
    public async Task ACaseNeedsATitle()
    {
        using var factory = await CreateAsync();
        await SeedAsync(factory);
        using var client = factory.CreateClient();

        using var blank = await client.PostAsJsonAsync("/api/cases", new { title = "   " });
        using var tooLong = await client.PostAsJsonAsync("/api/cases", new { title = new string('t', 201) });

        await AssertProblemAsync(blank, HttpStatusCode.BadRequest, "case_title_invalid");
        await AssertProblemAsync(tooLong, HttpStatusCode.BadRequest, "case_title_invalid");
        await using var db = Db(factory);
        Assert.Equal(0, await db.AuditEntries.CountAsync());
    }

    // --- Audit read surface ----------------------------------------------------------------------

    [Fact]
    public async Task TheAuditSurfaceFiltersBySubjectsAndPagesNewestFirst()
    {
        using var factory = await CreateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();
        await DecideAsync(client, world.TrackA, "Confirmed", "Unreviewed");
        _clock.Now = Start.AddMinutes(1);
        await DecideAsync(client, world.TrackB, "Rejected", "Unreviewed");
        _clock.Now = Start.AddMinutes(2);
        await DecideAsync(client, world.TrackA, "Rejected", "Confirmed");
        _clock.Now = Start.AddMinutes(3);
        var caseId = await CreateCaseAsync(client, "Gate");

        using var trackA = JsonDocument.Parse(await client.GetStringAsync($"/api/audit?subject=track:{world.TrackA}"));
        var aEntries = trackA.RootElement.GetProperty("items").EnumerateArray().ToList();
        Assert.Equal(2, aEntries.Count);
        Assert.True(aEntries[0].GetProperty("recordedAtUtc").GetDateTimeOffset() > aEntries[1].GetProperty("recordedAtUtc").GetDateTimeOffset());
        Assert.Matches("^[0-9a-f]{64}$", aEntries[0].GetProperty("payloadSha256").GetString());
        Assert.Equal("development-unattributed", aEntries[0].GetProperty("identitySource").GetString());

        using var both = JsonDocument.Parse(await client.GetStringAsync($"/api/audit?subject=track:{world.TrackA}&subject=case:{caseId}&limit=2"));
        Assert.Equal(2, both.RootElement.GetProperty("items").GetArrayLength());
        Assert.Equal("cases.created", both.RootElement.GetProperty("items")[0].GetProperty("action").GetString());
        var next = both.RootElement.GetProperty("nextCursor").GetString();
        using var rest = JsonDocument.Parse(await client.GetStringAsync(
            $"/api/audit?subject=track:{world.TrackA}&subject=case:{caseId}&limit=2&cursor={next}"));
        Assert.Single(rest.RootElement.GetProperty("items").EnumerateArray());

        using var byAction = JsonDocument.Parse(await client.GetStringAsync("/api/audit?action=cases.created"));
        Assert.Single(byAction.RootElement.GetProperty("items").EnumerateArray());
        using var bad = await client.GetAsync("/api/audit?subject=track");
        await AssertProblemAsync(bad, HttpStatusCode.BadRequest, "audit_query_invalid");
    }

    // --- Helpers ---------------------------------------------------------------------------------

    private sealed record World(Guid RunA, Guid RunB, Guid EarlierRunTrack, Guid TrackA, Guid TrackB);

    private async Task<ApiTestFactory> CreateAsync(string identityMode = "development-unattributed")
    {
        var metadata = Path.Combine(_root, $"release-{Guid.NewGuid():N}.json");
        await File.WriteAllTextAsync(metadata, $$"""
            {
              "schemaVersion": "mavi-poc-release-metadata-v1",
              "profile": "poc-single-host",
              "productionQualified": false,
              "evidenceClass": "Development",
              "identityMode": "windows-negotiate",
              "application": { "revision": "{{new string('b', 40)}}" },
              "packs": []
            }
            """);
        var factory = new ApiTestFactory
        {
            Clock = _clock,
            AdditionalConfiguration = new Dictionary<string, string?>
            {
                ["Identity:Mode"] = identityMode,
                ["Deployment:Profile"] = DeploymentProfiles.PocSingleHost,
                ["Deployment:ReleaseMetadataPath"] = metadata,
            },
        };
        await factory.ResetAndMigrateAsync();
        return factory;
    }

    /// <summary>One camera, one video, two completed runs: run A (earlier, one Track) and run B (latest, two Tracks).</summary>
    private static async Task<World> SeedAsync(ApiTestFactory factory)
    {
        await using var db = Db(factory);
        var recordingStart = Start.AddHours(-1);
        var camera = Camera.Create("CAM-RV-01", "Review Camera", "UTC");
        var source = Artifact.Create(ArtifactType.SourceVideo, $"source/CAM-RV-01/{Guid.CreateVersion7()}.mp4", "video/mp4", 1, new string('c', 64));
        var video = VideoAsset.Create(camera.Id, source.Id, "review.mp4", recordingStart, 600_000, 25, 1, 640, 360, "h264", TimestampSource.Manual, 1.0);
        db.AddRange(camera, source, video);
        var runA = await CompletedRunAsync(db, video.Id, Start.AddMinutes(-30));
        var runB = await CompletedRunAsync(db, video.Id, Start.AddMinutes(-10));
        var earlier = Track.Create(runA.Id, video.Id, 1, ObjectClass.Person, 1_000, 9_000, recordingStart, 5, 0.7, 0.9, Start.AddMinutes(-30));
        var a = Track.Create(runB.Id, video.Id, 1, ObjectClass.Person, 1_000, 9_000, recordingStart, 5, 0.7, 0.9, Start.AddMinutes(-10));
        var b = Track.Create(runB.Id, video.Id, 2, ObjectClass.Vehicle, 20_000, 40_000, recordingStart, 9, 0.8, 0.95, Start.AddMinutes(-10));
        db.AddRange(earlier, a, b);
        await db.SaveChangesAsync();
        return new World(runA.Id, runB.Id, earlier.Id, a.Id, b.Id);
    }

    private static async Task<ProcessingRun> CompletedRunAsync(MaviDbContext db, Guid videoId, DateTimeOffset completedAtUtc)
    {
        var run = ProcessingRun.Create(videoId, "phase1-detection-tracking-v1", "{}", completedAtUtc.AddMinutes(-4));
        run.MarkRunning("worker-01", completedAtUtc.AddMinutes(-3));
        run.MarkCompleted(250, 1, 5_000, completedAtUtc);
        run.AssignCompletionVisibilitySequence(await db.Database
            .SqlQueryRaw<long>("SELECT nextval('processing_visibility_sequence') AS \"Value\"").SingleAsync());
        db.AddRange(run, VisionJob.Create(run.Id, "phase1-detection-tracking", completedAtUtc.AddMinutes(-4)));
        return run;
    }

    private static async Task DecideAsync(HttpClient client, Guid trackId, string decision, string expected)
    {
        using var response = await client.PostAsJsonAsync($"/api/tracks/{trackId}/review",
            new { decisionId = Guid.CreateVersion7(), decision, expectedReviewStatus = expected });
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    private static async Task<Guid> CreateCaseAsync(HttpClient client, string title)
    {
        using var response = await client.PostAsJsonAsync("/api/cases", new { title, purpose = "PoC review" });
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return body.RootElement.GetProperty("caseId").GetGuid();
    }

    private static async Task<Guid> AddItemAsync(HttpClient client, Guid caseId, string kind, Guid subjectId, string? note)
    {
        using var response = await client.PostAsJsonAsync($"/api/cases/{caseId}/items", new { kind, subjectId, note });
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return body.RootElement.GetProperty("itemId").GetGuid();
    }

    /// <summary>Review plan §5: every Track's status equals its latest decision's result, or Unreviewed with none.</summary>
    private static async Task AssertProjectionInvariantAsync(ApiTestFactory factory)
    {
        await using var connection = new NpgsqlConnection(factory.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("""
            SELECT count(*) FROM tracks t
            WHERE t.review_status <> COALESCE(
                (SELECT d.resulting_status FROM track_review_decisions d WHERE d.track_id = t.id ORDER BY d.sequence DESC LIMIT 1),
                'Unreviewed')
            """, connection);
        Assert.Equal(0L, (long)(await command.ExecuteScalarAsync())!);
    }

    private static async Task AssertProblemAsync(HttpResponseMessage response, HttpStatusCode status, string code)
    {
        Assert.Equal(status, response.StatusCode);
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal(code, body.RootElement.GetProperty("code").GetString());
    }

    private static MaviDbContext Db(ApiTestFactory factory) =>
        new(new DbContextOptionsBuilder<MaviDbContext>().UseNpgsql(factory.ConnectionString, options => options.UseVector()).Options);

    private sealed class MutableClock(DateTimeOffset now) : TimeProvider
    {
        public DateTimeOffset Now { get; set; } = now;
        public override DateTimeOffset GetUtcNow() => Now;
    }
}
