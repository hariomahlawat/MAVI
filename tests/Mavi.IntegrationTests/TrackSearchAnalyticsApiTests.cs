using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Contracts.Api.Tracks;
using Mavi.Domain.Intelligence;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>
/// The analytic Track search over HTTP (plan §AC "Search integration"): ordinary-search
/// parity, the coverage block, the revision-pinned v3 cursor across a scene activation
/// and a supersede, the complete-coverage conflict, cursor authentication and rotation,
/// and identity-aware detail. Predicate-by-predicate translation is pinned at the
/// repository in <c>TrackSearchAnalyticsRepositoryTests</c>.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class TrackSearchAnalyticsApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    // --- Parity -------------------------------------------------------------

    [Fact]
    public async Task AnOrdinarySearchIsUnchangedOnTheWire()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.GetAsync($"/api/tracks?cameraId={world.CameraId}");
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(["items", "nextCursor"], document.RootElement.EnumerateObject().Select(x => x.Name));
        Assert.False(document.RootElement.GetProperty("items")[0].TryGetProperty("analytics", out _));
    }

    // --- Coverage and explanation ------------------------------------------

    [Fact]
    public async Task AnAnalyticSearchCarriesCoverageAndABoundedExplanation()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var response = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?cameraId={world.CameraId}&zoneId={world.ZoneId}&lineId={world.LineId}&crossingDirection=aToB", Json);

        var coverage = response!.AnalyticsCoverage!;
        Assert.Equal(world.RevisionId, coverage.SceneRevisionId);
        Assert.Equal(SceneAnalyticsWorld.AlgorithmVersion, coverage.AlgorithmVersion);
        Assert.Equal((1, 1, 0), (coverage.EvaluatedRuns, coverage.AnalysedTracks, coverage.UnavailableTracks));
        Assert.True(coverage.Complete);

        var item = Assert.Single(response.Items);
        var analytics = item.Analytics!;
        Assert.Equal(world.RevisionId, analytics.SceneRevisionId);
        Assert.Equal(world.ZoneId, Assert.Single(analytics.Zones).ZoneId);
        var line = Assert.Single(analytics.Lines);
        Assert.Equal("aToB", line.MatchedDirection);
        Assert.Equal(world.RunCompletedAtUtc.AddSeconds(2), line.FirstMatchedCrossingUtc);
        Assert.Null(analytics.Motion);
    }

    [Fact]
    public async Task IncompleteCoverageIsMetadataUnlessCompleteIsDemanded()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var partial = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?cameraId={world.CameraId}&loitering=true", Json);
        Assert.Empty(partial!.Items);
        Assert.Equal(1, partial.AnalyticsCoverage!.PendingRuns);
        Assert.False(partial.AnalyticsCoverage.Complete);

        using var demanded = await client.GetAsync(
            $"/api/tracks?cameraId={world.CameraId}&loitering=true&analyticsCoverage=complete");
        Assert.Equal(HttpStatusCode.Conflict, demanded.StatusCode);
        using var problem = JsonDocument.Parse(await demanded.Content.ReadAsStringAsync());
        Assert.Equal("track_analytics_incomplete", problem.RootElement.GetProperty("code").GetString());
        var block = problem.RootElement.GetProperty("analyticsCoverage");
        Assert.Equal(1, block.GetProperty("pendingRuns").GetInt32());
        Assert.False(block.GetProperty("complete").GetBoolean());

        // Explicit partial canonicalises to the default: same answer as omitting it.
        var explicitPartial = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?cameraId={world.CameraId}&loitering=true&analyticsCoverage=partial", Json);
        Assert.Equal(partial.AnalyticsCoverage, explicitPartial!.AnalyticsCoverage);
    }

    [Theory]
    [InlineData("loitering=true")]
    [InlineData("zoneId={zone}&videoAssetId=0199a1f0-0000-7000-8000-0000000000ff")]
    [InlineData("zoneId=0199a1f0-0000-7000-8000-00000000d001")]
    [InlineData("sceneRevisionId=0199a1f0-0000-7000-8000-00000000b001")]
    public async Task UnresolvedScopeAndForeignGeometryAreInvalid(string tail)
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        var query = tail.Replace("{zone}", world.ZoneId.ToString(), StringComparison.Ordinal);
        // The first case has no scope at all; the others carry the camera.
        var path = tail.StartsWith("loitering", StringComparison.Ordinal)
            ? $"/api/tracks?{query}"
            : $"/api/tracks?cameraId={world.CameraId}&{query}";

        using var response = await client.GetAsync(path);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("track_search_invalid", await ReadCodeAsync(response));
    }

    [Fact]
    public async Task ADisabledCameraPinsItsRevisionAndANeverConfiguredOnePinsNull()
    {
        var disabled = await SceneAnalyticsWorld.CreateAsync(fixture, Now, analyticsEnabled: false);
        await using (var factory = CreateFactory(disabled))
        {
            using var client = factory.CreateClient();
            var response = await client.GetFromJsonAsync<TrackSearchResponse>(
                $"/api/tracks?cameraId={disabled.CameraId}&loitering=true", Json);
            Assert.Equal(disabled.RevisionId, response!.AnalyticsCoverage!.SceneRevisionId);
            Assert.Equal(1, response.AnalyticsCoverage.DisabledRuns);
            Assert.Equal(0, response.AnalyticsCoverage.NotConfiguredRuns);
        }

        var unconfigured = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using (var db = unconfigured.Read())
        {
            await db.Database.ExecuteSqlInterpolatedAsync($"DELETE FROM scene_zones WHERE revision_id = {unconfigured.RevisionId}");
            await db.Database.ExecuteSqlInterpolatedAsync($"DELETE FROM trip_lines WHERE revision_id = {unconfigured.RevisionId}");
            await db.Database.ExecuteSqlInterpolatedAsync($"UPDATE scene_configurations SET active_revision_id = NULL WHERE camera_id = {unconfigured.CameraId}");
            await db.Database.ExecuteSqlInterpolatedAsync($"DELETE FROM scene_configuration_revisions WHERE id = {unconfigured.RevisionId}");
            await db.Database.ExecuteSqlInterpolatedAsync($"DELETE FROM scene_configurations WHERE camera_id = {unconfigured.CameraId}");
        }
        await using (var factory = CreateFactory(unconfigured))
        {
            using var client = factory.CreateClient();
            var response = await client.GetFromJsonAsync<TrackSearchResponse>(
                $"/api/tracks?cameraId={unconfigured.CameraId}&loitering=true", Json);
            Assert.Null(response!.AnalyticsCoverage!.SceneRevisionId);
            Assert.Equal(1, response.AnalyticsCoverage.NotConfiguredRuns);
        }
    }

    // --- Revision-pinned cursor --------------------------------------------

    [Fact]
    public async Task ACursorStaysPinnedAcrossAnActivationAndASupersedeAndCoverageIsByteStable()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var second = await AddTrackAsync(world, localTrackNumber: 2, startOffsetMs: 3_000);
        await CommitFactsAsync(world, [world.TrackId, second]);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        var path = $"/api/tracks?cameraId={world.CameraId}&zoneId={world.ZoneId}&limit=1";

        using var firstResponse = await client.GetAsync(path);
        var firstJson = await firstResponse.Content.ReadAsStringAsync();
        var first = JsonSerializer.Deserialize<TrackSearchResponse>(firstJson, Json)!;
        Assert.Equal(second, Assert.Single(first.Items).Id);
        Assert.NotNull(first.NextCursor);
        Assert.InRange(first.NextCursor.Length, 1, TrackCursorCodec.AnalyticMaximumEncodedLength);
        Assert.Equal(1, first.AnalyticsCoverage!.EvaluatedRuns);

        // Geometry is edited and revision 2 is activated; then revision 2 is analysed,
        // which supersedes the revision-1 unit the first page evaluated.
        var newRevision = await world.ActivateNewRevisionAsync(Now.AddMinutes(1));
        await CommitFactsAsync(world, [world.TrackId, second], revisionId: newRevision);
        await using (var db = world.Read())
        {
            var unit = await db.SceneAnalyses.AsNoTracking().SingleAsync(x => x.RevisionId == world.RevisionId);
            Assert.Equal(SceneAnalysisStatus.Superseded, unit.Status);
        }

        using var continuationResponse = await client.GetAsync($"{path}&cursor={Uri.EscapeDataString(first.NextCursor)}");
        Assert.Equal(HttpStatusCode.OK, continuationResponse.StatusCode);
        var continuationJson = await continuationResponse.Content.ReadAsStringAsync();
        var continuation = JsonSerializer.Deserialize<TrackSearchResponse>(continuationJson, Json)!;
        Assert.Equal(world.TrackId, Assert.Single(continuation.Items).Id);
        Assert.Equal(world.RevisionId, continuation.Items[0].Analytics!.SceneRevisionId);
        Assert.Null(continuation.NextCursor);
        Assert.Equal(CoverageText(firstJson), CoverageText(continuationJson));

        // A new search resolves revision 2. Its zone ids are new, so revision 1's zone is
        // now foreign; a generic predicate shows the freshly analysed run instead.
        using var foreign = await client.GetAsync(path);
        Assert.Equal(HttpStatusCode.BadRequest, foreign.StatusCode);
        var fresh = await client.GetFromJsonAsync<TrackSearchResponse>($"/api/tracks?cameraId={world.CameraId}&loitering=true", Json);
        Assert.Equal(newRevision, fresh!.AnalyticsCoverage!.SceneRevisionId);
        Assert.Equal(1, fresh.AnalyticsCoverage.EvaluatedRuns);

        // Explicitly naming revision 1 still reads its superseded facts.
        var historical = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?cameraId={world.CameraId}&sceneRevisionId={world.RevisionId}&zoneId={world.ZoneId}", Json);
        Assert.Equal(2, historical!.Items.Count);
        Assert.Equal(1, historical.AnalyticsCoverage!.EvaluatedRuns);
    }

    [Fact]
    public async Task TheSnapshotExcludesAUnitCompletedAfterTheFirstPage()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var second = await AddTrackAsync(world, localTrackNumber: 2, startOffsetMs: 3_000);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        var path = $"/api/tracks?cameraId={world.CameraId}&sceneRevisionId={world.RevisionId}&limit=1";

        // Nothing analysed yet: no rows, one pending run — and no cursor, because there is
        // nothing to continue. Pin the snapshot through the ordinary path instead.
        var pending = await client.GetFromJsonAsync<TrackSearchResponse>(path, Json);
        Assert.Empty(pending!.Items);
        Assert.Equal(1, pending.AnalyticsCoverage!.PendingRuns);

        // Now analyse, then take a first page whose snapshot precedes a second completion.
        await CommitFactsAsync(world, [world.TrackId, second]);
        var first = await client.GetFromJsonAsync<TrackSearchResponse>(path, Json);
        Assert.Equal(1, first!.AnalyticsCoverage!.EvaluatedRuns);
        Assert.NotNull(first.NextCursor);

        // A unit for a newer identity completes after the first page. The chain stays
        // pinned to revision 1 and its snapshot, and still yields the second row.
        var newRevision = await world.ActivateNewRevisionAsync(Now.AddMinutes(1));
        await CommitFactsAsync(world, [world.TrackId, second], revisionId: newRevision);
        var continuation = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"{path}&cursor={Uri.EscapeDataString(first.NextCursor)}", Json);
        Assert.Equal(world.TrackId, Assert.Single(continuation!.Items).Id);
        Assert.Equal(first.AnalyticsCoverage, continuation.AnalyticsCoverage);
    }

    [Fact]
    public async Task ATamperedOrForeignKeyCursorIsRefusedWhileOrdinaryCursorsSurviveRotation()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var second = await AddTrackAsync(world, localTrackNumber: 2, startOffsetMs: 3_000);
        await CommitFactsAsync(world, [world.TrackId, second]);
        var analyticPath = $"/api/tracks?cameraId={world.CameraId}&zoneId={world.ZoneId}&limit=1";
        var ordinaryPath = $"/api/tracks?cameraId={world.CameraId}&limit=1";

        string analyticCursor;
        string ordinaryCursor;
        await using (var factory = CreateFactory(world))
        {
            using var client = factory.CreateClient();
            analyticCursor = (await client.GetFromJsonAsync<TrackSearchResponse>(analyticPath, Json))!.NextCursor!;
            ordinaryCursor = (await client.GetFromJsonAsync<TrackSearchResponse>(ordinaryPath, Json))!.NextCursor!;

            // Flip one character inside the envelope: the MAC no longer matches.
            var tampered = analyticCursor.ToCharArray();
            tampered[tampered.Length / 2] = tampered[tampered.Length / 2] == 'A' ? 'B' : 'A';
            using var refused = await client.GetAsync($"{analyticPath}&cursor={new string(tampered)}");
            Assert.Equal(HttpStatusCode.BadRequest, refused.StatusCode);
            Assert.Equal("track_search_invalid", await ReadCodeAsync(refused));

            // A changed filter with the same cursor is a different search.
            using var changed = await client.GetAsync($"{analyticPath}&minDwellMs=1&cursor={Uri.EscapeDataString(analyticCursor)}");
            Assert.Equal(HttpStatusCode.BadRequest, changed.StatusCode);
        }

        // The installation rotates its key: analytic cursors die, ordinary ones do not.
        await using (var rotated = CreateFactory(world, cursorSigningKey: "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="))
        {
            using var client = rotated.CreateClient();
            using var analytic = await client.GetAsync($"{analyticPath}&cursor={Uri.EscapeDataString(analyticCursor)}");
            Assert.Equal(HttpStatusCode.BadRequest, analytic.StatusCode);
            using var ordinary = await client.GetAsync($"{ordinaryPath}&cursor={Uri.EscapeDataString(ordinaryCursor)}");
            Assert.Equal(HttpStatusCode.OK, ordinary.StatusCode);
        }
    }

    [Fact]
    public async Task AHistoricalEngineVersionClassifiesMissingUnitsAsStale()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var response = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?cameraId={world.CameraId}&sceneRevisionId={world.RevisionId}&analyticsAlgorithmVersion=scene-analytics-v7", Json);

        Assert.Equal("scene-analytics-v7", response!.AnalyticsCoverage!.AlgorithmVersion);
        Assert.Equal((1, 0), (response.AnalyticsCoverage.StaleRuns, response.AnalyticsCoverage.PendingRuns));
    }

    // --- Detail -------------------------------------------------------------

    [Fact]
    public async Task DetailAnalyticsFollowTheRequestedIdentityAndRefuseAForeignOne()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        var newRevision = await world.ActivateNewRevisionAsync(Now.AddMinutes(1));
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var current = await client.GetFromJsonAsync<TrackDetailResponse>($"/api/tracks/{world.TrackId}", Json);
        Assert.Equal("Stale", current!.Analytics!.Status);
        Assert.Equal(newRevision, current.Analytics.SceneRevisionId);
        var other = Assert.Single(current.Analytics.OtherIdentities);
        Assert.Equal(("Completed", "Analysed", 1), (other.UnitStatus, other.Outcome, other.SceneRevisionNumber));

        var historical = await client.GetFromJsonAsync<TrackDetailResponse>(
            $"/api/tracks/{world.TrackId}?sceneRevisionId={world.RevisionId}&analyticsAlgorithmVersion={SceneAnalyticsWorld.AlgorithmVersion}", Json);
        Assert.Equal("Analysed", historical!.Analytics!.Status);
        Assert.Equal(world.RevisionId, historical.Analytics.SceneRevisionId);
        Assert.Equal("aToB", Assert.Single(historical.Analytics.LineCrossings).Direction);
        Assert.Equal(1_000, Assert.Single(historical.Analytics.Motion!.StationaryIntervals).StartOffsetMs);
        Assert.Equal("bbox-centre", historical.Analytics.ReferencePoint);

        using var foreign = await client.GetAsync($"/api/tracks/{world.TrackId}?sceneRevisionId={Guid.CreateVersion7()}");
        Assert.Equal(HttpStatusCode.BadRequest, foreign.StatusCode);
        using var versionAlone = await client.GetAsync($"/api/tracks/{world.TrackId}?analyticsAlgorithmVersion=scene-analytics-v1");
        Assert.Equal(HttpStatusCode.BadRequest, versionAlone.StatusCode);
        using var unknownKey = await client.GetAsync($"/api/tracks/{world.TrackId}?zoneId={world.ZoneId}");
        Assert.Equal(HttpStatusCode.BadRequest, unknownKey.StatusCode);
        using var missing = await client.GetAsync($"/api/tracks/{Guid.CreateVersion7()}?sceneRevisionId={world.RevisionId}");
        Assert.Equal(HttpStatusCode.NotFound, missing.StatusCode);
    }

    // --- Helpers ------------------------------------------------------------

    private static ApiTestFactory CreateFactory(SceneAnalyticsWorld world, string? cursorSigningKey = null) => new()
    {
        Clock = world.Clock,
        EnableSceneAnalyticsHost = false,
        MediaRootOverride = world.MediaRoot,
        EvidenceRootOverride = world.EvidenceRoot,
        CursorSigningKey = cursorSigningKey ?? ApiTestFactory.DefaultCursorSigningKey,
    };

    private static string CoverageText(string responseJson)
    {
        using var document = JsonDocument.Parse(responseJson);
        return document.RootElement.GetProperty("analyticsCoverage").GetRawText();
    }

    private static async Task<string?> ReadCodeAsync(HttpResponseMessage response)
    {
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.TryGetProperty("code", out var code) ? code.GetString() : null;
    }

    private static async Task<Guid> AddTrackAsync(SceneAnalyticsWorld world, int localTrackNumber, long startOffsetMs)
    {
        await using var db = world.Read();
        var track = Track.Create(
            world.RunId, world.VideoId, localTrackNumber, ObjectClass.Person,
            startOffsetMs, startOffsetMs + 6_000, world.RecordingStartUtc,
            detectionCount: 6, meanConfidence: 0.7, maxConfidence: 0.8, createdAtUtc: world.RunCompletedAtUtc);
        db.Tracks.Add(track);
        await db.SaveChangesAsync();
        return track.Id;
    }

    /// <summary>Analyses the run for one identity with the fixture facts for every Track named.</summary>
    private static async Task CommitFactsAsync(
        SceneAnalyticsWorld world,
        IReadOnlyList<Guid>? trackIds = null,
        Guid? revisionId = null)
    {
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        var requested = await lifecycle.RequestAnalysisAsync(
            world.IdentityFor(revisionId ?? world.RevisionId, SceneAnalyticsWorld.AlgorithmVersion), default);
        Assert.Equal(SceneAnalysisQueueOutcome.Created, requested.Outcome);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        Assert.Equal(requested.AnalysisId, claim!.AnalysisId);

        var tracks = trackIds ?? [world.TrackId];
        var facts = new SceneAnalysisFacts(
            [.. tracks.Select(id => TrackAnalysisOutcome.Analysed(claim.AnalysisId, id, "bbox-centre", 120, 1, 400))],
            [.. tracks.Select(id => TrackZoneVisit.Create(
                claim.AnalysisId, id, world.ZoneId, 0, 1_000, 5_000,
                world.RunCompletedAtUtc, world.RunCompletedAtUtc.AddSeconds(4), 4_000,
                beganInside: false, endedInside: false, closedByGap: false, "NE", "SW"))],
            [.. tracks.Select(id => TrackZoneSummary.Create(
                claim.AnalysisId, id, world.ZoneId, 1, 4_000,
                world.RunCompletedAtUtc, world.RunCompletedAtUtc.AddSeconds(4), true, 45, 4_000))],
            [.. tracks.Select(id => TrackLineCrossing.Create(
                claim.AnalysisId, id, world.LineId, 0, 2_000,
                world.RunCompletedAtUtc.AddSeconds(2), "AToB", 0.25, 0.5))],
            [.. tracks.Select(id => TrackMotionSummary.Create(
                claim.AnalysisId, id, "NE", 0.42, 0.01, 2_500, 2_500,
                [new StationaryInterval(1_000, 3_500)], [world.ZoneId]))]);
        var result = await lifecycle.CommitFactsAsync(claim, facts, default);
        Assert.True(result.IsSuccess);
    }
}
