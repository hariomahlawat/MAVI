using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Api.Events;
using Mavi.Application.Modules.Events;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Contracts.Api.Analytics;
using Mavi.Contracts.Api.Events;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// Analytic events end to end (ADR-025; register C7.1, C7.2): derivation from persisted
/// scene-analytics facts, storage, the provenance binding, recompute behaviour, coverage
/// and the read surface over HTTP.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class AnalyticEventApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    private const string Window = "fromUtc=2026-09-21T05:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900";

    [Fact]
    public async Task TheThinSliceDerivesStoresAndServesEventsWithTheirProvenance()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var unitId = await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        Assert.Equal(1, await DeriveAsync(factory));

        var timeline = await client.GetFromJsonAsync<AnalyticEventTimelineResponse>(
            $"/api/cameras/{world.CameraId}/events?{Window}", Json);

        Assert.NotNull(timeline);
        Assert.Equal(RuleCatalogue.V1.CatalogueVersion, timeline.CatalogueVersion);
        Assert.Equal(world.RevisionId, timeline.SceneRevisionId);
        Assert.True(timeline.Coverage.Complete);
        Assert.Equal((1, 0), (timeline.Coverage.DerivedRuns, timeline.Coverage.EventsPendingRuns));
        Assert.False(timeline.Truncated);
        // The fixture Track is a person who crossed the kerb line once and loitered in the gate zone.
        Assert.Equal(
            [EventRuleIds.ZoneDwell, EventRuleIds.LineCrossing],
            timeline.Events.Select(item => item.RuleId));
        var crossing = timeline.Events.Single(item => item.RuleId == EventRuleIds.LineCrossing);
        Assert.Equal((world.LineId, "AToB", world.TrackId), (crossing.LineId!.Value, crossing.Direction, crossing.PrimaryTrackId!.Value));
        Assert.Equal("Kerb", crossing.LineName);
        Assert.Equal(1, timeline.RuleCounts.Single(count => count.RuleId == EventRuleIds.LineCrossing).Count);
        // A disabled rule has no count at all, rather than a zero.
        Assert.DoesNotContain(timeline.RuleCounts, count => count.RuleId == EventRuleIds.RepeatedVisit);

        var detail = await client.GetFromJsonAsync<AnalyticEventDetailResponse>($"/api/events/{crossing.EventId}", Json);

        Assert.NotNull(detail);
        Assert.Equal(unitId, detail.SceneAnalysisId);
        Assert.Equal(world.RevisionId, detail.SceneRevisionId);
        Assert.Equal(SceneAnalyticsWorld.AlgorithmVersion, detail.AnalyticsAlgorithmVersion);
        Assert.Equal(RuleCatalogue.V1.Sha256, detail.CatalogueSha256);
        var participant = Assert.Single(detail.Participants);
        Assert.Equal((world.TrackId, world.VideoId, "subject"), (participant.TrackId, participant.VideoAssetId, participant.Role));
        var input = Assert.Single(detail.Inputs);
        Assert.Equal("lineCrossing", input.Kind);

        var dwell = timeline.Events.Single(item => item.RuleId == EventRuleIds.ZoneDwell);
        var dwellDetail = await client.GetFromJsonAsync<AnalyticEventDetailResponse>($"/api/events/{dwell.EventId}", Json);
        var threshold = Assert.Single(dwellDetail!.Parameters);
        Assert.Equal(("45", RuleParameterSource.SceneRevision), (threshold.Value, threshold.Source));
        Assert.Equal("Gate", dwellDetail.Event.ZoneName);
    }

    [Fact]
    public async Task CrossingCountsEqualTheStageThreeAggregateForTheSameScope()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        await DeriveAsync(factory);

        var events = await client.GetFromJsonAsync<AnalyticEventTimelineResponse>(
            $"/api/cameras/{world.CameraId}/events?{Window}", Json);
        var aggregate = await client.GetFromJsonAsync<AnalyticsAggregateResponse>(
            $"/api/cameras/{world.CameraId}/analytics/aggregates?{Window}", Json);

        var counted = Assert.Single(events!.CrossingCounts);
        var stageThree = Assert.Single(aggregate!.Lines);
        Assert.Equal(stageThree.LineId, counted.LineId);
        Assert.Equal(stageThree.AToBCounts, counted.AToBCounts);
        Assert.Equal(stageThree.BToACounts, counted.BToACounts);
        Assert.Equal(1, counted.AToBCounts.Sum());
    }

    [Fact]
    public async Task UnderivedRunsArePendingAndNeverShownAsZeroEvents()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var timeline = await client.GetFromJsonAsync<AnalyticEventTimelineResponse>(
            $"/api/cameras/{world.CameraId}/events?{Window}", Json);

        Assert.Empty(timeline!.Events);
        Assert.Empty(timeline.RuleCounts);
        Assert.Empty(timeline.CrossingCounts);
        Assert.Equal((0, 1), (timeline.Coverage.DerivedRuns, timeline.Coverage.EventsPendingRuns));
        Assert.True(timeline.Coverage.Analytics.Complete);
        Assert.False(timeline.Coverage.Complete);
    }

    [Fact]
    public async Task ADerivationIsWrittenOnceAndARecomputeReproducesEveryIdentityAndDigest()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var unitId = await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);

        Assert.Equal(EventDerivationOutcome.Derived, await DeriveUnitAsync(factory, unitId));
        // Idempotent: the unique (unit, catalogue) derivation is the guard.
        Assert.Equal(EventDerivationOutcome.AlreadyDerived, await DeriveUnitAsync(factory, unitId));
        var first = await EventsAsync(unitId);

        // An explicit recompute from scratch (as a new catalogue version would do) gives
        // the same answer, byte for byte.
        await using (var db = world.Read())
        {
            await db.AnalyticEventDerivations.Where(item => item.SceneAnalysisId == unitId).ExecuteDeleteAsync();
        }

        Assert.Equal(EventDerivationOutcome.Derived, await DeriveUnitAsync(factory, unitId));
        var second = await EventsAsync(unitId);

        Assert.NotEmpty(first);
        Assert.Equal(first, second);
    }

    [Fact]
    public async Task EveryPersistedEventIsBoundToItsUnitRevisionAndRuleVersionAndReverifiesFromTheFacts()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var unitId = await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        await DeriveUnitAsync(factory, unitId);

        await using var db = world.Read();
        var derivation = await db.AnalyticEventDerivations.SingleAsync(item => item.SceneAnalysisId == unitId);
        var persisted = await db.AnalyticEvents.Where(item => item.SceneAnalysisId == unitId).ToListAsync();
        var input = await new AnalyticEventRepository(db).ReadDerivationInputAsync(unitId, default);
        var recomputed = EventDeriver.Derive(input!, RuleCatalogue.V1);

        Assert.Equal(recomputed.InputsSha256, derivation.InputsSha256);
        Assert.Equal(RuleCatalogue.V1.Sha256, derivation.CatalogueSha256);
        Assert.Equal(persisted.Count, derivation.EventCount);
        Assert.All(persisted, item =>
        {
            Assert.Equal(world.RevisionId, item.SceneRevisionId);
            Assert.Equal(world.RunId, item.ProcessingRunId);
            Assert.Equal(world.CameraId, item.CameraId);
            Assert.Equal(SceneAnalyticsWorld.AlgorithmVersion, item.AnalyticsAlgorithmVersion);
            Assert.Equal(RuleCatalogue.V1.CatalogueVersion, item.CatalogueVersion);
            Assert.Equal(RuleCatalogue.V1.Rule(item.RuleId).RuleVersion, item.RuleVersion);
            var match = recomputed.Events.Single(candidate => candidate.EventId == item.Id);
            Assert.Equal(match.InputSha256, item.InputSha256);
        });
        using var states = JsonDocument.Parse(derivation.RuleStatesJson);
        var repeated = states.RootElement.EnumerateArray()
            .Single(state => state.GetProperty("ruleId").GetString() == EventRuleIds.RepeatedVisit);
        Assert.False(repeated.GetProperty("enabled").GetBoolean());
        Assert.Equal(RuleCatalogue.RequiresEntityConfirmation, repeated.GetProperty("disabledReason").GetString());
    }

    [Fact]
    public async Task ANewSceneRevisionLeavesOldEventsBoundToTheOldRevisionAndReportsTheCameraStale()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var unitId = await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        await DeriveAsync(factory);

        var newRevision = await world.ActivateNewRevisionAsync(Now);
        var timeline = await client.GetFromJsonAsync<AnalyticEventTimelineResponse>(
            $"/api/cameras/{world.CameraId}/events?{Window}", Json);

        // The new geometry has not been applied: nothing is shown as zero, it is stale.
        Assert.Equal(newRevision, timeline!.SceneRevisionId);
        Assert.Empty(timeline.Events);
        Assert.Equal(1, timeline.Coverage.Analytics.StaleRuns);
        Assert.False(timeline.Coverage.Complete);

        // History is retained, bound to the revision that produced it.
        await using var db = world.Read();
        var retained = await db.AnalyticEvents.Where(item => item.SceneAnalysisId == unitId).ToListAsync();
        Assert.NotEmpty(retained);
        Assert.All(retained, item => Assert.Equal(world.RevisionId, item.SceneRevisionId));
    }

    [Fact]
    public async Task EditingAPermittedDirectionSavesARevisionThatMakesTheRunStale()
    {
        // ADR-025 §6, stated cost: a permitted direction is geometry, so setting one is a new
        // revision and the run's facts no longer describe the active scene until re-analysed.
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var before = await client.GetFromJsonAsync<ProcessingRunAnalyticsResponse>(
            $"/api/processing/runs/{world.RunId}/analytics", Json);
        Assert.Equal("Ready", before!.Readiness);

        var scene = await client.GetFromJsonAsync<Mavi.Contracts.Api.Scene.CameraSceneResponse>(
            $"/api/cameras/{world.CameraId}/scene", Json);
        var active = scene!.ActiveRevision!;
        var request = new Mavi.Contracts.Api.Scene.SaveSceneRequest(
            active.RevisionNumber,
            "one-way kerb",
            null,
            null,
            [.. active.Zones.Select(zone => new Mavi.Contracts.Api.Scene.SaveSceneZoneRequest(
                zone.ZoneId, zone.Name, zone.Kind, zone.Enabled,
                [.. zone.Vertices.Select(point => new Mavi.Contracts.Api.Scene.ScenePointRequest(point.X, point.Y))],
                zone.LoiteringThresholdSeconds))],
            [.. active.TripLines.Select(line => new Mavi.Contracts.Api.Scene.SaveSceneTripLineRequest(
                line.LineId, line.Name, line.Enabled,
                new Mavi.Contracts.Api.Scene.ScenePointRequest(line.A.X, line.A.Y),
                new Mavi.Contracts.Api.Scene.ScenePointRequest(line.B.X, line.B.Y),
                line.Directed, line.AToBLabel, line.BToALabel, "AToB"))]);
        using var saved = await client.PutAsJsonAsync($"/api/cameras/{world.CameraId}/scene", request);
        Assert.Equal(HttpStatusCode.Created, saved.StatusCode);

        var after = await client.GetFromJsonAsync<ProcessingRunAnalyticsResponse>(
            $"/api/processing/runs/{world.RunId}/analytics", Json);
        Assert.Equal("Stale", after!.Readiness);
    }

    [Fact]
    public async Task TheHostCycleDerivesWhatIsDueAndNothingTwice()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        var host = factory.Services.GetRequiredService<AnalyticEventsHostedService>();

        Assert.Equal(1, await host.RunCycleAsync(new AnalyticEventsOptions(), default));
        Assert.Equal(0, await host.RunCycleAsync(new AnalyticEventsOptions(), default));
    }

    [Fact]
    public async Task TheCatalogueIsServedWithEveryRuleAndTheDisabledReason()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var catalogue = await client.GetFromJsonAsync<RuleCatalogueResponse>("/api/events/catalogue", Json);

        Assert.Equal(RuleCatalogue.V1.CatalogueVersion, catalogue!.CatalogueVersion);
        Assert.Equal(RuleCatalogue.V1.Sha256, catalogue.CatalogueSha256);
        Assert.Equal(EventRuleIds.All, catalogue.Rules.Select(rule => rule.RuleId));
        var repeated = catalogue.Rules.Single(rule => rule.RuleId == EventRuleIds.RepeatedVisit);
        Assert.Equal((false, RuleCatalogue.RequiresEntityConfirmation), (repeated.Enabled, repeated.DisabledReason));
        var stopped = catalogue.Rules.Single(rule => rule.RuleId == EventRuleIds.StoppedVehicle);
        Assert.Contains(stopped.Parameters, parameter => parameter.Source == RuleParameterSource.OwnerDecision && parameter.Value == "30");
    }

    [Theory]
    [InlineData("?fromUtc=2026-09-21T05:00:00Z&toUtc=2026-09-21T07:00:00Z")]
    [InlineData("?fromUtc=2026-09-21T05:00:00&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900")]
    [InlineData("?fromUtc=2026-09-21T07:00:00Z&toUtc=2026-09-21T05:00:00Z&bucketSeconds=900")]
    [InlineData("?fromUtc=2026-09-21T05:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900&zoneId=x")]
    [InlineData("?fromUtc=2026-09-21T05:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900&ruleId=loitering")]
    [InlineData("?fromUtc=2026-09-21T05:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900&limit=0")]
    [InlineData("?fromUtc=2026-09-21T05:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900&limit=5001")]
    [InlineData("?fromUtc=2026-09-21T05:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900&bucketSeconds=60")]
    public async Task AMalformedTimelineQueryIsRefused(string query)
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.GetAsync($"/api/cameras/{world.CameraId}/events{query}");

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal(AnalyticEventQueryRules.InvalidQueryCode, document.RootElement.GetProperty("code").GetString());
    }

    [Fact]
    public async Task ARuleFilterAndALimitAreHonouredAndTruncationIsDisclosed()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        await DeriveAsync(factory);

        var filtered = await client.GetFromJsonAsync<AnalyticEventTimelineResponse>(
            $"/api/cameras/{world.CameraId}/events?{Window}&ruleId={EventRuleIds.ZoneDwell}", Json);
        Assert.Equal([EventRuleIds.ZoneDwell], filtered!.Events.Select(item => item.RuleId));
        // Line crossing was filtered out, so it reports nothing, not a row of zeros.
        Assert.Empty(filtered.CrossingCounts);
        Assert.Equal([EventRuleIds.ZoneDwell], filtered.RuleCounts.Select(count => count.RuleId));

        var limited = await client.GetFromJsonAsync<AnalyticEventTimelineResponse>(
            $"/api/cameras/{world.CameraId}/events?{Window}&limit=1", Json);
        Assert.Single(limited!.Events);
        Assert.True(limited.Truncated);
        // Counts are over every matching event, not the page.
        Assert.Equal(2, limited.RuleCounts.Sum(count => count.Count));
    }

    [Fact]
    public async Task AnEventOfARunThatIsNotPublishedIsNotFound()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var unitId = await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        await DeriveUnitAsync(factory, unitId);
        Guid eventId;
        await using (var db = world.Read())
        {
            eventId = await db.AnalyticEvents.Where(item => item.SceneAnalysisId == unitId).Select(item => item.Id).FirstAsync();
            await db.ProcessingRuns.Where(run => run.Id == world.RunId)
                .ExecuteUpdateAsync(setters => setters.SetProperty(run => run.VisibilitySequence, (long?)null));
        }

        using var response = await client.GetAsync($"/api/events/{eventId}");

        // The same answer as for an event that does not exist: the boundary does not enumerate.
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task ConcurrentDerivationsOfOneUnitWriteItOnce()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var unitId = await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);

        var outcomes = await Task.WhenAll(Enumerable.Range(0, 4).Select(_ => DeriveUnitAsync(factory, unitId)));

        Assert.Single(outcomes, outcome => outcome == EventDerivationOutcome.Derived);
        Assert.All(outcomes.Where(outcome => outcome != EventDerivationOutcome.Derived),
            outcome => Assert.Equal(EventDerivationOutcome.AlreadyDerived, outcome));
        await using var db = world.Read();
        Assert.Equal(1, await db.AnalyticEventDerivations.CountAsync(item => item.SceneAnalysisId == unitId));
    }

    [Fact]
    public async Task AnUnknownCameraOrEventIsNotFound()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var camera = await client.GetAsync($"/api/cameras/{Guid.NewGuid()}/events?{Window}");
        using var item = await client.GetAsync($"/api/events/{Guid.NewGuid()}");

        Assert.Equal(HttpStatusCode.NotFound, camera.StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, item.StatusCode);
    }

    // --- Helpers -----------------------------------------------------------------

    private async Task<List<(Guid, string, string)>> EventsAsync(Guid unitId)
    {
        await using var db = fixture.CreateDbContext();
        return (await db.AnalyticEvents.AsNoTracking()
                .Where(item => item.SceneAnalysisId == unitId)
                .Select(item => new { item.Id, item.InputSha256, item.ProvenanceJson })
                .ToListAsync())
            .OrderBy(item => item.Id)
            .Select(item => (item.Id, item.InputSha256, item.ProvenanceJson))
            .ToList();
    }

    private static async Task<int> DeriveAsync(ApiTestFactory factory)
    {
        await using var scope = factory.Services.CreateAsyncScope();
        return await scope.ServiceProvider.GetRequiredService<AnalyticEventService>().DeriveDueAsync(50, default);
    }

    private static async Task<EventDerivationOutcome> DeriveUnitAsync(ApiTestFactory factory, Guid unitId)
    {
        await using var scope = factory.Services.CreateAsyncScope();
        return await scope.ServiceProvider.GetRequiredService<IAnalyticEventRepository>()
            .DeriveAsync(unitId, RuleCatalogue.V1, Now, default);
    }

    private static async Task<Guid> CommitFactsAsync(SceneAnalyticsWorld world)
    {
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion, SceneAnalyticsWorld.ParametersSha256, null, Now.AddDays(-1), 50, default);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        var result = await lifecycle.CommitFactsAsync(claim!, world.Facts(claim!.AnalysisId), default);
        Assert.True(result.IsSuccess);
        return claim.AnalysisId;
    }

    private static ApiTestFactory CreateFactory(SceneAnalyticsWorld world) => new()
    {
        Clock = world.Clock,
        EnableSceneAnalyticsHost = false,
        MediaRootOverride = world.MediaRoot,
        EvidenceRootOverride = world.EvidenceRoot,
    };
}
