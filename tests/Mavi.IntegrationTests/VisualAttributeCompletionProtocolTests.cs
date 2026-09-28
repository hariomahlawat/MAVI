using System.Net;
using System.Net.Http.Json;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Application.Modules.VisualAttributes.Completion;
using Mavi.Contracts.Worker.Attributes;
using Mavi.Domain.Media;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// The three-phase publication protocol under its races (S2b plan §13, §4): the reclaim
/// between Phase A and Phase C, expiry without reclaim, a crash after seal, an ambiguous
/// commit, concurrent duplicates, and preferred-identity supersession across binding changes.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisualAttributeCompletionProtocolTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);

    private async Task<(VisualAttributeApiHost Host, SeededRun Run)> HostWithQueuedRunAsync()
    {
        var host = await VisualAttributeApiHost.CreateAsync(fixture, Now);
        await host.RunCycleAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        var run = await host.World.SeedRunAsync(2, 1, 2, completedAtUtc: host.World.Clock.GetUtcNow());
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        return (host, run);
    }

    private static async Task<BuiltCompletion> StagedAsync(VisualAttributeApiHost host, LeasedUnit unit, string value = "dark")
    {
        var completion = AttributeCompletionBuilder.Build(unit, value: value);
        using var uploaded = await host.UploadAsync(unit, completion.Predictions);
        Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);
        return completion;
    }

    private static async Task<VisualAttributeCompletionResult> CompleteThroughSeamsAsync(
        VisualAttributeApiHost host, LeasedUnit unit, BuiltCompletion completion,
        Func<CancellationToken, Task>? beforePhaseC = null, Func<Task>? beforeCommit = null, Func<Task>? afterCommit = null)
    {
        var (service, scope) = host.CompletionService(beforePhaseC, beforeCommit, afterCommit);
        using (scope)
            return await service.CompleteAsync(unit.AnalysisId, unit.Capability, completion.Request, CancellationToken.None);
    }

    private static async Task AssertNothingPublishedAsync(VisualAttributeApiHost host, Guid analysisId)
    {
        await using var db = host.World.Read();
        var unit = await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync(x => x.Id == analysisId);
        Assert.Equal(VisualAttributeAnalysisStatus.Running, unit.Status);
        Assert.Null(unit.VisibilitySequence);
        Assert.Null(unit.CompletionDigest);
        Assert.False(await db.VisualAttributeTrackOutcomes.AnyAsync(x => x.AnalysisId == analysisId));
        Assert.False(await db.VisualAttributes.AnyAsync(x => x.AnalysisId == analysisId));
        Assert.False(await db.Artifacts.AnyAsync(x => x.ArtifactType == ArtifactType.AttributePredictions));
    }

    private static async Task<string> ReadinessAsync(VisualAttributeApiHost host, Guid runId)
    {
        using var response = await host.Client.GetAsync($"/api/processing/runs/{runId}/visual-attributes");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return await response.Content.ReadAsStringAsync();
    }

    // --- Phase C re-fence ------------------------------------------------------------------

    [Fact]
    public async Task AReclaimBetweenPhaseAAndPhaseCIsRefusedAndTheSealedOrphanIsSafe()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var first = await host.LeaseAsync("attributes-01");
        var completion = await StagedAsync(host, first);
        LeasedUnit? second = null;

        var result = await CompleteThroughSeamsAsync(host, first, completion, beforePhaseC: async _ =>
        {
            // Phase A passed and the object is sealed; the lease now expires and another worker reclaims.
            host.World.Clock.Advance(TimeSpan.FromMinutes(3));
            second = await host.LeaseAsync("attributes-02");
        });

        Assert.Equal(VisualAttributeCompletionStatus.Refused, result.Status);
        Assert.Equal(409, result.HttpStatus);
        Assert.Equal(VisualAttributeAnalysis.StaleAttemptCode, result.Code);
        Assert.NotNull(second);
        Assert.Equal(2, second.Attempt);
        await AssertNothingPublishedAsync(host, first.AnalysisId);
        var acceptedPath = host.World.EvidencePath(AttributeStagingLayout.AcceptedKey(first.AnalysisId, completion.Sha256));
        Assert.Equal(completion.Predictions, await File.ReadAllBytesAsync(acceptedPath));

        // The reclaiming attempt publishes; identical bytes adopt the orphan rather than conflict.
        var retry = await StagedAsync(host, second);
        Assert.Equal(completion.Sha256, retry.Sha256);
        using var published = await host.CompleteAsync(second, retry.Request);
        Assert.Equal(HttpStatusCode.OK, published.StatusCode);
        await using var db = host.World.Read();
        var unit = await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync();
        Assert.Equal(VisualAttributeAnalysisStatus.Completed, unit.Status);
        Assert.Equal(2, unit.AttemptCount);
        Assert.Equal(1, await db.Artifacts.CountAsync(x => x.ArtifactType == ArtifactType.AttributePredictions));
    }

    [Fact]
    public async Task ExpiryAfterPhaseAWithoutReclaimRemainsPublishableByTheOwningAttempt()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);

        var result = await CompleteThroughSeamsAsync(host, unit, completion,
            beforePhaseC: _ =>
            {
                host.World.Clock.Advance(TimeSpan.FromMinutes(10));
                return Task.CompletedTask;
            });

        Assert.Equal(VisualAttributeCompletionStatus.Completed, result.Status);
        Assert.False(result.IsReplay);
        await using var db = host.World.Read();
        Assert.Equal(VisualAttributeAnalysisStatus.Completed, (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).Status);
    }

    [Fact]
    public async Task AClientThatGoesAwayAfterTheSealDoesNotAbortThePublication()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);
        using var request = new CancellationTokenSource();

        var (service, scope) = host.CompletionService(beforePhaseC: _ =>
        {
            // The worker's HTTP timeout fires, or its connection drops, once the object is sealed.
            request.Cancel();
            return Task.CompletedTask;
        });
        VisualAttributeCompletionResult result;
        using (scope)
            result = await service.CompleteAsync(unit.AnalysisId, unit.Capability, completion.Request, request.Token);

        Assert.Equal(VisualAttributeCompletionStatus.Completed, result.Status);
        await using var db = host.World.Read();
        Assert.Equal(VisualAttributeAnalysisStatus.Completed, (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).Status);
    }

    [Fact]
    public async Task ACompletionStartedAfterExpiryIsRefusedAtPhaseA()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);
        host.World.Clock.Advance(TimeSpan.FromMinutes(3));

        using var response = await host.CompleteAsync(unit, completion.Request);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("visual_attribute_lease_invalid", await VisualAttributeApiHost.ProblemCodeAsync(response));
        await AssertNothingPublishedAsync(host, unit.AnalysisId);
        // Nothing was sealed either: Phase A refuses before any filesystem work.
        Assert.False(Directory.Exists(Path.Combine(host.World.EvidenceRoot, "attributes")));
    }

    // --- Crash and ambiguity ---------------------------------------------------------------

    [Fact]
    public async Task ACrashAfterSealPublishesNothingAndTheRetryAdoptsTheSealedObject()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);

        await Assert.ThrowsAsync<InvalidOperationException>(() => CompleteThroughSeamsAsync(host, unit, completion,
            beforePhaseC: _ => throw new InvalidOperationException("process died after seal")));

        await AssertNothingPublishedAsync(host, unit.AnalysisId);
        var acceptedPath = host.World.EvidencePath(AttributeStagingLayout.AcceptedKey(unit.AnalysisId, completion.Sha256));
        Assert.True(File.Exists(acceptedPath));

        using var retry = await host.CompleteAsync(unit, completion.Request);
        Assert.Equal(HttpStatusCode.OK, retry.StatusCode);
        Assert.Equal(completion.Predictions, await File.ReadAllBytesAsync(acceptedPath));
        await using var db = host.World.Read();
        Assert.Equal(1, await db.Artifacts.CountAsync(x => x.ArtifactType == ArtifactType.AttributePredictions));
    }

    [Fact]
    public async Task AnAmbiguousCommitPublishesNothingAndTheRetryPublishesOnce()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);

        var ambiguous = await CompleteThroughSeamsAsync(host, unit, completion,
            beforeCommit: () => throw new IOException("connection reset during COMMIT"));

        Assert.Equal(503, ambiguous.HttpStatus);
        Assert.Equal("visual_attribute_publication_ambiguous", ambiguous.Code);
        await AssertNothingPublishedAsync(host, unit.AnalysisId);

        using var retry = await host.CompleteAsync(unit, completion.Request);
        Assert.Equal(HttpStatusCode.OK, retry.StatusCode);
        using var replay = await host.CompleteAsync(unit, completion.Request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        await using var db = host.World.Read();
        var published = await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync();
        Assert.Equal(3, await db.VisualAttributeTrackOutcomes.CountAsync(x => x.AnalysisId == published.Id));
    }

    /// <summary>A completion whose first person Track was scored from one crop; the other failed its digest.</summary>
    private static async Task<(BuiltCompletion Completion, Guid CorruptCrop)> StagedWithACorruptCropAsync(
        VisualAttributeApiHost host, LeasedUnit unit, SeededRun run)
    {
        var corrupt = run.Track(0).Observations[0].ObservationId;
        var completion = AttributeCompletionBuilder.Build(unit, unavailableObservation: id => id == corrupt ? "evidence_integrity_failed" : null);
        using var uploaded = await host.UploadAsync(unit, completion.Predictions);
        Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);
        return (completion, corrupt);
    }

    private static VisualAttributeIntegrityHealth Integrity(VisualAttributeApiHost host) =>
        host.Factory.Services.GetRequiredService<VisualAttributeIntegrityMonitor>().Current;

    [Fact]
    public async Task ACorruptCropIsAnIncidentEvenWhenTheCommitLandedAmbiguouslyAndTheRetryIsAReplay()
    {
        var (host, run) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var (completion, _) = await StagedWithACorruptCropAsync(host, unit, run);

        var ambiguous = await CompleteThroughSeamsAsync(host, unit, completion,
            afterCommit: () => throw new IOException("connection reset after COMMIT"));
        Assert.Equal("visual_attribute_publication_ambiguous", ambiguous.Code);

        // The commit landed: the worker's identical retry is answered by committed replay.
        using var replay = await host.CompleteAsync(unit, completion.Request);
        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        await using (var db = host.World.Read())
            Assert.Equal(VisualAttributeAnalysisStatus.Completed, (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).Status);
        var integrity = Integrity(host);
        Assert.Equal(1, integrity.CompletionIncidents);
        Assert.Equal(unit.AnalysisId, integrity.LastIncidentAnalysisId);
    }

    [Fact]
    public async Task ACorruptCropIsCountedOnceAcrossAFailedCommitAndItsRetry()
    {
        var (host, run) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var (completion, _) = await StagedWithACorruptCropAsync(host, unit, run);

        var ambiguous = await CompleteThroughSeamsAsync(host, unit, completion,
            beforeCommit: () => throw new IOException("connection reset during COMMIT"));
        Assert.Equal("visual_attribute_publication_ambiguous", ambiguous.Code);
        using (var retry = await host.CompleteAsync(unit, completion.Request))
            Assert.Equal(HttpStatusCode.OK, retry.StatusCode);
        using (var replay = await host.CompleteAsync(unit, completion.Request))
            Assert.Equal(HttpStatusCode.OK, replay.StatusCode);

        Assert.Equal(1, Integrity(host).CompletionIncidents);
    }

    [Fact]
    public async Task AHeartbeatingWorkerIsPresentForReadinessThroughALongAnalysis()
    {
        var (host, run) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var presence = TimeSpan.FromSeconds(new VisualAttributeOptions().WorkerPresenceSeconds);

        // Well past the presence window since the lease poll, the worker still renews its lease.
        var step = presence / 2 + TimeSpan.FromSeconds(10);
        for (var elapsed = TimeSpan.Zero; elapsed <= presence; elapsed += step)
        {
            host.World.Clock.Advance(step);
            using var heartbeat = await host.HeartbeatAsync(unit);
            Assert.Equal(HttpStatusCode.OK, heartbeat.StatusCode);
        }

        var during = await ReadinessAsync(host, run.RunId);
        Assert.DoesNotContain(VisualAttributeReadinessRule.NoReadyWorker, during, StringComparison.Ordinal);
        Assert.Contains("\"running\"", during, StringComparison.Ordinal);

        // A worker that stops renewing ages out like one that stops polling.
        host.World.Clock.Advance(presence + TimeSpan.FromSeconds(1));
        Assert.Contains(VisualAttributeReadinessRule.NoReadyWorker, await ReadinessAsync(host, run.RunId), StringComparison.Ordinal);
    }

    [Fact]
    public async Task ARefusedHeartbeatIsNotPresence()
    {
        var (host, run) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(new VisualAttributeOptions().WorkerPresenceSeconds + 1));

        // The lease has expired: the renewal is refused, and proves nothing about a READY worker.
        using (var heartbeat = await host.HeartbeatAsync(unit))
            Assert.NotEqual(HttpStatusCode.OK, heartbeat.StatusCode);
        Assert.Contains(VisualAttributeReadinessRule.NoReadyWorker, await ReadinessAsync(host, run.RunId), StringComparison.Ordinal);
    }

    [Fact]
    public async Task ConcurrentIdenticalCompletionsPublishOnce()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);

        var responses = await Task.WhenAll(Enumerable.Range(0, 4).Select(_ => host.CompleteAsync(unit, completion.Request)));

        Assert.All(responses, response => Assert.Equal(HttpStatusCode.OK, response.StatusCode));
        foreach (var response in responses) response.Dispose();
        await using var db = host.World.Read();
        var published = await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync();
        Assert.Equal(3, await db.VisualAttributeTrackOutcomes.CountAsync(x => x.AnalysisId == published.Id));
        Assert.Equal(1, await db.Artifacts.CountAsync(x => x.ArtifactType == ArtifactType.AttributePredictions));
    }

    [Fact]
    public async Task PublicationWaitsForTheVisibilityBarrier()
    {
        var (host, _) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);

        // A first-page search in flight holds the barrier shared.
        await using var search = host.World.Read();
        await using var searchTransaction = await search.Database.BeginTransactionAsync();
        await Mavi.Infrastructure.Persistence.ProcessingVisibilityBarrier.AcquireSearchSharedAsync(search, CancellationToken.None);
        var sequenceBefore = await Mavi.Infrastructure.Persistence.ProcessingVisibilityBarrier.AllocateSequenceAsync(search, CancellationToken.None);

        var publishing = host.CompleteAsync(unit, completion.Request);
        await Task.Delay(TimeSpan.FromSeconds(1.5));
        Assert.False(publishing.IsCompleted);
        await using (var db = host.World.Read())
            Assert.Equal(VisualAttributeAnalysisStatus.Running, (await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).Status);

        await searchTransaction.CommitAsync();
        using var response = await publishing;
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        await using (var db = host.World.Read())
            Assert.True((await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync()).VisibilitySequence > sequenceBefore);
    }

    // --- Preferred identity, supersession and rollback -----------------------------------------

    [Fact]
    public async Task ALateObsoleteCompletionIsHistoryAndARollbackReDerivesItAsTheDefault()
    {
        var (host, run) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);

        // The binding moves to B while identity A's attempt is in flight (after the run completed).
        host.World.Clock.Advance(TimeSpan.FromSeconds(10));
        await host.RestartWithAsync(identityB: true);
        await host.RunCycleAsync();
        using (var late = await host.CompleteAsync(unit, completion.Request))
        {
            Assert.Equal(HttpStatusCode.OK, late.StatusCode);
            Assert.Equal("superseded", (await late.Content.ReadFromJsonAsync<VisualAttributeCompleteResponse>())!.Status);
        }

        var underB = await ReadinessAsync(host, run.RunId);
        Assert.Contains("\"Stale\"", underB, StringComparison.Ordinal);
        Assert.Contains("\"defaultAnalysisId\":null", underB, StringComparison.Ordinal);

        // Rollback to A: the existing successful A analysis is the default again; nothing is re-queued.
        await host.RestartWithAsync(identityB: false);
        Assert.Equal(0, (await host.RunCycleAsync()).Queued);
        var underA = await ReadinessAsync(host, run.RunId);
        Assert.Contains("\"Ready\"", underA, StringComparison.Ordinal);
        Assert.Contains($"\"defaultAnalysisId\":\"{unit.AnalysisId}\"", underA, StringComparison.Ordinal);
        await using var db = host.World.Read();
        Assert.Equal(1, await db.VisualAttributeAnalyses.CountAsync(x => x.ProcessingRunId == run.RunId));
    }

    [Fact]
    public async Task APreferredCompletionSupersedesTheOldDefaultAndAFailedReplacementDoesNot()
    {
        var (host, run) = await HostWithQueuedRunAsync();
        await using var owned = host;
        var runB = await host.World.SeedRunAsync(1, 0, 1, completedAtUtc: host.World.Clock.GetUtcNow());
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        foreach (var _ in new[] { run, runB })
        {
            var unitA = await host.LeaseAsync();
            using var completed = await host.UploadAndCompleteAsync(unitA, AttributeCompletionBuilder.Build(unitA));
            Assert.Equal(HttpStatusCode.OK, completed.StatusCode);
        }

        // Identity B becomes preferred; history is not backfilled, so B re-analysis is requested explicitly.
        host.World.Clock.Advance(TimeSpan.FromSeconds(10));
        await host.RestartWithAsync(identityB: true);
        await host.RunCycleAsync();
        var identityB = VisualAttributeReleaseFixture.Definition(identityB: true).Identity.ToFields();
        await using (var db = host.World.Read())
        {
            db.VisualAttributeAnalyses.Add(VisualAttributeAnalysis.Queue(run.RunId, identityB, host.World.Clock.GetUtcNow()));
            db.VisualAttributeAnalyses.Add(VisualAttributeAnalysis.Queue(runB.RunId, identityB, host.World.Clock.GetUtcNow().AddTicks(1)));
            await db.SaveChangesAsync();
        }

        Assert.Contains("\"Stale\"", await ReadinessAsync(host, run.RunId), StringComparison.Ordinal);

        var firstB = await host.LeaseAsync();
        var secondB = await host.LeaseAsync();
        var failing = firstB.Lease.ProcessingRunId == runB.RunId ? firstB : secondB;
        var succeeding = ReferenceEquals(failing, firstB) ? secondB : firstB;

        // The failed replacement leaves the prior success untouched.
        using (var failed = await host.FailAsync(failing, "visual_attribute_output_invalid", "schema drift"))
            Assert.Equal("failed", (await failed.Content.ReadFromJsonAsync<VisualAttributeFailResponse>())!.Outcome);
        using (var completed = await host.UploadAndCompleteAsync(succeeding, AttributeCompletionBuilder.Build(succeeding)))
            Assert.Equal("completed", (await completed.Content.ReadFromJsonAsync<VisualAttributeCompleteResponse>())!.Status);

        await using (var db = host.World.Read())
        {
            var units = await db.VisualAttributeAnalyses.AsNoTracking().ToListAsync();
            var byRun = units.ToLookup(x => x.ProcessingRunId);
            Assert.Equal(VisualAttributeAnalysisStatus.Superseded, byRun[succeeding.Lease.ProcessingRunId].Single(x => x.Id != succeeding.AnalysisId).Status);
            Assert.Equal(VisualAttributeAnalysisStatus.Completed, byRun[succeeding.Lease.ProcessingRunId].Single(x => x.Id == succeeding.AnalysisId).Status);
            Assert.Equal(VisualAttributeAnalysisStatus.Completed, byRun[failing.Lease.ProcessingRunId].Single(x => x.Id != failing.AnalysisId).Status);
            Assert.Equal(VisualAttributeAnalysisStatus.Failed, byRun[failing.Lease.ProcessingRunId].Single(x => x.Id == failing.AnalysisId).Status);
            // Superseded history keeps its facts exactly.
            var historical = byRun[succeeding.Lease.ProcessingRunId].Single(x => x.Id != succeeding.AnalysisId);
            Assert.Equal(3, await db.VisualAttributeTrackOutcomes.CountAsync(x => x.AnalysisId == historical.Id));
        }

        var current = await ReadinessAsync(host, succeeding.Lease.ProcessingRunId);
        Assert.Contains("\"Ready\"", current, StringComparison.Ordinal);
        Assert.Contains($"\"defaultAnalysisId\":\"{succeeding.AnalysisId}\"", current, StringComparison.Ordinal);
        var stale = await ReadinessAsync(host, failing.Lease.ProcessingRunId);
        Assert.Contains("\"Stale\"", stale, StringComparison.Ordinal);
        Assert.Contains("preferred_failed", stale, StringComparison.Ordinal);

        // Rollback to A: the superseded A analysis becomes the derived default again.
        await host.RestartWithAsync(identityB: false);
        var rolledBack = await ReadinessAsync(host, succeeding.Lease.ProcessingRunId);
        Assert.Contains("\"Ready\"", rolledBack, StringComparison.Ordinal);
        Assert.DoesNotContain($"\"defaultAnalysisId\":\"{succeeding.AnalysisId}\"", rolledBack, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ReadinessSaysWhenNoReadyWorkerHasPolled()
    {
        var (host, run) = await HostWithQueuedRunAsync();
        await using var owned = host;

        var before = await ReadinessAsync(host, run.RunId);
        Assert.Contains("\"Pending\"", before, StringComparison.Ordinal);
        Assert.Contains(VisualAttributeReadinessRule.NoReadyWorker, before, StringComparison.Ordinal);

        // A worker polling for another identity is not a READY worker for this one.
        using (await host.PostLeaseAsync("attributes-other", new string('9', 64))) { }
        Assert.Contains(VisualAttributeReadinessRule.NoReadyWorker, await ReadinessAsync(host, run.RunId), StringComparison.Ordinal);

        using (await host.PostLeaseAsync("attributes-01")) { }
        var after = await ReadinessAsync(host, run.RunId);
        Assert.DoesNotContain(VisualAttributeReadinessRule.NoReadyWorker, after, StringComparison.Ordinal);
        Assert.Contains("\"running\"", after, StringComparison.Ordinal);

        // Presence ages out: a silent worker is no longer proof of readiness.
        host.World.Clock.Advance(TimeSpan.FromMinutes(4));
        Assert.Contains(VisualAttributeReadinessRule.NoReadyWorker, await ReadinessAsync(host, run.RunId), StringComparison.Ordinal);
    }
}
