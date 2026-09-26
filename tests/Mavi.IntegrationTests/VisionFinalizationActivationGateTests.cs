using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace Mavi.IntegrationTests;

/// <summary>
/// The S1.4 B3 activation gate (<c>VisionFinalization:Enabled</c>, plan §15.2, F2 deployment
/// note). Held off, the platform behaves exactly as before F2 for workers, and no job may enter
/// Finalizing. Since F4-C the shipped appsettings.json turns the gate on, which retires 3.0 and
/// makes 3.1 the durable hand-off; a machine override holds it off for activation step 1 and
/// rollback. These tests set the gate explicitly (<see cref="ApiTestFactory"/>); the shipped
/// file itself is pinned by <see cref="ConfigurationValidationTests"/>.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionFinalizationActivationGateTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 25, 8, 0, 0, TimeSpan.Zero);
    private static readonly string[] Roles = ["representative", "near-view", "early-diverse", "late-diverse"];

    // -- gate held off: an F2-only deployment, activation step 1, or a rollback ---------------

    [Fact]
    public async Task WhenTheGateIsHeldOffTheProbeAdvertisesTheSynchronousVersionsAndNever31()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();

        using var probe = await client.GetAsync("/api/vision/contract");

        Assert.Equal(HttpStatusCode.OK, probe.StatusCode);
        var body = await probe.Content.ReadAsStringAsync();
        Assert.Contains("\"completionSchemaVersions\":[\"2.0\",\"3.0\"]", body, StringComparison.Ordinal);
        Assert.DoesNotContain("3.1", body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task WhenTheGateIsHeldOffA31SubmissionIsRefusedBeforeTheHandOffStoreAndNoJobBecomesFinalizing()
    {
        var trap = new SubmissionStoreTrap();
        using var factory = new ApiTestFactory
        {
            Clock = new MutableTimeProvider(Now),
            OverrideServices = services =>
            {
                services.RemoveAll<IVisionFinalizationSubmissionStore>();
                services.AddSingleton<IVisionFinalizationSubmissionStore>(trap);
            },
        };
        var (client, lease, request) = await LeasedAsync(factory);

        using var refused = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request with { SchemaVersion = "3.1" });

        Assert.Equal(HttpStatusCode.BadRequest, refused.StatusCode);
        Assert.Contains("worker_contract_version_unsupported", await refused.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        Assert.Equal(0, trap.Calls);
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var job = await db.VisionJobs.SingleAsync();
        Assert.Equal(VisionJobStatus.Leased, job.Status);
        Assert.Null(job.FinalizationAcceptedAtUtc);
        Assert.Equal(0, await db.VisionFinalizationPayloads.CountAsync());
        Assert.Equal(0, await db.VisionJobs.CountAsync(x => x.Status == VisionJobStatus.Finalizing));
    }

    [Fact]
    public async Task WhenTheGateIsHeldOffTheStoreItselfRefusesToHandOffEvenIfReachedDirectly()
    {
        // Defence in depth: the gate is enforced inside the store too, so no caller can
        // create a Finalizing row on a platform without a finalizer.
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now) };
        var (_, lease, request) = await LeasedAsync(factory);

        VisionFinalizationSubmissionResult result;
        using (var scope = factory.Services.CreateScope())
        {
            var store = scope.ServiceProvider.GetRequiredService<IVisionFinalizationSubmissionStore>();
            result = await store.SubmitAsync(lease.JobId, lease.WorkerId, lease.LeaseToken, request with { SchemaVersion = "3.1" }, CancellationToken.None);
        }

        Assert.False(result.IsSuccess);
        Assert.Equal("vision_finalization_disabled", result.ErrorCode);
        using var verify = factory.Services.CreateScope();
        var db = verify.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Equal(VisionJobStatus.Leased, (await db.VisionJobs.SingleAsync()).Status);
        Assert.Equal(0, await db.VisionFinalizationPayloads.CountAsync());
    }

    [Fact]
    public async Task WhenTheGateIsHeldOffAnF2OnlyDeploymentCannotStrandAJobInFinalizing()
    {
        // The cold-review scenario: a worker leases a real job, submits, exits, and no finalizer
        // exists. With the gate off the only accepted v3 exchange is the synchronous 3.0
        // completion, which publishes in the request; a 3.1 attempt is refused. Either way the
        // job ends Completed (or stays Leased for the worker to retry), never Finalizing.
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now) };
        var (client, lease, request) = await LeasedAsync(factory);

        using var handOffAttempt = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request with { SchemaVersion = "3.1" });
        Assert.Equal(HttpStatusCode.BadRequest, handOffAttempt.StatusCode);

        using var completed = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        var response = (await completed.Content.ReadFromJsonAsync<VisionJobCompleteResponse>())!;
        Assert.Equal("3.0", response.SchemaVersion);
        Assert.Equal(1, response.TracksAccepted);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Equal(VisionJobStatus.Completed, (await db.VisionJobs.SingleAsync()).Status);
        Assert.Equal(ProcessingRunStatus.Completed, (await db.ProcessingRuns.SingleAsync()).Status);
        Assert.Equal(VideoProcessingStatus.Processed, (await db.VideoAssets.SingleAsync()).ProcessingStatus);
        Assert.Equal(1, await db.Tracks.CountAsync());
        Assert.Equal(0, await db.VisionJobs.CountAsync(x => x.Status == VisionJobStatus.Finalizing));
        Assert.Equal(0, await db.VisionFinalizationPayloads.CountAsync());
        using var status = await client.GetAsync($"/api/videos/{(await db.VideoAssets.SingleAsync()).Id}/processing");
        using var statusBody = JsonDocument.Parse(await status.Content.ReadAsStringAsync());
        Assert.Equal("completed", statusBody.RootElement.GetProperty("latestRun").GetProperty("phase").GetString());
    }

    // -- activated (gate on): the shipped default since F4-C ------------------------------------

    [Fact]
    public async Task WhenActivatedTheProbeAdvertises31Retires30AndTheHandOffIsLive()
    {
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now), EnableAsynchronousFinalization = true };
        var (client, lease, request) = await LeasedAsync(factory);

        using var probe = await client.GetAsync("/api/vision/contract");
        var advertised = await probe.Content.ReadAsStringAsync();
        Assert.Contains("\"completionSchemaVersions\":[\"2.0\",\"3.1\"]", advertised, StringComparison.Ordinal);
        Assert.DoesNotContain("\"3.0\"", advertised, StringComparison.Ordinal);

        using var retired = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.BadRequest, retired.StatusCode);
        Assert.Contains("worker_contract_version_unsupported", await retired.Content.ReadAsStringAsync(), StringComparison.Ordinal);

        using var handedOff = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request with { SchemaVersion = "3.1" });
        Assert.Equal(HttpStatusCode.OK, handedOff.StatusCode);
        Assert.Equal("finalizing", (await handedOff.Content.ReadFromJsonAsync<VisionJobFinalizationResponse>())!.State);
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        Assert.Equal(VisionJobStatus.Finalizing, (await db.VisionJobs.SingleAsync()).Status);
        Assert.Equal(1, await db.VisionFinalizationPayloads.CountAsync());
    }

    // -- activation symmetry ------------------------------------------------------------------

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task TheProbeAdvertisesExactlyTheVersionsTheEndpointAccepts(bool activated)
    {
        // No split brain: the capability probe and the completion endpoint read the same gate,
        // so a worker that trusts the probe is never refused for its version, and a worker on
        // a version the probe does not list is always refused.
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(Now), EnableAsynchronousFinalization = activated };
        var (client, lease, request) = await LeasedAsync(factory);
        using var probe = await client.GetAsync("/api/vision/contract");
        using var body = JsonDocument.Parse(await probe.Content.ReadAsStringAsync());
        var advertised = body.RootElement.GetProperty("completionSchemaVersions").EnumerateArray().Select(x => x.GetString()!).ToHashSet();
        Assert.Equal(WorkerContractRules.CompletionSchemaVersions(activated).ToHashSet(), advertised);

        foreach (var version in new[] { "2.0", "3.0", "3.1" })
        {
            // A 2.0 body needs a 2.0 shape; probing the version gate is enough for the point.
            using var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request with { SchemaVersion = version });
            var refusedForVersion = response.StatusCode == HttpStatusCode.BadRequest &&
                (await response.Content.ReadAsStringAsync()).Contains("worker_contract_version_unsupported", StringComparison.Ordinal);
            Assert.Equal(!advertised.Contains(version), refusedForVersion);
        }
    }

    // -- helpers ------------------------------------------------------------------------------

    private static async Task<(HttpClient Client, VisionJobLeaseContract Lease, VisionJobCompleteRequest Request)> LeasedAsync(ApiTestFactory factory)
    {
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        // A staged 3.0 body (crops and trajectory present), so the synchronous path can publish it.
        var request = await VisionResultCompletionV3ApiTests.BuildRequestAsync(factory, lease, Roles);
        return (client, lease, request);
    }

    private sealed class SubmissionStoreTrap : IVisionFinalizationSubmissionStore
    {
        private int _calls;
        public int Calls => _calls;

        public Task<VisionFinalizationSubmissionResult> SubmitAsync(Guid jobId, string workerId, string leaseToken, VisionJobCompleteRequest request, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _calls);
            throw new InvalidOperationException("The hand-off store must be unreachable while asynchronous finalization is not activated.");
        }
    }
}
