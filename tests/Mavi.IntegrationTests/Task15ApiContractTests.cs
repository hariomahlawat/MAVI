using System.Net;
using System.Net.Http.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Processing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class Task15ApiContractTests
{
    [Fact]
    public async Task ProcessingStatusMapsOnlyThePublicContract()
    {
        var videoId = Guid.CreateVersion7();
        var runId = Guid.CreateVersion7();
        var queuedAt = new DateTimeOffset(2026, 9, 14, 1, 0, 0, TimeSpan.Zero);
        var status = new ProcessingStatusResult(
            true,
            "Processing",
            new ProcessingRunStatusView(
                runId,
                "Running",
                "phase1-detection-tracking",
                "phase1-v1",
                "worker-contract",
                queuedAt,
                queuedAt.AddSeconds(2),
                null,
                42.5,
                1,
                null));

        using var factory = CreateFactory(status);
        using var client = factory.CreateClient();
        using var response = await client.GetAsync($"/api/videos/{videoId}/processing");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var contract = await response.Content.ReadFromJsonAsync<ProcessingStatusResponse>();
        Assert.NotNull(contract);
        Assert.Equal("Processing", contract.VideoStatus);
        Assert.NotNull(contract.LatestRun);
        Assert.Equal(runId, contract.LatestRun.ProcessingRunId);
        Assert.Equal("Running", contract.LatestRun.Status);
        Assert.Equal(42.5, contract.LatestRun.ProgressPercent);
        Assert.Equal(1, contract.LatestRun.AttemptCount);

        var json = await response.Content.ReadAsStringAsync();
        Assert.DoesNotContain("leaseToken", json, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("configurationJson", json, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("runtimeProvenance", json, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("failureDetails", json, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task NeverQueuedProcessingStatusHasNullLatestRun()
    {
        using var factory = CreateFactory(new ProcessingStatusResult(true, "NotQueued", null));
        using var client = factory.CreateClient();

        var contract = await client.GetFromJsonAsync<ProcessingStatusResponse>(
            $"/api/videos/{Guid.CreateVersion7()}/processing");

        Assert.NotNull(contract);
        Assert.Equal("NotQueued", contract.VideoStatus);
        Assert.Null(contract.LatestRun);
    }

    [Fact]
    public async Task MissingVideoReturnsStableProcessingProblem()
    {
        using var factory = CreateFactory(new ProcessingStatusResult(false, string.Empty, null));
        using var client = factory.CreateClient();
        using var response = await client.GetAsync($"/api/videos/{Guid.CreateVersion7()}/processing");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        var problem = await response.Content.ReadFromJsonAsync<Dictionary<string, object?>>();
        Assert.NotNull(problem);
        Assert.Equal("video_not_found", problem["code"]?.ToString());
    }

    private static ApiTestFactory CreateFactory(ProcessingStatusResult result) =>
        new()
        {
            OverrideServices = services =>
            {
                services.RemoveAll<IProcessingOrchestrator>();
                services.AddSingleton<IProcessingOrchestrator>(new StubProcessingOrchestrator(result));
            },
        };

    private sealed class StubProcessingOrchestrator(ProcessingStatusResult status) : IProcessingOrchestrator
    {
        public Task<ProcessingStatusResult> GetStatusAsync(Guid videoId, CancellationToken cancellationToken) =>
            Task.FromResult(status);

        public Task<ProcessingRunAttestationSource?> GetCompletedRunAttestationAsync(
            Guid processingRunId,
            CancellationToken cancellationToken) =>
            Task.FromResult<ProcessingRunAttestationSource?>(null);

        public Task<QueueProcessingResult> QueueAsync(Guid videoId, CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<VisionLeaseView?> LeaseAsync(string workerId, CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<HeartbeatResult> HeartbeatAsync(
            Guid jobId,
            string workerId,
            string leaseToken,
            double progressPercent,
            CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<OrchestrationResult> FailAsync(
            Guid jobId,
            string workerId,
            string leaseToken,
            string failureCode,
            string? failureMessage,
            CancellationToken cancellationToken) =>
            throw new NotSupportedException();
    }
}
