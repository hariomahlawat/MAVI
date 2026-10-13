using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Api.Middleware;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Plates;
using Mavi.Domain.Plates;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace Mavi.IntegrationTests;

/// <summary>
/// <c>GET /api/tracks?plateText=…</c> and the detail's <c>plates</c> block over the real host and a real
/// database (Stage 4 PR-4, plan §5.4, §5.5): literal match kinds, normalisation, coverage in every readiness
/// bucket, Person exclusion, AND-combination with the ordinary filters, v4 pagination, limits and log
/// redaction.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class TrackPlateSearchApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 10, 13, 12, 0, 0, TimeSpan.Zero);

    /// <summary>
    /// The deterministic fixture corpus: one run of a Person and five Vehicle Tracks whose texts exercise
    /// consistent, conflicting, unreadable, confusable-lookalike and unavailable cases.
    /// </summary>
    private sealed record Corpus(SeededRun Run, Guid Consistent, Guid Conflicting, Guid Unreadable, Guid Lookalike, Guid Unavailable, Guid Person,
        Guid AnalysisId)
    {
        /// <summary>Every searchable text per Track, as the fixture seeded it: the oracle for precision and recall.</summary>
        public IReadOnlyDictionary<Guid, string[]> Texts { get; } = new Dictionary<Guid, string[]>
        {
            [Consistent] = ["KA01AB1234"],
            [Conflicting] = ["KA01AB1235", "MH12DE4321"],
            [Unreadable] = [],
            [Lookalike] = ["KAO1AB1234"],
            [Unavailable] = [],
        };
    }

    private static async Task<Corpus> SeedCorpusAsync(PlateApiHost host)
    {
        var run = await host.World.SeedRunAsync(persons: 1, vehicles: 5, observationsPerTrack: 2);
        await TrackPlateSearchWorld.AttachRepresentativesAsync(host.World.Read, run);
        var (person, consistent, conflicting, unreadable, lookalike, unavailable) =
            (run.Track(0), run.Track(1), run.Track(2), run.Track(3), run.Track(4), run.Track(5));
        var identity = TrackPlateSearchWorld.IdentityA(host.Factory.Services.GetRequiredService<IPlateRelease>());
        var analysisId = await TrackPlateSearchWorld.PublishAsync(host.World.Read, Now, run.RunId, identity,
        [
            SeedPlateTrack.Analysed(consistent.TrackId,
                new SeedPlate(consistent.Observations[0].ObservationId, 0.9, ("KA 01 AB 1234", 0.97), ("KA01AB1284", 0.4)),
                new SeedPlate(consistent.Observations[1].ObservationId, 0.8, ("KA01AB1234", 0.9))),
            SeedPlateTrack.Analysed(conflicting.TrackId,
                new SeedPlate(conflicting.Observations[0].ObservationId, 0.9, ("KA01AB1235", 0.8)),
                new SeedPlate(conflicting.Observations[1].ObservationId, 0.9, ("MH12\nDE4321", 0.85))),
            SeedPlateTrack.Analysed(unreadable.TrackId, new SeedPlate(unreadable.Observations[0].ObservationId, 0.5)),
            SeedPlateTrack.Analysed(lookalike.TrackId, new SeedPlate(lookalike.Observations[0].ObservationId, 0.9, ("KAO1AB1234", 0.88))),
            SeedPlateTrack.Unavailable(unavailable.TrackId, "evidence_missing"),
        ]);
        return new Corpus(run, consistent.TrackId, conflicting.TrackId, unreadable.TrackId, lookalike.TrackId, unavailable.TrackId,
            person.TrackId, analysisId);
    }

    private static async Task<JsonElement> SearchAsync(PlateApiHost host, string query)
    {
        using var response = await host.Client.GetAsync("/api/tracks?" + query);
        Assert.True(response.StatusCode == HttpStatusCode.OK, $"{query}: {(int)response.StatusCode} {await response.Content.ReadAsStringAsync()}");
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    private static Guid[] Ids(JsonElement page) =>
        page.GetProperty("items").EnumerateArray().Select(item => item.GetProperty("id").GetGuid()).ToArray();

    // --- Match semantics -----------------------------------------------------------------------------

    [Fact]
    public async Task EveryMatchKindIsLiteralAndExplainsItsRow()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);
        var corpus = await SeedCorpusAsync(host);

        var contains = await SearchAsync(host, "plateText=KA01");
        Assert.Equal(new[] { corpus.Consistent, corpus.Conflicting }.Order(), Ids(contains).Order());
        var explained = contains.GetProperty("items").EnumerateArray()
            .ToDictionary(item => item.GetProperty("id").GetGuid(), item => item.GetProperty("plate"));
        Assert.Equal("KA01AB1234", explained[corpus.Consistent].GetProperty("matchedText").GetString());
        Assert.Equal("contains", explained[corpus.Consistent].GetProperty("matchKind").GetString());
        Assert.Equal(2, explained[corpus.Consistent].GetProperty("supportCount").GetInt32());
        Assert.Equal(2, explained[corpus.Consistent].GetProperty("plateObservationCount").GetInt32());
        Assert.Equal(1, explained[corpus.Consistent].GetProperty("distinctTextCount").GetInt32());
        Assert.Equal(0.97, explained[corpus.Consistent].GetProperty("maxConfidence").GetDouble());
        Assert.Equal("KA01AB1235", explained[corpus.Conflicting].GetProperty("matchedText").GetString());
        Assert.Equal(2, explained[corpus.Conflicting].GetProperty("distinctTextCount").GetInt32());

        // Separators and case are normalised; the match mode is honoured.
        Assert.Equal(new[] { corpus.Consistent, corpus.Conflicting }.Order(), Ids(await SearchAsync(host, "plateText=ka-01-ab&plateMatch=prefix")).Order());
        Assert.Equal([corpus.Consistent], Ids(await SearchAsync(host, "plateText=KA01AB1234&plateMatch=exact")));
        Assert.Empty(Ids(await SearchAsync(host, "plateText=AB12&plateMatch=prefix")));
        Assert.Empty(Ids(await SearchAsync(host, "plateText=KA01AB123&plateMatch=exact")));
        // A text of a two-line reading is searchable as one; the conflict's other text explains its own match.
        var other = await SearchAsync(host, "plateText=DE4321");
        Assert.Equal([corpus.Conflicting], Ids(other));
        Assert.Equal("MH12DE4321", other.GetProperty("items")[0].GetProperty("plate").GetProperty("matchedText").GetString());
        // No confusable expansion either way: KA01 never finds KAO1, and KAO1 finds only it.
        Assert.Equal([corpus.Lookalike], Ids(await SearchAsync(host, "plateText=KAO1")));
        // A rank-1 reading is not a Track text under the v1 summary policy.
        Assert.Empty(Ids(await SearchAsync(host, "plateText=KA01AB1284")));
    }

    [Fact]
    public async Task TheLiteralMatcherIsExactOnTheFixtureCorpus()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);
        var corpus = await SeedCorpusAsync(host);
        string[] texts = ["KA0", "KA01", "A01", "1234", "AB123", "KAO", "MH12", "DE4321", "4321", "KA01AB1235", "ZZZ", "B12", "O1A"];

        foreach (var text in texts)
        {
            foreach (var match in new[] { TrackPlateMatch.Contains, TrackPlateMatch.Prefix, TrackPlateMatch.Exact })
            {
                var query = new TrackPlateQuery(text, match);
                var expected = corpus.Texts
                    .Where(pair => pair.Value.Any(stored => TrackPlateQueryRules.Matches(query, stored)))
                    .Select(pair => pair.Key)
                    .Order()
                    .ToArray();
                var actual = Ids(await SearchAsync(host, $"plateText={text}&plateMatch={TrackPlateQueryRules.ToWire(match)}")).Order().ToArray();
                // Precision and recall are 1.0 by construction: the returned set is the oracle's set.
                Assert.True(expected.SequenceEqual(actual), $"{text} {match}");
            }
        }
    }

    [Fact]
    public async Task PersonTracksAreNeverSearchedOrCountedAndAPersonClassIsRefused()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);
        var corpus = await SeedCorpusAsync(host);

        var page = await SearchAsync(host, "plateText=KA01");
        Assert.DoesNotContain(corpus.Person, Ids(page));
        Assert.All(page.GetProperty("items").EnumerateArray(), item => Assert.Equal("Vehicle", item.GetProperty("objectClass").GetString()));
        Assert.Equal(5, page.GetProperty("plateCoverage").GetProperty("vehicleTracksInScope").GetInt32());

        using var person = await host.Client.GetAsync("/api/tracks?objectClass=Person&plateText=KA01");
        Assert.Equal(HttpStatusCode.BadRequest, person.StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await host.Client.GetAsync("/api/tracks?objectClass=Vehicle&plateText=KA01")).StatusCode);
    }

    [Theory]
    [InlineData("plateMatch=exact")]
    [InlineData("plateText=KA")]
    [InlineData("plateText=K-A")]
    [InlineData("plateText=ABCDEFGHIJ123456")]
    [InlineData("plateText=KA_01")]
    [InlineData("plateText=%25KA01")]
    [InlineData("plateText=KA01&plateMatch=fuzzy")]
    [InlineData("plateText=KA01&plateMatch=Exact")]
    [InlineData("plateText=KA01&plateText=KA02")]
    [InlineData("plateText=KA01&plateMatch=exact&plateMatch=prefix")]
    [InlineData("plateText=%20%20%20")]
    [InlineData("plateText=")]
    [InlineData("plateText=KA01&objectClass=Person")]
    [InlineData("plateText=KA01&cursor=bm90LWEtY3Vyc29y")]
    public async Task AMalformedPlateQueryIsA400(string query)
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);

        using var response = await host.Client.GetAsync("/api/tracks?" + query);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        var problem = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal("track_search_invalid", problem.GetProperty("code").GetString());
    }

    [Fact]
    public async Task ThePlatePredicateCombinesWithTheOrdinaryFiltersByAnd()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);
        var corpus = await SeedCorpusAsync(host);
        var otherRun = await host.World.SeedRunAsync(persons: 0, vehicles: 1);
        var identity = TrackPlateSearchWorld.IdentityA(host.Factory.Services.GetRequiredService<IPlateRelease>());
        await TrackPlateSearchWorld.PublishAsync(host.World.Read, Now, otherRun.RunId, identity,
            [SeedPlateTrack.Analysed(otherRun.Track(0).TrackId, new SeedPlate(otherRun.Track(0).Observations[0].ObservationId, 0.9, ("KA01ZZ0001", 0.9)))]);

        Assert.Equal(3, Ids(await SearchAsync(host, "plateText=KA01")).Length);
        Assert.Equal(new[] { corpus.Consistent, corpus.Conflicting }.Order(),
            Ids(await SearchAsync(host, $"plateText=KA01&processingRunId={corpus.Run.RunId}")).Order());
        Assert.Equal([otherRun.Track(0).TrackId], Ids(await SearchAsync(host, $"plateText=KA01&processingRunId={otherRun.RunId}")));
        Assert.Empty(Ids(await SearchAsync(host, "plateText=KA01&minimumConfidence=0.95")));
        Assert.Empty(Ids(await SearchAsync(host, $"plateText=KA01&fromUtc={Uri.EscapeDataString(Now.AddHours(1).ToString("O"))}")));
        // The coverage denominator follows the ordinary filters too.
        var scoped = await SearchAsync(host, $"plateText=KA01&processingRunId={otherRun.RunId}");
        Assert.Equal(1, scoped.GetProperty("plateCoverage").GetProperty("vehicleTracksInScope").GetInt32());
    }

    // --- Coverage ------------------------------------------------------------------------------------

    [Fact]
    public async Task CoverageCountsVehicleTracksInEveryReadinessBucketAndIsReturnedForAnEmptyPage()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);
        var identity = TrackPlateSearchWorld.IdentityA(host.Factory.Services.GetRequiredService<IPlateRelease>());
        var ready = await host.World.SeedRunAsync(persons: 2, vehicles: 2);
        var pending = await host.World.SeedRunAsync(persons: 0, vehicles: 3);
        var queued = await host.World.SeedRunAsync(persons: 0, vehicles: 1);
        var failed = await host.World.SeedRunAsync(persons: 1, vehicles: 1);
        var stale = await host.World.SeedRunAsync(persons: 0, vehicles: 4);
        await TrackPlateSearchWorld.PublishAsync(host.World.Read, Now, ready.RunId, identity,
            [SeedPlateTrack.Analysed(ready.Track(2).TrackId), SeedPlateTrack.Analysed(ready.Track(3).TrackId)]);
        await TrackPlateSearchWorld.QueueAsync(host.World.Read, Now, queued.RunId, identity);
        await TrackPlateSearchWorld.QueueAsync(host.World.Read, Now, failed.RunId, identity, failed: true);
        await TrackPlateSearchWorld.PublishAsync(host.World.Read, Now, stale.RunId, TrackPlateSearchWorld.Obsolete(identity),
            [.. stale.Tracks.Select(track => SeedPlateTrack.Analysed(track.TrackId))], preferred: false);

        var page = await SearchAsync(host, "plateText=ZZZ999");

        Assert.Empty(Ids(page));
        Assert.Equal(JsonValueKind.Null, page.GetProperty("nextCursor").ValueKind);
        var coverage = page.GetProperty("plateCoverage");
        Assert.Equal(host.PreferredFingerprint, coverage.GetProperty("identityFingerprint").GetString());
        Assert.Equal(11, coverage.GetProperty("vehicleTracksInScope").GetInt32());
        Assert.Equal(2, coverage.GetProperty("ready").GetInt32());
        Assert.Equal(4, coverage.GetProperty("pending").GetInt32());
        Assert.Equal(1, coverage.GetProperty("failed").GetInt32());
        Assert.Equal(4, coverage.GetProperty("stale").GetInt32());
        Assert.Equal(0, coverage.GetProperty("notConfigured").GetInt32());
        // An ordinary search is untouched by Stage 4: no plate member anywhere.
        var ordinary = await SearchAsync(host, "objectClass=Vehicle");
        Assert.False(ordinary.TryGetProperty("plateCoverage", out _));
        Assert.All(ordinary.GetProperty("items").EnumerateArray(), item => Assert.False(item.TryGetProperty("plate", out _)));
        Assert.Equal(11, Ids(ordinary).Length);
    }

    [Fact]
    public async Task WithoutAPlateBindingEveryVehicleTrackIsNotConfigured()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now, configured: false);
        var run = await host.World.SeedRunAsync(persons: 1, vehicles: 3);
        await TrackPlateSearchWorld.AttachRepresentativesAsync(host.World.Read, run);

        var page = await SearchAsync(host, "plateText=KA01");

        Assert.Empty(Ids(page));
        var coverage = page.GetProperty("plateCoverage");
        Assert.Equal(JsonValueKind.Null, coverage.GetProperty("identityFingerprint").ValueKind);
        Assert.Equal(3, coverage.GetProperty("vehicleTracksInScope").GetInt32());
        Assert.Equal(3, coverage.GetProperty("notConfigured").GetInt32());

        var detail = await host.Client.GetFromJsonAsync<JsonElement>($"/api/tracks/{run.Track(1).TrackId}");
        Assert.Equal("NotConfigured", detail.GetProperty("plates").GetProperty("readiness").GetString());
        var personDetail = await host.Client.GetFromJsonAsync<JsonElement>($"/api/tracks/{run.Track(0).TrackId}");
        Assert.False(personDetail.TryGetProperty("plates", out _));
    }

    // --- Pagination ----------------------------------------------------------------------------------

    [Fact]
    public async Task PagesAreDisjointOrderedAndStableAcrossASupersessionAndANewRun()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);
        var identity = TrackPlateSearchWorld.IdentityA(host.Factory.Services.GetRequiredService<IPlateRelease>());
        var run = await host.World.SeedRunAsync(persons: 0, vehicles: 5);
        var analysisId = await TrackPlateSearchWorld.PublishAsync(host.World.Read, Now, run.RunId, identity,
        [
            .. run.Tracks.Select((track, index) => SeedPlateTrack.Analysed(track.TrackId,
                new SeedPlate(track.Observations[0].ObservationId, 0.9, ($"KA01AB{index:0000}", 0.9)))),
        ]);

        var first = await SearchAsync(host, "plateText=KA01&limit=2");
        var cursor = first.GetProperty("nextCursor").GetString()!;
        var coverage = first.GetProperty("plateCoverage").GetRawText();

        // Mid-pagination: the analysis is superseded by a newer identity's, whose facts match nothing,
        // and a new run with a matching plate becomes visible. Neither changes what the open set means.
        await TrackPlateSearchWorld.SupersedeAsync(host.World.Read, analysisId);
        await TrackPlateSearchWorld.PublishAsync(host.World.Read, Now, run.RunId, TrackPlateSearchWorld.Obsolete(identity),
            [.. run.Tracks.Select(track => SeedPlateTrack.Analysed(track.TrackId))]);
        var late = await host.World.SeedRunAsync(persons: 0, vehicles: 1);
        await TrackPlateSearchWorld.PublishAsync(host.World.Read, Now, late.RunId, identity,
            [SeedPlateTrack.Analysed(late.Track(0).TrackId, new SeedPlate(late.Track(0).Observations[0].ObservationId, 0.9, ("KA01XX0001", 0.9)))]);

        var seen = Ids(first).ToList();
        while (cursor is not null)
        {
            var next = await SearchAsync(host, $"plateText=KA01&limit=2&cursor={Uri.EscapeDataString(cursor)}");
            Assert.Equal(coverage, next.GetProperty("plateCoverage").GetRawText());
            seen.AddRange(Ids(next));
            cursor = next.GetProperty("nextCursor").ValueKind == JsonValueKind.String ? next.GetProperty("nextCursor").GetString() : null;
        }

        Assert.Equal(run.Tracks.Select(track => track.TrackId).OrderDescending(), seen);
        Assert.DoesNotContain(late.Track(0).TrackId, seen);

        // A cursor of one query is refused by another.
        var refused = await host.Client.GetAsync(
            $"/api/tracks?plateText=KA02&limit=2&cursor={Uri.EscapeDataString(first.GetProperty("nextCursor").GetString()!)}");
        Assert.Equal(HttpStatusCode.BadRequest, refused.StatusCode);
    }

    [Fact]
    public async Task TheLimitBoundsTheFirstPageAndOrderingIsTimeDescending()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);
        var corpus = await SeedCorpusAsync(host);

        var page = await SearchAsync(host, "plateText=KA01&limit=1");
        Assert.Single(Ids(page));
        Assert.Equal(new[] { corpus.Consistent, corpus.Conflicting }.Max(), Ids(page)[0]);
        Assert.Equal(JsonValueKind.String, page.GetProperty("nextCursor").ValueKind);
        Assert.Equal(HttpStatusCode.BadRequest, (await host.Client.GetAsync("/api/tracks?plateText=KA01&limit=101")).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await host.Client.GetAsync("/api/tracks?plateText=KA01&limit=0")).StatusCode);
    }

    // --- Detail --------------------------------------------------------------------------------------

    [Fact]
    public async Task AVehicleDetailCarriesItsPlateEvidenceAndAPersonDetailOmitsIt()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);
        var corpus = await SeedCorpusAsync(host);

        var consistent = (await host.Client.GetFromJsonAsync<JsonElement>($"/api/tracks/{corpus.Consistent}")).GetProperty("plates");
        Assert.Equal("Ready", consistent.GetProperty("readiness").GetString());
        Assert.Equal("Analysed", consistent.GetProperty("trackOutcome").GetString());
        Assert.Equal("consistent", consistent.GetProperty("agreement").GetString());
        var text = Assert.Single(consistent.GetProperty("texts").EnumerateArray());
        Assert.Equal("KA01AB1234", text.GetProperty("normalisedText").GetString());
        Assert.Equal(2, text.GetProperty("supportCount").GetInt32());
        var observations = consistent.GetProperty("observations").EnumerateArray().ToArray();
        Assert.Equal(2, observations.Length);
        Assert.Equal(corpus.Run.Track(1).Observations[0].ObservationId, observations[0].GetProperty("sourceObservationId").GetGuid());
        Assert.Equal("Representative", observations[0].GetProperty("role").GetString());
        Assert.Equal("NearView", observations[1].GetProperty("role").GetString());
        Assert.Equal(400, observations[1].GetProperty("offsetMs").GetInt64());
        var readings = observations[0].GetProperty("readings").EnumerateArray().ToArray();
        Assert.Equal("KA 01 AB 1234", readings[0].GetProperty("rawText").GetString());
        Assert.Equal("KA01AB1234", readings[0].GetProperty("normalisedText").GetString());
        Assert.Equal("ok", readings[0].GetProperty("normalisationOutcome").GetString());
        Assert.Equal("in-standard", readings[0].GetProperty("formatClass").GetString());
        Assert.Equal(1, readings[1].GetProperty("rank").GetInt32());
        var provenance = consistent.GetProperty("provenance");
        Assert.Equal(corpus.AnalysisId, provenance.GetProperty("analysisId").GetGuid());
        Assert.Equal(PlateReleaseFixture.DetectorPack, provenance.GetProperty("plateDetectorModelPackId").GetString());
        Assert.Equal(PlateReleaseFixture.OcrPackA, provenance.GetProperty("ocrModelPackId").GetString());
        Assert.Equal("mavi-plate-normalisation-v1", provenance.GetProperty("normalisation").GetProperty("id").GetString());

        var conflicting = (await host.Client.GetFromJsonAsync<JsonElement>($"/api/tracks/{corpus.Conflicting}")).GetProperty("plates");
        Assert.Equal("conflicting", conflicting.GetProperty("agreement").GetString());
        Assert.Equal(2, conflicting.GetProperty("observations")[1].GetProperty("readings")[0].GetProperty("rawLineCount").GetInt32());

        var unreadable = (await host.Client.GetFromJsonAsync<JsonElement>($"/api/tracks/{corpus.Unreadable}")).GetProperty("plates");
        Assert.Equal("none", unreadable.GetProperty("agreement").GetString());
        Assert.Equal("Unreadable", unreadable.GetProperty("observations")[0].GetProperty("outcome").GetString());
        Assert.Empty(unreadable.GetProperty("observations")[0].GetProperty("readings").EnumerateArray());

        var unavailable = (await host.Client.GetFromJsonAsync<JsonElement>($"/api/tracks/{corpus.Unavailable}")).GetProperty("plates");
        Assert.Equal("Unavailable", unavailable.GetProperty("trackOutcome").GetString());
        Assert.Equal("evidence_missing", unavailable.GetProperty("unavailableReason").GetString());
        Assert.False(unavailable.TryGetProperty("agreement", out _));

        var person = await host.Client.GetFromJsonAsync<JsonElement>($"/api/tracks/{corpus.Person}");
        Assert.False(person.TryGetProperty("plates", out _));
    }

    /// <summary>
    /// The impossible state (owner decision 2026-10-13): the run's default analysis is Ready but has no
    /// outcome row for this Vehicle Track. The response keeps the frozen shape — an Unavailable outcome with
    /// no reason, no agreement, empty texts and observations, the provenance — and the server logs a
    /// warning (event 1422) naming the analysis and the Track, never a plate text.
    /// </summary>
    [Fact]
    public async Task AReadyAnalysisWithoutTheTracksOutcomeKeepsTheShapeAndLogsAWarning()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);
        var identity = TrackPlateSearchWorld.IdentityA(host.Factory.Services.GetRequiredService<IPlateRelease>());
        var run = await host.World.SeedRunAsync(persons: 0, vehicles: 2);
        await TrackPlateSearchWorld.AttachRepresentativesAsync(host.World.Read, run);
        // The analysis publishes an outcome for the first Vehicle Track only. Written straight into the database:
        // PR-3's completion route refuses this state, so only a defect or a direct write could produce it, and
        // the warning is the defence in depth for that case.
        var analysisId = await TrackPlateSearchWorld.PublishAsync(host.World.Read, Now, run.RunId, identity,
            [SeedPlateTrack.Analysed(run.Track(0).TrackId,
                new SeedPlate(run.Track(0).Observations[0].ObservationId, 0.9, ("KA01AB1234", 0.9)))]);
        var orphan = run.Track(1).TrackId;
        var before = host.Logs.Entries.Count;

        var plates = (await host.Client.GetFromJsonAsync<JsonElement>($"/api/tracks/{orphan}")).GetProperty("plates");

        Assert.Equal(["readiness", "trackOutcome", "texts", "observations", "provenance"], plates.EnumerateObject().Select(member => member.Name));
        Assert.Equal("Ready", plates.GetProperty("readiness").GetString());
        Assert.Equal("Unavailable", plates.GetProperty("trackOutcome").GetString());
        Assert.Empty(plates.GetProperty("texts").EnumerateArray());
        Assert.Empty(plates.GetProperty("observations").EnumerateArray());
        Assert.Equal(analysisId, plates.GetProperty("provenance").GetProperty("analysisId").GetGuid());

        var warning = Assert.Single(host.Logs.Entries.Skip(before), entry => entry.EventId.Id == 1422);
        Assert.Equal(LogLevel.Warning, warning.Level);
        Assert.Equal("track_plate_outcome_missing", warning.EventId.Name);
        Assert.Contains(analysisId.ToString(), warning.Message, StringComparison.OrdinalIgnoreCase);
        Assert.Contains(orphan.ToString(), warning.Message, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("KA01AB1234", warning.Message, StringComparison.Ordinal);

        // A Track that has its outcome raises no warning.
        var countBefore = host.Logs.Entries.Count(entry => entry.EventId.Id == 1422);
        await host.Client.GetFromJsonAsync<JsonElement>($"/api/tracks/{run.Track(0).TrackId}");
        Assert.Equal(countBefore, host.Logs.Entries.Count(entry => entry.EventId.Id == 1422));
    }

    [Fact]
    public async Task PendingAndStaleVehicleDetailsCarryOnlyTheirReadiness()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);
        var identity = TrackPlateSearchWorld.IdentityA(host.Factory.Services.GetRequiredService<IPlateRelease>());
        var pending = await host.World.SeedRunAsync(persons: 0, vehicles: 1);
        var stale = await host.World.SeedRunAsync(persons: 0, vehicles: 1);
        await TrackPlateSearchWorld.AttachRepresentativesAsync(host.World.Read, pending);
        await TrackPlateSearchWorld.AttachRepresentativesAsync(host.World.Read, stale);
        await TrackPlateSearchWorld.PublishAsync(host.World.Read, Now, stale.RunId, TrackPlateSearchWorld.Obsolete(identity),
            [SeedPlateTrack.Analysed(stale.Track(0).TrackId, new SeedPlate(stale.Track(0).Observations[0].ObservationId, 0.9, ("KA01AB1234", 0.9)))],
            preferred: false);

        var pendingPlates = (await host.Client.GetFromJsonAsync<JsonElement>($"/api/tracks/{pending.Track(0).TrackId}")).GetProperty("plates");
        var stalePlates = (await host.Client.GetFromJsonAsync<JsonElement>($"/api/tracks/{stale.Track(0).TrackId}")).GetProperty("plates");

        Assert.Equal("Pending", pendingPlates.GetProperty("readiness").GetString());
        Assert.Equal("Stale", stalePlates.GetProperty("readiness").GetString());
        foreach (var plates in new[] { pendingPlates, stalePlates })
            Assert.Equal(["readiness", "texts", "observations"], plates.EnumerateObject().Select(member => member.Name));
        // An obsolete identity's text is not searchable under the preferred identity.
        Assert.Empty(Ids(await SearchAsync(host, "plateText=KA01AB1234&plateMatch=exact")));
    }

    // --- Privacy -------------------------------------------------------------------------------------

    [Fact]
    public async Task NoLogRecordOfAPlateSearchCarriesThePlateText()
    {
        // Every category at Trace, the framework's request logging and EF Core's command logging included.
        await using var host = await PlateApiHost.CreateAsync(fixture, Now, configuration: new Dictionary<string, string?>
        {
            ["Logging:LogLevel:Default"] = "Trace",
            ["Logging:LogLevel:Microsoft"] = "Trace",
            ["Logging:LogLevel:Microsoft.AspNetCore"] = "Trace",
            ["Logging:LogLevel:Microsoft.EntityFrameworkCore"] = "Trace",
        });
        var corpus = await SeedCorpusAsync(host);
        const string raw = "ka-01-ab";

        var first = await SearchAsync(host, $"plateText={raw}&plateMatch=prefix&limit=1");
        var cursor = first.GetProperty("nextCursor").GetString()!;
        await SearchAsync(host, $"plateText={raw}&plateMatch=prefix&limit=1&cursor={Uri.EscapeDataString(cursor)}");
        await host.Client.GetAsync("/api/tracks?plateText=K");
        await host.Client.GetAsync($"/api/tracks/{corpus.Consistent}");

        var entries = host.Logs.Entries;
        var plateSearches = entries.Where(entry => entry.EventId.Name == "track_plate_search").ToArray();
        Assert.Equal(2, plateSearches.Length);
        Assert.Contains(plateSearches, entry => entry.Message.Contains("prefix", StringComparison.Ordinal));
        foreach (var forbidden in new[] { raw, "KA01AB", "ka-01", "KA01AB1234", "KA 01 AB 1234", "MH12DE4321" })
        {
            var leaking = entries.Where(entry => entry.Message.Contains(forbidden, StringComparison.OrdinalIgnoreCase)).ToArray();
            Assert.True(leaking.Length == 0, $"'{forbidden}' was logged: {string.Join(" | ", leaking.Select(entry => $"[{entry.EventId}] {entry.Message}"))}");
        }

        Assert.Contains(entries, entry => entry.Level <= LogLevel.Debug);
        // The framework's raw-URL request lines are gone; the sanitised ones replace them.
        Assert.DoesNotContain(entries, entry => entry.Message.StartsWith("Request starting HTTP/", StringComparison.Ordinal));
        Assert.Contains(entries, entry => entry.EventId.Id == SafeRequestTelemetryMiddleware.RequestFinishedEventId);
    }

    /// <summary>
    /// The owner's request-telemetry contract (2026-10-13): a plate search with a cursor yields useful start
    /// and finish events — method, route template, status, duration, trace id and the two plate fields — and
    /// neither the plate value, the cursor value nor the raw query string appears in any captured record,
    /// at any level, in any category.
    /// </summary>
    [Fact]
    public async Task APlateSearchWithACursorYieldsSanitisedRequestTelemetryAndLeaksNoQueryValue()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now, configuration: new Dictionary<string, string?>
        {
            ["Logging:LogLevel:Default"] = "Trace",
            ["Logging:LogLevel:Microsoft"] = "Trace",
            ["Logging:LogLevel:Microsoft.AspNetCore"] = "Trace",
            ["Logging:LogLevel:Microsoft.AspNetCore.Hosting.Diagnostics"] = "Trace",
            ["Logging:LogLevel:Microsoft.EntityFrameworkCore"] = "Trace",
        });
        var identity = TrackPlateSearchWorld.IdentityA(host.Factory.Services.GetRequiredService<IPlateRelease>());
        var run = await host.World.SeedRunAsync(persons: 0, vehicles: 3);
        await TrackPlateSearchWorld.PublishAsync(host.World.Read, Now, run.RunId, identity,
            [.. run.Tracks.Select(track => SeedPlateTrack.Analysed(track.TrackId,
                new SeedPlate(track.Observations[0].ObservationId, 0.9, ("KA01AB1234", 0.9))))]);
        var cursor = (await SearchAsync(host, "plateText=KA01AB1234&plateMatch=contains&limit=1")).GetProperty("nextCursor").GetString()!;
        var before = host.Logs.Entries.Count;

        var rawQuery = $"plateText=KA01AB1234&plateMatch=contains&limit=1&cursor={Uri.EscapeDataString(cursor)}";
        using var response = await host.Client.GetAsync("/api/tracks?" + rawQuery);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        // A match mode outside the vocabulary is never echoed, even though the request is refused.
        using var refused = await host.Client.GetAsync("/api/tracks?plateText=KA01AB1234&plateMatch=evil-value-123");
        Assert.Equal(HttpStatusCode.BadRequest, refused.StatusCode);

        var request = host.Logs.Entries.Skip(before).ToArray();
        var starting = request.Where(entry => entry.EventId.Id == SafeRequestTelemetryMiddleware.RequestStartingEventId).ToArray();
        var finished = request.Where(entry => entry.EventId.Id == SafeRequestTelemetryMiddleware.RequestFinishedEventId).ToArray();
        Assert.Equal(2, starting.Length);
        Assert.Equal(2, finished.Length);
        Assert.Matches(@"^Request starting GET /api/tracks/? \(trace \S+, plateFilterPresent true, plateMatch contains\)$", starting[0].Message);
        Assert.Matches(@"^Request finished GET /api/tracks/? 200 in \d+\.\d ms \(trace \S+, plateFilterPresent true, plateMatch contains\)$", finished[0].Message);
        Assert.Matches(@"^Request finished GET /api/tracks/? 400 in \d+\.\d ms \(trace \S+, plateFilterPresent true, plateMatch none\)$", finished[1].Message);
        // Start and finish of one request carry the same trace id.
        var trace = System.Text.RegularExpressions.Regex.Match(starting[0].Message, @"trace (\S+),").Groups[1].Value;
        Assert.False(string.IsNullOrWhiteSpace(trace));
        Assert.Contains($"trace {trace},", finished[0].Message, StringComparison.Ordinal);

        foreach (var forbidden in new[] { "KA01AB1234", "ka01ab1234", cursor, Uri.EscapeDataString(cursor), rawQuery, "plateText=", "cursor=", "evil-value-123" })
        {
            var leaking = host.Logs.Entries.Where(entry => entry.Message.Contains(forbidden, StringComparison.OrdinalIgnoreCase)).ToArray();
            Assert.True(leaking.Length == 0,
                $"'{forbidden[..Math.Min(forbidden.Length, 24)]}…' was logged: {string.Join(" | ", leaking.Select(entry => $"[{entry.EventId}] {entry.Message[..Math.Min(entry.Message.Length, 160)]}"))}");
        }
    }

    [Fact]
    public async Task RequestsWithoutAPlateFilterStillHaveTelemetry()
    {
        await using var host = await PlateApiHost.CreateAsync(fixture, Now);
        var before = host.Logs.Entries.Count;

        await host.Client.GetAsync("/api/tracks?objectClass=Vehicle");
        await host.Client.GetAsync($"/api/tracks/{Guid.CreateVersion7()}");

        var finished = host.Logs.Entries.Skip(before)
            .Where(entry => entry.EventId.Id == SafeRequestTelemetryMiddleware.RequestFinishedEventId).ToArray();
        Assert.Equal(2, finished.Length);
        Assert.Matches(@"^Request finished GET /api/tracks/? 200 in .* plateFilterPresent false, plateMatch none\)$", finished[0].Message);
        // The detail route is logged by its template, never by the requested id; it carries no plate field.
        Assert.Matches(@"^Request finished GET /api/tracks/\{id:guid\} 404 in .* plateFilterPresent none, plateMatch none\)$", finished[1].Message);
    }
}
