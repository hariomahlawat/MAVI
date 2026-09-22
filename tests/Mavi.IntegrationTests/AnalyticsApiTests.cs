using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Contracts.Api.Analytics;
using Mavi.Domain.Cameras;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace Mavi.IntegrationTests;

/// <summary>
/// The two Slice-6 analytics routes over HTTP: the closed query vocabulary, the
/// response-shape bound, the non-enumerating run boundary, the typed refusals, and the
/// provenance every successful answer must carry (plan §4.4, §5.5, §6, §16).
/// </summary>
/// <remarks>
/// Counting semantics are pinned in the Application tests and scope resolution in the
/// repository tests. What is asserted here is only what crosses the wire.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class AnalyticsApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    private const string From = "2026-09-21T04:00:00Z";
    private const string To = "2026-09-21T07:00:00Z";

    // --- Query vocabulary ---------------------------------------------------

    [Theory]
    // An unknown parameter is refused rather than ignored, so a caller can never
    // believe a filter was applied that the server never saw.
    [InlineData("aggregates", "?fromUtc=2026-09-21T04:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900&zoneId=abc")]
    [InlineData("heatmap", "?fromUtc=2026-09-21T04:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900")]
    // A repeated singleton key is malformed, not "last one wins".
    [InlineData("aggregates", "?fromUtc=2026-09-21T04:00:00Z&fromUtc=2026-09-21T05:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900")]
    [InlineData("heatmap", "?fromUtc=2026-09-21T04:00:00Z&toUtc=2026-09-21T07:00:00Z&gridWidth=16&gridWidth=32")]
    // A local time without an offset is ambiguous and is refused, never guessed.
    [InlineData("aggregates", "?fromUtc=2026-09-21T04:00:00&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900")]
    [InlineData("aggregates", "?fromUtc=2026-09-21T04:00:00%2B05:30&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900")]
    [InlineData("heatmap", "?fromUtc=2026-09-21&toUtc=2026-09-21T07:00:00Z")]
    // Required parameters, and a window that is empty or inverted.
    [InlineData("aggregates", "?fromUtc=2026-09-21T04:00:00Z&toUtc=2026-09-21T07:00:00Z")]
    [InlineData("aggregates", "?fromUtc=2026-09-21T07:00:00Z&toUtc=2026-09-21T04:00:00Z&bucketSeconds=900")]
    [InlineData("heatmap", "?fromUtc=2026-09-21T07:00:00Z&toUtc=2026-09-21T07:00:00Z")]
    // Closed vocabularies: bucket size, object class, grid width, run id.
    [InlineData("aggregates", "?fromUtc=2026-09-21T04:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=30")]
    [InlineData("aggregates", "?fromUtc=2026-09-21T04:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=86401")]
    [InlineData("aggregates", "?fromUtc=2026-09-21T04:00:00Z&toUtc=2026-09-21T07:00:00Z&bucketSeconds=900&objectClass=unicorn")]
    [InlineData("heatmap", "?fromUtc=2026-09-21T04:00:00Z&toUtc=2026-09-21T07:00:00Z&objectClass=unicorn")]
    [InlineData("heatmap", "?fromUtc=2026-09-21T04:00:00Z&toUtc=2026-09-21T07:00:00Z&gridWidth=48")]
    [InlineData("heatmap", "?fromUtc=2026-09-21T04:00:00Z&toUtc=2026-09-21T07:00:00Z&gridWidth=0")]
    [InlineData("heatmap", "?fromUtc=2026-09-21T04:00:00Z&toUtc=2026-09-21T07:00:00Z&processingRunId=not-a-guid")]
    public async Task AMalformedQueryIsRefusedWithTheTypedInvalidCode(string route, string query)
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.GetAsync(
            $"/api/cameras/{world.CameraId}/analytics/{route}{query}");

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal(AnalyticsQueryRules.InvalidQueryCode, await ReadCodeAsync(response));
    }

    [Theory]
    [InlineData("Person")]
    [InlineData("person")]
    [InlineData("PERSON")]
    public async Task ObjectClassIsSpeltTheSameWayHereAsInTrackSearch(string objectClass)
    {
        // The same parameter name on the same API must not be case-sensitive on one
        // route and case-insensitive on another. /api/tracks has always accepted any
        // casing of a member of the closed vocabulary; these routes match it, and the
        // canonical spelling is what comes back.
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var search = await client.GetAsync($"/api/tracks?cameraId={world.CameraId}&objectClass={objectClass}");
        Assert.Equal(HttpStatusCode.OK, search.StatusCode);

        var response = await client.GetFromJsonAsync<AnalyticsAggregateResponse>(
            $"/api/cameras/{world.CameraId}/analytics/aggregates" +
            $"?fromUtc={From}&toUtc={To}&bucketSeconds=900&objectClass={objectClass}", Json);

        Assert.Equal("Person", response!.ObjectClass);
    }

    [Fact]
    public async Task AWindowAndBucketSizeThatWouldOverflowTheResponseIsRefusedBeforeAnyWork()
    {
        // Both values are individually legal. It is their product that the contract
        // cannot transport, so the refusal names the bound rather than the parameter.
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.GetAsync(
            $"/api/cameras/{world.CameraId}/analytics/aggregates" +
            "?fromUtc=2026-09-01T00:00:00Z&toUtc=2026-09-21T00:00:00Z&bucketSeconds=60");

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal(
            AnalyticsQueryRules.BucketCountInvalidCode,
            document.RootElement.GetProperty("code").GetString());
        Assert.Equal(
            AnalyticsQueryRules.MaximumBuckets,
            document.RootElement.GetProperty("maximumBuckets").GetInt32());
    }

    [Fact]
    public async Task TheLargestWindowThatFitsIsAccepted()
    {
        // The complement of the bound: exactly MaximumBuckets is inside it, so the
        // check is not off by one in the direction that silently refuses legal work.
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var from = new DateTimeOffset(2026, 9, 21, 0, 0, 0, TimeSpan.Zero);
        var to = from.AddSeconds(60L * AnalyticsQueryRules.MaximumBuckets);
        var response = await client.GetFromJsonAsync<AnalyticsAggregateResponse>(
            $"/api/cameras/{world.CameraId}/analytics/aggregates" +
            $"?fromUtc={Iso(from)}&toUtc={Iso(to)}&bucketSeconds=60", Json);

        Assert.Equal(AnalyticsQueryRules.MaximumBuckets, response!.Buckets.Count);
    }

    // --- Provenance ---------------------------------------------------------

    [Fact]
    public async Task AnAggregateAnswerCarriesItsResolvedIdentityAndCoverage()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var response = await client.GetFromJsonAsync<AnalyticsAggregateResponse>(
            $"/api/cameras/{world.CameraId}/analytics/aggregates" +
            $"?fromUtc={From}&toUtc={To}&bucketSeconds=900", Json);

        Assert.Equal(world.CameraId, response!.CameraId);
        Assert.Equal(world.RevisionId, response.SceneRevisionId);
        Assert.Equal(SceneAnalyticsWorld.AlgorithmVersion, response.AlgorithmVersion);
        Assert.True(response.SnapshotVisibilitySequence > 0);
        Assert.Equal(12, response.Buckets.Count);
        Assert.True(response.Coverage.Complete);

        // Every series is exactly as long as the bucket axis it is read against.
        foreach (var zone in response.Zones)
        {
            Assert.Equal(
                [response.Buckets.Count, response.Buckets.Count, response.Buckets.Count, response.Buckets.Count],
                new[]
                {
                    zone.EntryCounts.Count, zone.ExitCounts.Count,
                    zone.UniqueTrackCounts.Count, zone.OccupancyAtStart.Count,
                });
        }

        foreach (var line in response.Lines)
        {
            Assert.Equal(response.Buckets.Count, line.AToBCounts.Count);
            Assert.Equal(response.Buckets.Count, line.BToACounts.Count);
        }

        // Buckets tile the window, half-open and contiguous, anchored to fromUtc.
        Assert.Equal(DateTimeOffset.Parse(From, null), response.Buckets[0].StartUtc);
        for (var index = 1; index < response.Buckets.Count; index++)
        {
            Assert.Equal(response.Buckets[index - 1].EndUtc, response.Buckets[index].StartUtc);
        }
    }

    [Fact]
    public async Task AHeatmapAnswerCarriesItsResolvedIdentityGridAndDensity()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await world.AttachTrajectoryAsync(TrajectoryPayload.Encode(
        [
            (0L, 0.10, 0.10),
            (2_000L, 0.50, 0.50),
        ]));
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var response = await client.GetFromJsonAsync<AnalyticsHeatmapResponse>(
            $"/api/cameras/{world.CameraId}/analytics/heatmap?fromUtc={From}&toUtc={To}", Json);

        Assert.Equal(world.CameraId, response!.CameraId);
        Assert.Equal(world.RevisionId, response.SceneRevisionId);
        Assert.True(response.SnapshotVisibilitySequence > 0);
        // The default grid, and the frozen 16:9 height for it.
        Assert.Equal(AnalyticsQueryRules.DefaultGridWidth, response.GridWidth);
        Assert.Equal(AnalyticsQueryRules.GridHeightFor(response.GridWidth), response.GridHeight);
        Assert.Equal(response.GridWidth * response.GridHeight, response.Values.Count);
        Assert.Equal(2, response.SampleCount);
        Assert.Equal(1, response.TrackCount);
        // Sample counts, so the matrix sums to exactly the samples that contributed.
        Assert.Equal(response.SampleCount, response.Values.Sum());
        Assert.Equal(response.Values.Max(), response.MaxCellValue);
    }

    // --- The non-enumerating boundary ---------------------------------------

    [Fact]
    public async Task AMissingCameraAndAnUnusableRunAreIndistinguishable()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        var other = await OtherCameraRunAsync(world);

        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var route = $"/api/cameras/{world.CameraId}/analytics/heatmap?fromUtc={From}&toUtc={To}";
        string[] bodies =
        [
            await BodyAsync(client, $"/api/cameras/{Guid.CreateVersion7()}/analytics/heatmap?fromUtc={From}&toUtc={To}"),
            await BodyAsync(client, $"{route}&processingRunId={Guid.CreateVersion7()}"),
            await BodyAsync(client, $"{route}&processingRunId={other}"),
        ];

        // Byte-identical: the caller learns nothing about whether the run exists, and
        // nothing about another camera's runs.
        Assert.Single(bodies.Distinct(StringComparer.Ordinal));
    }

    [Fact]
    public async Task AnUnpublishedRunIsRefusedTheSameWay()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now, runVisible: false);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.GetAsync(
            $"/api/cameras/{world.CameraId}/analytics/heatmap" +
            $"?fromUtc={From}&toUtc={To}&processingRunId={world.RunId}");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal(AnalyticsQueryRules.CameraNotFoundCode, await ReadCodeAsync(response));
    }

    [Fact]
    public async Task AMissingCameraIsNotFoundForAggregatesToo()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.GetAsync(
            $"/api/cameras/{Guid.CreateVersion7()}/analytics/aggregates" +
            $"?fromUtc={From}&toUtc={To}&bucketSeconds=900");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal(AnalyticsQueryRules.CameraNotFoundCode, await ReadCodeAsync(response));
    }

    // --- Typed refusals -----------------------------------------------------

    [Theory]
    [InlineData(AnalyticsQueryRules.RunsDimension, AnalyticsQueryRules.MaximumHeatmapRuns)]
    [InlineData(AnalyticsQueryRules.TracksDimension, AnalyticsQueryRules.MaximumHeatmapTracks)]
    public async Task AnOversizedScopeIsRefusedWithTheDimensionAndLimitThatFired(
        string dimension, int limit)
    {
        // A stub scope, because the point under test is the transport mapping: that the
        // refusal is a typed 422 naming which bound fired and what it is, so the client
        // can tell the operator how to narrow the request. That the bounds fire before
        // evidence is opened at all is proven in AnalyticsHeatmapGuardTests.
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var runs = dimension == AnalyticsQueryRules.RunsDimension
            ? AnalyticsQueryRules.MaximumHeatmapRuns + 1
            : 1;
        var tracks = dimension == AnalyticsQueryRules.TracksDimension
            ? AnalyticsQueryRules.MaximumHeatmapTracks + 1
            : 0;

        await using var factory = CreateFactory(world, services =>
            Replace<IAnalyticsAggregateRepository>(services, new OversizedScopeRepository(world, runs, tracks)));
        using var client = factory.CreateClient();

        using var response = await client.GetAsync(
            $"/api/cameras/{world.CameraId}/analytics/heatmap?fromUtc={From}&toUtc={To}");

        Assert.Equal(HttpStatusCode.UnprocessableEntity, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal(
            AnalyticsQueryRules.HeatmapScopeTooLargeCode,
            document.RootElement.GetProperty("code").GetString());
        Assert.Equal(dimension, document.RootElement.GetProperty("dimension").GetString());
        Assert.Equal(limit, document.RootElement.GetProperty("limit").GetInt32());
    }

    [Fact]
    public async Task UnreadableEvidenceIsAnOpaqueRetryableFailure()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        // Recorded as sealed evidence, and never written: exactly the state a damaged
        // or half-restored evidence root is in.
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing(), write: false);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.GetAsync(
            $"/api/cameras/{world.CameraId}/analytics/heatmap?fromUtc={From}&toUtc={To}");
        var body = await response.Content.ReadAsStringAsync();

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        using var document = JsonDocument.Parse(body);
        Assert.Equal(
            AnalyticsQueryRules.EvidenceUnreadableCode,
            document.RootElement.GetProperty("code").GetString());

        // The operator is told the evidence could not be read, never where it lives:
        // no storage key, no path, no digest crosses the boundary.
        Assert.DoesNotContain("evidence/", body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain(world.EvidenceRoot, body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("msgpack", body, StringComparison.OrdinalIgnoreCase);
    }

    // --- Helpers ------------------------------------------------------------

    /// <summary>A scope that is legal in every way except its size.</summary>
    private sealed class OversizedScopeRepository(SceneAnalyticsWorld world, int runs, int tracks)
        : IAnalyticsAggregateRepository
    {
        public Task<AnalyticsAggregateResult> AggregateAsync(
            AnalyticsAggregateQuery query, CancellationToken cancellationToken) =>
            throw new NotSupportedException("This test is about the heatmap route.");

        public Task<AnalyticsHeatmapScope> ResolveHeatmapScopeAsync(
            AnalyticsHeatmapQuery query, CancellationToken cancellationToken) =>
            Task.FromResult(new AnalyticsHeatmapScope(
                AnalyticsFailure.None,
                new AnalyticsResolvedIdentity(
                    world.CameraId, world.RevisionId, 1, SceneAnalyticsWorld.AlgorithmVersion, 1),
                new TrackAnalyticsCoverage(
                    world.RevisionId, SceneAnalyticsWorld.AlgorithmVersion,
                    EvaluatedRuns: runs, PendingRuns: 0, FailedRuns: 0, NotConfiguredRuns: 0,
                    DisabledRuns: 0, StaleRuns: 0, AnalysedTracks: tracks, UnavailableTracks: 0),
                runs,
                tracks));

        public Task<IReadOnlyList<HeatmapCandidateTrack>> ListHeatmapCandidatesAsync(
            AnalyticsHeatmapQuery query,
            AnalyticsResolvedIdentity identity,
            CancellationToken cancellationToken) =>
            throw new InvalidOperationException(
                "Candidates were listed although the scope should have been refused.");
    }

    /// <summary>A completed, published run that belongs to a different camera.</summary>
    private static async Task<Guid> OtherCameraRunAsync(SceneAnalyticsWorld world)
    {
        await using var db = world.Read();
        var camera = Camera.Create("CAM-OTHER-01", "Another Camera", "UTC");
        var source = Artifact.Create(
            ArtifactType.SourceVideo,
            $"source/CAM-OTHER-01/{Guid.CreateVersion7()}.mp4",
            "video/mp4",
            1,
            new string('c', 64));
        var video = VideoAsset.Create(
            camera.Id, source.Id, "other.mp4", Now.AddMinutes(-30), 10_000, 25, 1, 640, 360,
            "h264", TimestampSource.Manual, 1.0);
        var run = ProcessingRun.Create(video.Id, "phase1-detection-tracking-v1", "{}", Now.AddMinutes(-20));
        run.MarkRunning("worker-02", Now.AddMinutes(-15));
        run.MarkCompleted(10, 1, 1_000, Now.AddMinutes(-10));
        run.AssignCompletionVisibilitySequence(2);
        db.AddRange(camera, source, video, run);
        await db.SaveChangesAsync();
        return run.Id;
    }

    private static void Replace<TService>(IServiceCollection services, TService instance)
        where TService : class
    {
        services.RemoveAll<TService>();
        services.AddSingleton(instance);
    }

    private static ApiTestFactory CreateFactory(
        SceneAnalyticsWorld world,
        Action<IServiceCollection>? overrideServices = null) => new()
        {
            Clock = world.Clock,
            EnableSceneAnalyticsHost = false,
            MediaRootOverride = world.MediaRoot,
            EvidenceRootOverride = world.EvidenceRoot,
            OverrideServices = overrideServices,
        };

    private static string Iso(DateTimeOffset value) =>
        Uri.EscapeDataString(value.ToString("yyyy-MM-ddTHH:mm:ssZ", System.Globalization.CultureInfo.InvariantCulture));

    private static async Task<string> BodyAsync(HttpClient client, string route)
    {
        using var response = await client.GetAsync(route);
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        return await response.Content.ReadAsStringAsync();
    }

    private static async Task<string?> ReadCodeAsync(HttpResponseMessage response)
    {
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.TryGetProperty("code", out var code) ? code.GetString() : null;
    }

    private static Task<int> QueueAsync(SceneAnalysisLifecycle lifecycle) =>
        lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            null,
            Now.AddDays(-1),
            50,
            default);

    private static async Task CommitFactsAsync(SceneAnalyticsWorld world)
    {
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        var result = await lifecycle.CommitFactsAsync(claim!, world.Facts(claim!.AnalysisId), default);
        Assert.True(result.IsSuccess);
    }
}
