using System.Data.Common;
using System.Net;
using System.Net.Http.Json;
using Mavi.Contracts.Worker;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// Completion 3.1 at the database commit boundary (S1.4 B3 asynchronous finalization plan §6, §10.1–§10.2).
/// <para>
/// PostgreSQL is the only authority. A failure before the commit leaves the job Leased with no
/// payload, and the worker's retry hands off normally. A commit that succeeded but was reported
/// as failed (the ambiguous outcome) leaves the hand-off committed, and the identical retry
/// observes Finalizing with the same capability, attempt and digest and is answered
/// idempotently. Nothing was sealed, so there is no evidence to compensate or adopt and no
/// cross-resource repair.
/// </para>
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionResultCompletionCommitFailureTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 25, 8, 0, 0, TimeSpan.Zero);
    private static readonly string[] Roles = ["representative", "near-view", "early-diverse", "late-diverse"];

    [Fact]
    public async Task FailureBeforeTheCommitLeavesNeitherTransitionNorPayloadAndTheRetryHandsOff()
    {
        var faults = new CommitBoundaryFaults();
        using var factory = Factory(faults);
        var (client, lease, request) = await LeasedCompletionAsync(factory);

        faults.Arm(failBeforeCommit: true);
        await Assert.ThrowsAsync<InjectedCommitBoundaryException>(() =>
            client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request));

        Assert.True(faults.RollbackReached);
        await AssertNotHandedOffAsync(factory);
        Assert.Empty(EvidenceFiles(factory));

        // Plan §10.1: nothing authoritative changed, the lease is still the worker's.
        using var retried = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, retried.StatusCode);
        var ack = (await retried.Content.ReadFromJsonAsync<VisionJobFinalizationResponse>())!;
        Assert.Equal("finalizing", ack.State);
        await AssertHandedOffOnceAsync(factory, ack.AcceptedAtUtc);
    }

    [Fact]
    public async Task CommitThatSucceededButReportedFailureIsResolvedByTheIdenticalRetry()
    {
        // Plan §10.2: the database committed, then the commit call failed. The hand-off is
        // authoritative; the worker's retry sees Finalizing and gets the same acknowledgement.
        var faults = new CommitBoundaryFaults();
        using var factory = Factory(faults);
        var (client, lease, request) = await LeasedCompletionAsync(factory);

        faults.Arm(failAfterCommit: true);
        await Assert.ThrowsAsync<InjectedCommitBoundaryException>(() =>
            client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request));

        DateTimeOffset acceptedAtUtc;
        using (var scope = factory.Services.CreateScope())
        {
            var job = await scope.ServiceProvider.GetRequiredService<MaviDbContext>().VisionJobs.SingleAsync();
            Assert.Equal(VisionJobStatus.Finalizing, job.Status);
            acceptedAtUtc = job.FinalizationAcceptedAtUtc!.Value;
        }
        await AssertHandedOffOnceAsync(factory, acceptedAtUtc);

        using var replay = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        var ack = (await replay.Content.ReadFromJsonAsync<VisionJobFinalizationResponse>())!;
        Assert.Equal("finalizing", ack.State);
        Assert.Equal(acceptedAtUtc, ack.AcceptedAtUtc);
        await AssertHandedOffOnceAsync(factory, acceptedAtUtc);
        Assert.Empty(EvidenceFiles(factory));
    }

    [Fact]
    public async Task FailureBeforeTheCommitWithAnUnconfirmedRollbackStillLeavesNothingCommitted()
    {
        // The store has no compensation to decide about any more: whatever the rollback call
        // reported, the database either committed or it did not, and here it did not.
        var faults = new CommitBoundaryFaults();
        using var factory = Factory(faults);
        var (client, lease, request) = await LeasedCompletionAsync(factory);

        faults.Arm(failBeforeCommit: true, failRollback: true);
        await Assert.ThrowsAsync<InjectedCommitBoundaryException>(() =>
            client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request));

        await AssertNotHandedOffAsync(factory);

        using var retried = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        Assert.Equal(HttpStatusCode.OK, retried.StatusCode);
        await AssertHandedOffOnceAsync(factory, (await retried.Content.ReadFromJsonAsync<VisionJobFinalizationResponse>())!.AcceptedAtUtc);
    }

    // Helpers
    private static ApiTestFactory Factory(CommitBoundaryFaults faults) => new()
    {
        Clock = new MutableTimeProvider(Now),
        ConfigureDbContext = options => options.AddInterceptors(faults),
    };

    private static async Task<(HttpClient Client, VisionJobLeaseContract Lease, VisionJobCompleteRequest Request)> LeasedCompletionAsync(
        ApiTestFactory factory)
    {
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = await VisionFinalizationSubmissionApiTests.BuildRequestAsync(factory, lease, Roles);
        return (client, lease, request);
    }

    private static string[] EvidenceFiles(ApiTestFactory factory) =>
        Directory.Exists(factory.EvidenceRoot)
            ? Directory.GetFiles(factory.EvidenceRoot, "*", SearchOption.AllDirectories)
            : [];

    private static async Task AssertNotHandedOffAsync(ApiTestFactory factory)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var job = await db.VisionJobs.SingleAsync();
        Assert.Equal(VisionJobStatus.Leased, job.Status);
        Assert.Null(job.CompletionDigest);
        Assert.Null(job.FinalizationAcceptedAtUtc);
        Assert.Equal(0, await db.VisionFinalizationPayloads.CountAsync());
        Assert.Empty(await db.Tracks.ToListAsync());
        Assert.Equal(ProcessingRunStatus.Running, (await db.ProcessingRuns.SingleAsync()).Status);
    }

    private static async Task AssertHandedOffOnceAsync(ApiTestFactory factory, DateTimeOffset acceptedAtUtc)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var job = await db.VisionJobs.SingleAsync();
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal(acceptedAtUtc, job.FinalizationAcceptedAtUtc);
        var payload = await db.VisionFinalizationPayloads.SingleAsync();
        Assert.Equal(job.CompletionDigest, payload.CompletionDigest);
        Assert.Empty(await db.Tracks.ToListAsync());
        Assert.Equal(ProcessingRunStatus.Running, (await db.ProcessingRuns.SingleAsync()).Status);
    }

    private sealed class InjectedCommitBoundaryException(string message) : Exception(message);

    /// <summary>
    /// Fails the next transaction commit on either side of the real database commit,
    /// and optionally the rollback that follows. It is armed only for the completion
    /// under test, so setup and lease transactions are unaffected.
    /// </summary>
    private sealed class CommitBoundaryFaults : DbTransactionInterceptor
    {
        private volatile bool _failBeforeCommit;
        private volatile bool _failAfterCommit;
        private volatile bool _failRollback;

        public bool RollbackReached { get; private set; }

        public void Arm(bool failBeforeCommit = false, bool failAfterCommit = false, bool failRollback = false)
        {
            _failBeforeCommit = failBeforeCommit;
            _failAfterCommit = failAfterCommit;
            _failRollback = failRollback;
            RollbackReached = false;
        }

        public override ValueTask<InterceptionResult> TransactionCommittingAsync(
            DbTransaction transaction, TransactionEventData eventData, InterceptionResult result, CancellationToken cancellationToken = default)
        {
            if (_failBeforeCommit)
            {
                _failBeforeCommit = false;
                throw new InjectedCommitBoundaryException("Injected failure before the database commit.");
            }

            return base.TransactionCommittingAsync(transaction, eventData, result, cancellationToken);
        }

        public override Task TransactionCommittedAsync(
            DbTransaction transaction, TransactionEndEventData eventData, CancellationToken cancellationToken = default)
        {
            if (_failAfterCommit)
            {
                _failAfterCommit = false;
                throw new InjectedCommitBoundaryException("Injected failure after the database commit.");
            }

            return base.TransactionCommittedAsync(transaction, eventData, cancellationToken);
        }

        public override ValueTask<InterceptionResult> TransactionRollingBackAsync(
            DbTransaction transaction, TransactionEventData eventData, InterceptionResult result, CancellationToken cancellationToken = default)
        {
            RollbackReached = true;
            if (_failRollback)
            {
                _failRollback = false;
                throw new InjectedCommitBoundaryException("Injected failure confirming the rollback.");
            }

            return base.TransactionRollingBackAsync(transaction, eventData, result, cancellationToken);
        }
    }
}
