using System.Net;
using System.Net.Http.Json;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Contracts.Api.Analytics;
using Mavi.Contracts.Api.Processing;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>
/// The analytics API surface over a real database: readiness, unit status, retry and
/// re-analysis.
/// </summary>
/// <remarks>
/// These go through HTTP rather than calling the service directly, because the things
/// most worth protecting here are contract properties — that the claim token is absent
/// from every response, that a repeated re-analysis is visibly a no-op, and that a retry
/// from the wrong state is a conflict rather than a silent success.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneAnalyticsApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    // --- Readiness ---------------------------------------------------------

    [Fact]
    public async Task ARunWithNoUnitYetReportsPending()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var analytics = await client.GetFromJsonAsync<ProcessingRunAnalyticsResponse>(Route(world));

        Assert.NotNull(analytics);
        Assert.Equal(world.RunId, analytics.ProcessingRunId);
        Assert.Equal("Pending", analytics.Readiness);
        Assert.Equal(world.RevisionId, analytics.ActiveSceneRevisionId);
        Assert.Empty(analytics.Analyses);
    }

    /// <summary>
    /// A camera whose active revision enables nothing reports a switch-off, not an
    /// absence of results.
    /// </summary>
    [Fact]
    public async Task ADisabledCameraReportsDisabledRatherThanEmpty()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now, analyticsEnabled: false);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var analytics = await client.GetFromJsonAsync<ProcessingRunAnalyticsResponse>(Route(world));

        Assert.Equal("Disabled", analytics!.Readiness);
    }

    [Fact]
    public async Task ACompletedUnitReportsReadyWithItsCounts()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        await CompleteOneUnitAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var analytics = await client.GetFromJsonAsync<ProcessingRunAnalyticsResponse>(Route(world));

        Assert.Equal("Ready", analytics!.Readiness);
        var unit = Assert.Single(analytics.Analyses);
        Assert.Equal("Completed", unit.Status);
        Assert.Equal(world.RevisionId, unit.SceneRevisionId);
        Assert.Equal(1, unit.SceneRevisionNumber);
        Assert.Equal(1, unit.AnalysedTrackCount);
        Assert.Equal(0, unit.UnavailableTrackCount);
        Assert.Null(unit.FailureCode);

        // Ownership is surrendered at completion, so there is no lease left to show.
        Assert.Null(unit.LeaseExpiresAtUtc);
    }

    /// <summary>
    /// Activating a new revision makes existing facts stale without deleting them and
    /// without anything having rewritten the run.
    /// </summary>
    [Fact]
    public async Task ActivatingANewRevisionMakesAReadyRunStale()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        await CompleteOneUnitAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        Assert.Equal(
            "Ready",
            (await client.GetFromJsonAsync<ProcessingRunAnalyticsResponse>(Route(world)))!.Readiness);

        await world.ActivateNewRevisionAsync(Now.AddMinutes(5));

        var analytics = await client.GetFromJsonAsync<ProcessingRunAnalyticsResponse>(Route(world));
        Assert.Equal("Stale", analytics!.Readiness);

        // The historical unit is still there, still successful, still readable.
        var unit = Assert.Single(analytics.Analyses);
        Assert.Equal("Completed", unit.Status);
        Assert.Equal(1, unit.AnalysedTrackCount);
    }

    [Fact]
    public async Task ReadinessAppearsOnTheProcessingStatusResponse()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        var status = await client.GetFromJsonAsync<ProcessingStatusResponse>(
            $"/api/videos/{world.VideoId}/processing");

        Assert.NotNull(status?.LatestRun);
        Assert.Equal("Pending", status.LatestRun.AnalyticsReadiness);
    }

    [Fact]
    public async Task AnUnknownRunIsNotFound()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.GetAsync(
            $"/api/processing/runs/{Guid.CreateVersion7()}/analytics");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal("processing_run_not_found", await ReadCodeAsync(response));
    }

    // --- The claim token is never projected --------------------------------

    /// <summary>
    /// The token that fences a running attempt exists in the executing host's memory and
    /// nowhere else. This reads the raw response body of a <c>Running</c> unit — the one
    /// state where a token exists — and asserts it appears in no form.
    /// </summary>
    [Fact]
    public async Task ARunningUnitProjectsItsLeaseButNeverItsClaimToken()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(Policy, default);

        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        var body = await client.GetStringAsync(Route(world));

        var token = claim!.ClaimToken.ToArray();
        Assert.DoesNotContain(Convert.ToHexStringLower(token), body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain(Convert.ToBase64String(token), body, StringComparison.Ordinal);
        Assert.DoesNotContain("claimToken", body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("tokenHash", body, StringComparison.OrdinalIgnoreCase);

        // The lease expiry is not a secret, and is how an operator tells a unit that is
        // progressing from one that has been abandoned.
        var analytics = await client.GetFromJsonAsync<ProcessingRunAnalyticsResponse>(Route(world));
        var unit = Assert.Single(analytics!.Analyses);
        Assert.Equal("Running", unit.Status);
        Assert.Equal(claim.LeaseExpiresAtUtc, unit.LeaseExpiresAtUtc);
        Assert.Equal(1, unit.AttemptCount);
    }

    // --- Retry -------------------------------------------------------------

    [Fact]
    public async Task RetryingAFailedUnitStartsANewCycleAndKeepsItsFacts()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        var analysisId = await CompleteOneUnitAsync(world);
        await ForceFailedAsync(world, analysisId);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.PostAsync($"{Route(world)}/retry", null);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var unit = await response.Content.ReadFromJsonAsync<SceneAnalysisStatusResponse>();
        Assert.Equal(analysisId, unit!.AnalysisId);
        Assert.Equal("Queued", unit.Status);
        Assert.Equal(0, unit.AttemptCount);
        Assert.Null(unit.FailureCode);
        Assert.Null(unit.StartedAtUtc);
        Assert.Null(unit.CompletedAtUtc);

        // The same row, and its facts are untouched: a retry that never succeeds must
        // leave the last good answer exactly where it was.
        await using var reader = world.Read();
        Assert.Equal(1, await reader.SceneAnalyses.CountAsync());
        Assert.NotEmpty(await reader.TrackZoneVisits.ToListAsync());
    }

    [Theory]
    [InlineData(SceneAnalysisStatus.Queued)]
    [InlineData(SceneAnalysisStatus.Running)]
    [InlineData(SceneAnalysisStatus.Completed)]
    public async Task RetryingFromAnyOtherStateIsAConflict(SceneAnalysisStatus state)
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        await DriveToAsync(world, state);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.PostAsync($"{Route(world)}/retry", null);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal(SceneAnalyticsErrorCodes.TransitionInvalid, await ReadCodeAsync(response));
        Assert.Equal(state, (await world.UnitAsync(await SingleUnitIdAsync(world))).Status);
    }

    [Fact]
    public async Task RetryingARunWithNoCurrentAnalysisIsNotFound()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.PostAsync($"{Route(world)}/retry", null);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal("analytics_not_found", await ReadCodeAsync(response));
    }

    // --- Re-analysis -------------------------------------------------------

    [Fact]
    public async Task ReanalysingACameraQueuesItsLatestRun()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.PostAsJsonAsync(
            $"/api/cameras/{world.CameraId}/scene/analyses",
            new SceneReanalysisRequest(null));

        Assert.Equal(HttpStatusCode.Accepted, response.StatusCode);
        var accepted = await response.Content.ReadFromJsonAsync<SceneReanalysisAcceptedResponse>();
        Assert.Equal(world.CameraId, accepted!.CameraId);
        Assert.Equal(world.RevisionId, accepted.SceneRevisionId);
        Assert.Equal("latestRuns", accepted.Scope);
        Assert.Equal(1, accepted.Created);
        Assert.Equal(1, accepted.RunsInScope);
        Assert.Equal(1, await world.Read().SceneAnalyses.CountAsync());
    }

    /// <summary>
    /// A second click must be visibly a no-op. A single "queued" total could not say that,
    /// which is why the response carries the breakdown.
    /// </summary>
    [Fact]
    public async Task ARepeatedRequestCreatesNothingAndSaysSo()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();
        var route = $"/api/cameras/{world.CameraId}/scene/analyses";
        await client.PostAsJsonAsync(route, new SceneReanalysisRequest("allRuns"));

        using var response = await client.PostAsJsonAsync(route, new SceneReanalysisRequest("allRuns"));

        var accepted = await response.Content.ReadFromJsonAsync<SceneReanalysisAcceptedResponse>();
        Assert.Equal(0, accepted!.Created);
        Assert.Equal(1, accepted.AlreadyQueued);
        Assert.Equal(1, accepted.RunsInScope);
        Assert.Equal("allRuns", accepted.Scope);
        Assert.Equal(1, await world.Read().SceneAnalyses.CountAsync());
    }

    [Fact]
    public async Task ARequestAgainstACompletedIdentityReportsItAsAlreadyReady()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        await CompleteOneUnitAsync(world);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.PostAsJsonAsync(
            $"/api/cameras/{world.CameraId}/scene/analyses",
            new SceneReanalysisRequest(null));

        var accepted = await response.Content.ReadFromJsonAsync<SceneReanalysisAcceptedResponse>();
        Assert.Equal(0, accepted!.Created);
        Assert.Equal(1, accepted.AlreadyReady);
    }

    [Fact]
    public async Task ReanalysingADisabledCameraIsRefused()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now, analyticsEnabled: false);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.PostAsJsonAsync(
            $"/api/cameras/{world.CameraId}/scene/analyses",
            new SceneReanalysisRequest(null));

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("analytics_disabled", await ReadCodeAsync(response));
        Assert.Empty(await world.Read().SceneAnalyses.ToListAsync());
    }

    [Fact]
    public async Task AnUnknownScopeIsRejected()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.PostAsJsonAsync(
            $"/api/cameras/{world.CameraId}/scene/analyses",
            new SceneReanalysisRequest("everything"));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("analytics_scope_invalid", await ReadCodeAsync(response));
    }

    /// <summary>No request may supply an identity; attribution is server-controlled.</summary>
    [Fact]
    public async Task ARequestCarryingAnUnknownMemberIsRejected()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var content = new StringContent(
            """{"scope":"latestRuns","requestedBy":"someone"}""",
            System.Text.Encoding.UTF8,
            "application/json");
        using var response = await client.PostAsync($"/api/cameras/{world.CameraId}/scene/analyses", content);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task ReanalysingAnUnknownCameraIsNotFound()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using var factory = CreateFactory(world);
        using var client = factory.CreateClient();

        using var response = await client.PostAsJsonAsync(
            $"/api/cameras/{Guid.CreateVersion7()}/scene/analyses",
            new SceneReanalysisRequest(null));

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal("camera_not_found", await ReadCodeAsync(response));
    }

    // --- Helpers -----------------------------------------------------------

    private static ApiTestFactory CreateFactory(SceneAnalyticsWorld world) => new()
    {
        Clock = world.Clock,
        EnableSceneAnalyticsHost = false,
        MediaRootOverride = world.MediaRoot,
        EvidenceRootOverride = world.EvidenceRoot,
    };

    private static string Route(SceneAnalyticsWorld world) =>
        $"/api/processing/runs/{world.RunId}/analytics";

    private static Task<int> QueueAsync(Mavi.Infrastructure.Persistence.Repositories.SceneAnalysisLifecycle lifecycle) =>
        lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            null,
            Now.AddDays(-1),
            50,
            default);

    private static async Task<Guid> CompleteOneUnitAsync(SceneAnalyticsWorld world)
    {
        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(Policy, default);
        await executor.ExecuteAsync(claim!, new SceneAnalyticsOptions(), default);
        return claim!.AnalysisId;
    }

    private static async Task DriveToAsync(SceneAnalyticsWorld world, SceneAnalysisStatus state)
    {
        if (state == SceneAnalysisStatus.Completed)
        {
            await CompleteOneUnitAsync(world);
            return;
        }

        var (_, lifecycle, db) = world.Executor();
        await using var __ = db;
        await QueueAsync(lifecycle);
        if (state == SceneAnalysisStatus.Running)
        {
            await lifecycle.ClaimNextAsync(Policy, default);
        }
    }

    private static async Task<Guid> SingleUnitIdAsync(SceneAnalyticsWorld world)
    {
        await using var db = world.Read();
        return (await db.SceneAnalyses.AsNoTracking().SingleAsync()).Id;
    }

    private static async Task ForceFailedAsync(SceneAnalyticsWorld world, Guid analysisId)
    {
        await using var db = world.Read();
        await db.Database.ExecuteSqlInterpolatedAsync($"""
            UPDATE scene_analyses
               SET status = 'Failed', failure_code = 'analytics_engine_failed'
             WHERE id = {analysisId}
            """);
    }

    private static async Task<string?> ReadCodeAsync(HttpResponseMessage response)
    {
        using var document = System.Text.Json.JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.TryGetProperty("code", out var code) ? code.GetString() : null;
    }
}
