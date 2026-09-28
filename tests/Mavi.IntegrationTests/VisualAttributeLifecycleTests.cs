using Mavi.Application.Modules.VisualAttributes;
using Mavi.Application.Modules.VisualAttributes.Release;
using Mavi.Domain.VisualAttributes;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.Infrastructure.Security;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>
/// Queueing, claim, heartbeat, failure, sweep and evidence authorisation against PostgreSQL
/// (S2b plan §7, §8, §10, §16).
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisualAttributeLifecycleTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);
    private static readonly VisualAttributeLeasePolicy Policy = new(
        TimeSpan.FromMinutes(2), TimeSpan.FromMinutes(2), 3, TimeSpan.FromHours(1));
    private static readonly VisualAttributeReleaseDefinition A = VisualAttributeReleaseFixture.Definition();
    private static readonly VisualAttributeReleaseDefinition B = VisualAttributeReleaseFixture.Definition(identityB: true);

    private static VisualAttributeLifecycle Lifecycle(VisualAttributeWorld world) =>
        new(world.Read(), world.Clock, new LeaseCapabilityService());

    private async Task<(VisualAttributeWorld World, SeededRun Run, DateTimeOffset Activated)> WorldWithQueuedUnitAsync(
        int persons = 2, int vehicles = 1, int observations = 2)
    {
        var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var activated = await Lifecycle(world).EnsureActivationAsync(A, CancellationToken.None);
        world.Clock.Advance(TimeSpan.FromSeconds(1));
        var run = await world.SeedRunAsync(persons, vehicles, observations, completedAtUtc: world.Clock.GetUtcNow());
        Assert.Equal(1, await Lifecycle(world).QueueEligibleAsync(A, activated, 100, CancellationToken.None));
        return (world, run, activated);
    }

    private static async Task<VisualAttributeAnalysis> UnitAsync(VisualAttributeWorld world, Guid runId)
    {
        await using var db = world.Read();
        return await db.VisualAttributeAnalyses.AsNoTracking().SingleAsync(x => x.ProcessingRunId == runId);
    }

    // --- Queueing ----------------------------------------------------------------------------

    [Fact]
    public async Task OnlyVisibleApplicableRunsOfTheCurrentActivationAreQueued()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var history = await world.SeedRunAsync(1, 0, completedAtUtc: Now.AddMinutes(-5));
        var activated = await Lifecycle(world).EnsureActivationAsync(A, CancellationToken.None);
        world.Clock.Advance(TimeSpan.FromMinutes(1));
        var current = await world.SeedRunAsync(1, 1, completedAtUtc: world.Clock.GetUtcNow());
        var invisible = await world.SeedRunAsync(1, 0, visible: false, completedAtUtc: world.Clock.GetUtcNow());
        var empty = await world.SeedRunAsync(0, 0, completedAtUtc: world.Clock.GetUtcNow());

        Assert.Equal(1, await Lifecycle(world).QueueEligibleAsync(A, activated, 100, CancellationToken.None));
        // Idempotent: the unit exists now.
        Assert.Equal(0, await Lifecycle(world).QueueEligibleAsync(A, activated, 100, CancellationToken.None));

        await using var db = world.Read();
        var units = await db.VisualAttributeAnalyses.AsNoTracking().ToListAsync();
        var unit = Assert.Single(units);
        Assert.Equal(current.RunId, unit.ProcessingRunId);
        Assert.Equal(A.Identity.Fingerprint, unit.IdentityFingerprint);
        Assert.Equal(0, unit.AttemptCount);
        Assert.DoesNotContain(units, x => x.ProcessingRunId == history.RunId || x.ProcessingRunId == invisible.RunId || x.ProcessingRunId == empty.RunId);
    }

    [Fact]
    public async Task ConcurrentReconcilersCreateOneUnit()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var activated = await Lifecycle(world).EnsureActivationAsync(A, CancellationToken.None);
        world.Clock.Advance(TimeSpan.FromSeconds(1));
        var run = await world.SeedRunAsync(1, 0, completedAtUtc: world.Clock.GetUtcNow());

        var results = await Task.WhenAll(Enumerable.Range(0, 6).Select(_ =>
            Lifecycle(world).QueueEligibleAsync(A, activated, 100, CancellationToken.None)));

        Assert.Equal(1, results.Sum());
        await using var db = world.Read();
        Assert.Equal(1, await db.VisualAttributeAnalyses.CountAsync(x => x.ProcessingRunId == run.RunId));
    }

    [Fact]
    public async Task ARollbackStartsANewActivationSoHistoryIsNotBackfilled()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var firstA = await Lifecycle(world).EnsureActivationAsync(A, CancellationToken.None);
        world.Clock.Advance(TimeSpan.FromMinutes(1));
        var activatedB = await Lifecycle(world).EnsureActivationAsync(B, CancellationToken.None);
        world.Clock.Advance(TimeSpan.FromMinutes(1));
        var duringB = await world.SeedRunAsync(1, 0, completedAtUtc: world.Clock.GetUtcNow());
        world.Clock.Advance(TimeSpan.FromMinutes(1));
        var secondA = await Lifecycle(world).EnsureActivationAsync(A, CancellationToken.None);

        Assert.True(activatedB > firstA);
        Assert.True(secondA > activatedB);
        // Unchanged preferred identity: the same activation, not a new one.
        Assert.Equal(secondA, await Lifecycle(world).EnsureActivationAsync(A, CancellationToken.None));
        // The run completed under B is not re-analysed for A automatically.
        Assert.Equal(0, await Lifecycle(world).QueueEligibleAsync(A, secondA, 100, CancellationToken.None));
        await using var db = world.Read();
        Assert.False(await db.VisualAttributeAnalyses.AnyAsync(x => x.ProcessingRunId == duringB.RunId));
    }

    // --- Claim --------------------------------------------------------------------------------

    [Fact]
    public async Task AClaimGrantsTheRunsApplicableEvidenceAndConsumesOneAttempt()
    {
        var (world, run, _) = await WorldWithQueuedUnitAsync(persons: 2, vehicles: 1, observations: 3);
        using var owned = world;

        var grant = await Lifecycle(world).ClaimNextAsync("attributes-01", A.Identity.Fingerprint, Policy, CancellationToken.None);

        Assert.NotNull(grant);
        Assert.Equal(run.RunId, grant.ProcessingRunId);
        Assert.Equal(1, grant.AttemptCount);
        Assert.Equal(43, grant.LeaseToken.Length);
        Assert.Equal(Now.AddSeconds(1) + Policy.LeaseDuration, grant.LeaseExpiresAtUtc);
        Assert.Equal(Now.AddSeconds(1) + Policy.MaximumAnalysisDuration, grant.DeadlineAtUtc);
        Assert.Equal(3, grant.Tracks.Count);
        Assert.Equal(["person", "person", "vehicle"], grant.Tracks.Select(track => track.ObjectClass));
        var first = grant.Tracks[0];
        Assert.Equal(run.Track(0).TrackId, first.TrackId);
        Assert.Equal(["representative", "near-view", "early-diverse"], first.Observations.Select(item => item.Role));
        Assert.Equal(run.Track(0).Observations.Select(item => item.Sha256), first.Observations.Select(item => item.Sha256));
        Assert.Equal(run.Track(0).Observations.Select(item => (long)item.Bytes.Length), first.Observations.Select(item => item.SizeBytes));

        var unit = await UnitAsync(world, run.RunId);
        Assert.Equal(VisualAttributeAnalysisStatus.Running, unit.Status);
        Assert.Equal(1, unit.AttemptCount);
        // Only the hash is stored.
        Assert.NotNull(unit.LeaseTokenHash);
        Assert.DoesNotContain(grant.LeaseToken, System.Text.Encoding.ASCII.GetString(unit.LeaseTokenHash!), StringComparison.Ordinal);
    }

    [Fact]
    public async Task AWorkerOfAnotherIdentityNeverClaimsOrConsumesAnAttempt()
    {
        var (world, run, _) = await WorldWithQueuedUnitAsync();
        using var owned = world;
        // B is activated too, so its worker passes every pre-check and only the claim's
        // identity predicate stands between it and A's unit.
        world.Clock.Advance(TimeSpan.FromSeconds(1));
        await Lifecycle(world).EnsureActivationAsync(B, CancellationToken.None);

        Assert.Null(await Lifecycle(world).ClaimNextAsync("attributes-02", B.Identity.Fingerprint, Policy, CancellationToken.None));
        Assert.Null(await Lifecycle(world).ClaimNextAsync("attributes-02", new string('9', 64), Policy, CancellationToken.None));

        var unit = await UnitAsync(world, run.RunId);
        Assert.Equal(VisualAttributeAnalysisStatus.Queued, unit.Status);
        Assert.Equal(0, unit.AttemptCount);
    }

    [Fact]
    public async Task ConcurrentClaimsGrantTheUnitOnce()
    {
        var (world, run, _) = await WorldWithQueuedUnitAsync();
        using var owned = world;

        var grants = await Task.WhenAll(Enumerable.Range(0, 8).Select(index =>
            Lifecycle(world).ClaimNextAsync($"attributes-{index:00}", A.Identity.Fingerprint, Policy, CancellationToken.None)));

        Assert.Single(grants, grant => grant is not null);
        Assert.Equal(1, (await UnitAsync(world, run.RunId)).AttemptCount);
    }

    [Fact]
    public async Task AnExpiredLeaseIsReclaimedAndTheStaleAttemptLosesEveryOperation()
    {
        var (world, run, _) = await WorldWithQueuedUnitAsync();
        using var owned = world;
        var first = (await Lifecycle(world).ClaimNextAsync("attributes-01", A.Identity.Fingerprint, Policy, CancellationToken.None))!;

        Assert.Null(await Lifecycle(world).ClaimNextAsync("attributes-02", A.Identity.Fingerprint, Policy, CancellationToken.None));
        world.Clock.Advance(Policy.LeaseDuration);
        var second = (await Lifecycle(world).ClaimNextAsync("attributes-02", A.Identity.Fingerprint, Policy, CancellationToken.None))!;
        Assert.Equal(2, second.AttemptCount);

        var heartbeat = await Lifecycle(world).HeartbeatAsync(first.AnalysisId, "attributes-01", first.LeaseToken, 1, Policy, CancellationToken.None);
        Assert.Equal("visual_attribute_lease_invalid", heartbeat.Refusal!.Code);
        var fail = await Lifecycle(world).FailAsync(first.AnalysisId, "attributes-01", first.LeaseToken, 1,
            "visual_attribute_inference_failed", true, null, Policy, CancellationToken.None);
        Assert.Equal("visual_attribute_lease_invalid", fail.Refusal!.Code);
        var read = await Lifecycle(world).AuthorizeEvidenceReadAsync(first.AnalysisId, "attributes-01", first.LeaseToken, 1,
            run.Track(0).Observations[0].ObservationId, CancellationToken.None);
        Assert.Equal("visual_attribute_lease_invalid", read.Refusal!.Code);
        Assert.True((await Lifecycle(world).HeartbeatAsync(second.AnalysisId, "attributes-02", second.LeaseToken, 2, Policy, CancellationToken.None)).IsSuccess);
    }

    // --- Heartbeat -----------------------------------------------------------------------------

    [Fact]
    public async Task AHeartbeatExtendsTheLeaseButCannotReviveAnExpiredOne()
    {
        var (world, _, _) = await WorldWithQueuedUnitAsync();
        using var owned = world;
        var grant = (await Lifecycle(world).ClaimNextAsync("attributes-01", A.Identity.Fingerprint, Policy, CancellationToken.None))!;

        world.Clock.Advance(TimeSpan.FromSeconds(90));
        var extended = await Lifecycle(world).HeartbeatAsync(grant.AnalysisId, "attributes-01", grant.LeaseToken, 1, Policy, CancellationToken.None);
        Assert.Equal(world.Clock.GetUtcNow() + Policy.HeartbeatExtension, extended.LeaseExpiresAtUtc);

        world.Clock.Advance(Policy.HeartbeatExtension);
        var late = await Lifecycle(world).HeartbeatAsync(grant.AnalysisId, "attributes-01", grant.LeaseToken, 1, Policy, CancellationToken.None);
        Assert.Equal("visual_attribute_lease_invalid", late.Refusal!.Code);
    }

    // --- Failure -------------------------------------------------------------------------------

    [Fact]
    public async Task ARetryableFailureRequeuesOnceAndItsReplayWritesNothing()
    {
        var (world, run, _) = await WorldWithQueuedUnitAsync();
        using var owned = world;
        var grant = (await Lifecycle(world).ClaimNextAsync("attributes-01", A.Identity.Fingerprint, Policy, CancellationToken.None))!;

        var failed = await Lifecycle(world).FailAsync(grant.AnalysisId, "attributes-01", grant.LeaseToken, 1,
            "visual_attribute_evidence_transport_failed", true, "reset", Policy, CancellationToken.None);
        var replay = await Lifecycle(world).FailAsync(grant.AnalysisId, "attributes-01", grant.LeaseToken, 1,
            "visual_attribute_evidence_transport_failed", true, "reset", Policy, CancellationToken.None);
        var different = await Lifecycle(world).FailAsync(grant.AnalysisId, "attributes-01", grant.LeaseToken, 1,
            "visual_attribute_output_invalid", false, null, Policy, CancellationToken.None);

        Assert.Equal(VisualAttributeFailOutcome.Requeued, failed.Outcome);
        Assert.Equal(VisualAttributeFailOutcome.Requeued, replay.Outcome);
        Assert.Equal("visual_attribute_not_running", different.Refusal!.Code);
        var unit = await UnitAsync(world, run.RunId);
        Assert.Equal(VisualAttributeAnalysisStatus.Queued, unit.Status);
        await using var db = world.Read();
        var history = Assert.Single(await db.VisualAttributeAttemptFailures.AsNoTracking().ToListAsync());
        Assert.Equal(1, history.AttemptNumber);
        Assert.True(history.Retryable);
        // The next claim is attempt 2.
        Assert.Equal(2, (await Lifecycle(world).ClaimNextAsync("attributes-02", A.Identity.Fingerprint, Policy, CancellationToken.None))!.AttemptCount);
    }

    [Fact]
    public async Task ATerminalFailureEndsTheUnit()
    {
        var (world, run, _) = await WorldWithQueuedUnitAsync();
        using var owned = world;
        var grant = (await Lifecycle(world).ClaimNextAsync("attributes-01", A.Identity.Fingerprint, Policy, CancellationToken.None))!;

        var failed = await Lifecycle(world).FailAsync(grant.AnalysisId, "attributes-01", grant.LeaseToken, 1,
            "visual_attribute_output_invalid", false, null, Policy, CancellationToken.None);

        Assert.Equal(VisualAttributeFailOutcome.Failed, failed.Outcome);
        Assert.Equal(VisualAttributeAnalysisStatus.Failed, (await UnitAsync(world, run.RunId)).Status);
        Assert.Null(await Lifecycle(world).ClaimNextAsync("attributes-02", A.Identity.Fingerprint, Policy, CancellationToken.None));
    }

    // --- Platform authority --------------------------------------------------------------------

    [Fact]
    public async Task TheDeadlineIsEnforcedWithNoWorkerPolling()
    {
        var (world, run, _) = await WorldWithQueuedUnitAsync();
        using var owned = world;
        // Queued long before the first claim: the deadline counts from the claim, not the queue.
        world.Clock.Advance(TimeSpan.FromHours(5));
        _ = await Lifecycle(world).ClaimNextAsync("attributes-01", A.Identity.Fingerprint, Policy, CancellationToken.None);

        world.Clock.Advance(Policy.MaximumAnalysisDuration - TimeSpan.FromSeconds(1));
        Assert.Equal(new VisualAttributeSweepResult(0, 0), await Lifecycle(world).SweepAsync(Policy, 100, CancellationToken.None));
        world.Clock.Advance(TimeSpan.FromSeconds(1));
        Assert.Equal(1, (await Lifecycle(world).SweepAsync(Policy, 100, CancellationToken.None)).DeadlineFailed);

        var unit = await UnitAsync(world, run.RunId);
        Assert.Equal(VisualAttributeAnalysisStatus.Failed, unit.Status);
        Assert.Equal("visual_attribute_deadline_exceeded", unit.FailureCode);
    }

    [Fact]
    public async Task AUnitPastItsDeadlineNeverStarvesQueuedWork()
    {
        var (world, _, activated) = await WorldWithQueuedUnitAsync();
        using var owned = world;
        var second = await world.SeedRunAsync(1, 0, 1, completedAtUtc: world.Clock.GetUtcNow());
        Assert.Equal(1, await Lifecycle(world).QueueEligibleAsync(A, activated, 100, CancellationToken.None));
        var first = (await Lifecycle(world).ClaimNextAsync("attributes-01", A.Identity.Fingerprint, Policy, CancellationToken.None))!;

        // The first unit's lease and deadline have both passed and no sweep has run yet: the
        // claim must pass it over for the queued unit rather than select it and give up.
        world.Clock.Advance(Policy.MaximumAnalysisDuration + TimeSpan.FromSeconds(1));
        var next = await Lifecycle(world).ClaimNextAsync("attributes-02", A.Identity.Fingerprint, Policy, CancellationToken.None);

        Assert.NotNull(next);
        Assert.NotEqual(first.AnalysisId, next.AnalysisId);
        Assert.Equal(second.RunId, next.ProcessingRunId);
    }

    [Fact]
    public async Task NeverClaimedWorkDoesNotFailOnTheClock()
    {
        var (world, run, _) = await WorldWithQueuedUnitAsync();
        using var owned = world;
        world.Clock.Advance(TimeSpan.FromDays(30));

        Assert.Equal(new VisualAttributeSweepResult(0, 0), await Lifecycle(world).SweepAsync(Policy, 100, CancellationToken.None));
        Assert.Equal(VisualAttributeAnalysisStatus.Queued, (await UnitAsync(world, run.RunId)).Status);
    }

    [Fact]
    public async Task TheLastAttemptsExpiredLeaseIsExhaustedWithNoWorkerPolling()
    {
        var (world, run, _) = await WorldWithQueuedUnitAsync();
        using var owned = world;
        for (var attempt = 1; attempt <= Policy.MaximumAttempts; attempt++)
        {
            Assert.NotNull(await Lifecycle(world).ClaimNextAsync("attributes-01", A.Identity.Fingerprint, Policy, CancellationToken.None));
            world.Clock.Advance(Policy.LeaseDuration);
        }

        Assert.Null(await Lifecycle(world).ClaimNextAsync("attributes-01", A.Identity.Fingerprint, Policy, CancellationToken.None));
        Assert.Equal(1, (await Lifecycle(world).SweepAsync(Policy, 100, CancellationToken.None)).ExhaustedFailed);
        var unit = await UnitAsync(world, run.RunId);
        Assert.Equal("visual_attribute_attempts_exhausted", unit.FailureCode);
    }

    // --- Evidence authorisation ----------------------------------------------------------------

    [Fact]
    public async Task EvidenceIsAuthorisedOnlyForTheLeasedRunsAcceptedCrops()
    {
        var (world, run, _) = await WorldWithQueuedUnitAsync();
        using var owned = world;
        var other = await world.SeedRunAsync(1, 0);
        var grant = (await Lifecycle(world).ClaimNextAsync("attributes-01", A.Identity.Fingerprint, Policy, CancellationToken.None))!;

        var own = await Lifecycle(world).AuthorizeEvidenceReadAsync(grant.AnalysisId, "attributes-01", grant.LeaseToken, 1,
            run.Track(1).Observations[1].ObservationId, CancellationToken.None);
        Assert.True(own.IsAuthorised);
        Assert.Equal(run.Track(1).Observations[1].StorageKey, own.Grant!.StorageKey);
        Assert.Equal(run.Track(1).Observations[1].Sha256, own.Grant.Sha256);

        // Cross-run IDOR: a real Observation of another run is refused.
        var foreign = await Lifecycle(world).AuthorizeEvidenceReadAsync(grant.AnalysisId, "attributes-01", grant.LeaseToken, 1,
            other.Track(0).Observations[0].ObservationId, CancellationToken.None);
        Assert.Equal("visual_attribute_evidence_forbidden", foreign.Refusal!.Code);
        var missing = await Lifecycle(world).AuthorizeEvidenceReadAsync(grant.AnalysisId, "attributes-01", grant.LeaseToken, 1,
            Guid.CreateVersion7(), CancellationToken.None);
        Assert.Equal("visual_attribute_evidence_forbidden", missing.Refusal!.Code);
        var wrongToken = await Lifecycle(world).AuthorizeEvidenceReadAsync(grant.AnalysisId, "attributes-01", new LeaseCapabilityService().Create().Token, 1,
            run.Track(0).Observations[0].ObservationId, CancellationToken.None);
        Assert.Equal("visual_attribute_lease_invalid", wrongToken.Refusal!.Code);
        var wrongAttempt = await Lifecycle(world).AuthorizeEvidenceReadAsync(grant.AnalysisId, "attributes-01", grant.LeaseToken, 2,
            run.Track(0).Observations[0].ObservationId, CancellationToken.None);
        Assert.Equal("visual_attribute_lease_invalid", wrongAttempt.Refusal!.Code);

        world.Clock.Advance(Policy.LeaseDuration);
        var expired = await Lifecycle(world).AuthorizeEvidenceReadAsync(grant.AnalysisId, "attributes-01", grant.LeaseToken, 1,
            run.Track(0).Observations[0].ObservationId, CancellationToken.None);
        Assert.Equal("visual_attribute_lease_invalid", expired.Refusal!.Code);
    }
}
