using System.Security.Cryptography;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// The finalizer's transactions against PostgreSQL (F3 plan §7.1–§7.3, §7.5–§7.8; slice 4):
/// claim exclusivity and rotation, the absolute deadline at every layer, canonical and
/// malformed claim states, fenced notes and failures, tokenless exhaustion, payload cleanup
/// and the health counts.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisionFinalizationLifecycleTests
{
    // -- claim ----------------------------------------------------------------------------------

    [Fact]
    public async Task ClaimTakesTheOldestFinalizingJobAndCommitsBeforeReturning()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var first = await world.HandOffAsync(cameraCode: "CAM-1");
        world.Clock.Advance(TimeSpan.FromSeconds(1));
        var second = await world.HandOffAsync(cameraCode: "CAM-2");
        world.Clock.Advance(TimeSpan.FromSeconds(1));

        var claim = await world.ClaimAsync();

        Assert.NotNull(claim);
        Assert.Equal(first.Lease.JobId, claim.JobId);
        Assert.Equal(first.Lease.ProcessingRunId, claim.ProcessingRunId);
        Assert.Equal(first.Lease.VideoAssetId, claim.VideoAssetId);
        Assert.Equal(first.Lease.AttemptCount, claim.AttemptCount);
        Assert.Equal(1, claim.FinalizationAttemptCount);
        Assert.Equal(32, claim.ClaimToken.Length);
        Assert.Equal(world.Clock.GetUtcNow().AddMinutes(5), claim.ClaimExpiresAtUtc);
        Assert.Equal(first.Ack.AcceptedAtUtc.AddHours(6), claim.FinalizationDeadlineUtc);
        Assert.DoesNotContain(Convert.ToBase64String(claim.ClaimToken.ToArray()), claim.ToString(), StringComparison.Ordinal);

        var job = await world.JobAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal(1, job.FinalizationAttemptCount);
        Assert.Equal(SHA256.HashData(claim.ClaimToken.ToArray()), job.FinalizationClaimTokenHash);
        Assert.Equal(claim.ClaimExpiresAtUtc, job.FinalizationClaimExpiresAtUtc);
        Assert.Equal(world.Clock.GetUtcNow(), job.FinalizationClaimExtendedAtUtc);
        Assert.Equal(FinalizationClaimState.Live, job.FinalizationClaimStateAt(world.Clock.GetUtcNow()));

        var next = await world.ClaimAsync();
        Assert.NotNull(next);
        Assert.Equal(second.Lease.JobId, next.JobId);
        Assert.Null(await world.ClaimAsync());
    }

    [Fact]
    public async Task ClaimIsExclusiveUnderConcurrency()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();

        var policy = world.Policy with { MaximumAttempts = 20 };
        var winners = new List<VisionFinalizationClaim>();
        for (var round = 0; round < 10; round++)
        {
            var claims = await Task.WhenAll(Enumerable.Range(0, 6).Select(_ => world.ClaimAsync(policy)));
            winners.AddRange(claims.Where(x => x is not null)!);
            // Hand the job back by expiring the claim so the next round contends again.
            world.Clock.Advance(TimeSpan.FromMinutes(6));
        }

        Assert.Equal(10, winners.Count);
        Assert.All(winners, x => Assert.Equal(handOff.Lease.JobId, x.JobId));
        Assert.Equal(10, winners.Select(x => Convert.ToHexString(x.ClaimToken.Span)).Distinct().Count());
        Assert.Equal(Enumerable.Range(1, 10), winners.Select(x => x.FinalizationAttemptCount).Order());
    }

    [Fact]
    public async Task ExpiredClaimIsReclaimedWithARotatedTokenAndTheOldTokenIsDead()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var first = (await world.ClaimAsync())!;
        Assert.Null(await world.ClaimAsync());

        world.Clock.Advance(TimeSpan.FromMinutes(5));
        var second = (await world.ClaimAsync())!;

        Assert.Equal(2, second.FinalizationAttemptCount);
        Assert.NotEqual(first.ClaimToken.ToArray(), second.ClaimToken.ToArray());
        var job = await world.JobAsync(first.JobId);
        Assert.True(job.FinalizationOwnedBy(second.ClaimToken.Span, world.Clock.GetUtcNow()));
        Assert.False(job.FinalizationOwnedBy(first.ClaimToken.Span, world.Clock.GetUtcNow()));
    }

    [Fact]
    public async Task ClaimStopsAtMaximumAttempts()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var policy = world.Policy with { MaximumAttempts = 2 };

        Assert.NotNull(await world.ClaimAsync(policy));
        world.Clock.Advance(TimeSpan.FromMinutes(6));
        Assert.NotNull(await world.ClaimAsync(policy));
        world.Clock.Advance(TimeSpan.FromMinutes(6));

        Assert.Null(await world.ClaimAsync(policy));
        Assert.Equal(2, (await world.JobAsync((await world.StateAsync((await AnyJobIdAsync(world)))).Job.Id)).FinalizationAttemptCount);
    }

    // -- the absolute deadline at every layer (F3 plan §5.4, §8.6) -----------------------------

    [Fact]
    public async Task NoNewClaimAfterMaximumFinalizationDuration()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var deadline = handOff.Ack.AcceptedAtUtc.Add(world.Policy.MaximumDuration);

        world.Clock.Advance(deadline - world.Clock.GetUtcNow());
        world.Sql.Clear();
        Assert.Null(await world.ClaimAsync());
        Assert.Contains(world.Sql.Commands, x => x.Contains("FOR UPDATE SKIP LOCKED", StringComparison.Ordinal));

        world.Clock.Advance(TimeSpan.FromHours(1));
        Assert.Null(await world.ClaimAsync());

        var job = await world.JobAsync(handOff.Lease.JobId);
        Assert.Equal(0, job.FinalizationAttemptCount);
        Assert.Equal(FinalizationClaimState.Unclaimed, job.FinalizationClaimStateAt(world.Clock.GetUtcNow()));
    }

    [Fact]
    public async Task ClaimSqlAndDomainAgreeAtTheDeadlineInstant()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var deadline = handOff.Ack.AcceptedAtUtc.Add(world.Policy.MaximumDuration);

        // One tick before: SQL selects, the domain claims.
        world.Clock.Advance(deadline.AddTicks(-1) - world.Clock.GetUtcNow());
        // PostgreSQL keeps microseconds, so "one tick before" must be a whole microsecond before.
        world.Clock.Advance(TimeSpan.FromTicks(-9));
        var claim = await world.ClaimAsync();
        Assert.NotNull(claim);
        await world.SetClaimTripleAsync(claim.JobId, null, null, null); // back to unclaimed for the boundary itself
        await world.ExecuteSqlAsync("UPDATE vision_jobs SET finalization_attempt_count = 0 WHERE id = $1", claim.JobId);

        // At the instant: SQL does not select, and forcing the domain transition on the locked row throws.
        world.Clock.Advance(deadline - world.Clock.GetUtcNow());
        Assert.Null(await world.ClaimAsync());
        using var scope = world.Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        await using var transaction = await db.Database.BeginTransactionAsync();
        var locked = await db.VisionJobs.FromSqlInterpolated($"SELECT * FROM vision_jobs WHERE id = {claim.JobId} FOR UPDATE").SingleAsync();
        Assert.False(locked.CanClaimFinalization(world.Clock.GetUtcNow(), world.Policy.MaximumAttempts, world.Policy.MaximumDuration));
        Assert.Throws<Mavi.Domain.Common.DomainValidationException>(() =>
            locked.ClaimFinalization(new byte[32], world.Clock.GetUtcNow(), world.Policy.ClaimDuration, world.Policy.MaximumAttempts, world.Policy.MaximumDuration));
        await transaction.RollbackAsync();
        Assert.Equal(0, (await world.JobAsync(claim.JobId)).FinalizationAttemptCount);
    }

    [Fact]
    public async Task ClaimCanBeExtendedBeforeAndNotAtOrAfterMaximumFinalizationDuration()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var deadline = handOff.Ack.AcceptedAtUtc.Add(world.Policy.MaximumDuration);
        world.Clock.Advance(deadline.AddMinutes(-3) - world.Clock.GetUtcNow());
        var claim = (await world.ClaimAsync())!;

        world.Clock.Advance(TimeSpan.FromMinutes(1));
        var before = await world.WithLifecycleAsync(l => l.ExtendClaimAsync(claim, world.Policy, CancellationToken.None));
        Assert.Equal(VisionFinalizationClaimStatus.Live, before.Status);
        Assert.Equal(world.Clock.GetUtcNow().AddMinutes(5), before.ClaimExpiresAtUtc);

        world.Clock.Advance(TimeSpan.FromMinutes(2)); // now == deadline
        var at = await world.WithLifecycleAsync(l => l.ExtendClaimAsync(claim, world.Policy, CancellationToken.None));
        Assert.Equal(VisionFinalizationClaimStatus.DeadlineReached, at.Status);
        Assert.Equal(before.ClaimExpiresAtUtc, at.ClaimExpiresAtUtc);

        world.Clock.Advance(TimeSpan.FromMinutes(1));
        var after = await world.WithLifecycleAsync(l => l.ExtendClaimAsync(claim, world.Policy, CancellationToken.None));
        Assert.Equal(VisionFinalizationClaimStatus.DeadlineReached, after.Status);

        var job = await world.JobAsync(claim.JobId);
        Assert.Equal(before.ClaimExpiresAtUtc, job.FinalizationClaimExpiresAtUtc);
        Assert.True(job.FinalizationOwnedBy(claim.ClaimToken.Span, world.Clock.GetUtcNow()), "ownership is intact; only renewal is refused");
    }

    [Fact]
    public async Task DurationExceededLiveClaimIsNotKilledImmediatelyAndIsExhaustedAfterItExpires()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var deadline = handOff.Ack.AcceptedAtUtc.Add(world.Policy.MaximumDuration);
        world.Clock.Advance(deadline.AddMinutes(-1) - world.Clock.GetUtcNow());
        var claim = (await world.ClaimAsync())!;

        world.Clock.Advance(TimeSpan.FromMinutes(2)); // past the deadline, claim live for 3 more minutes
        var live = await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(world.Policy, 10, CancellationToken.None));
        Assert.Equal(0, live.Exhausted);
        Assert.Empty(live.InvariantJobIds);
        Assert.Equal(VisionJobStatus.Finalizing, (await world.JobAsync(claim.JobId)).Status);
        Assert.Null(await world.ClaimAsync());

        world.Clock.Advance(TimeSpan.FromMinutes(3)); // claim expired
        Assert.Null(await world.ClaimAsync());
        var exhausted = await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(world.Policy, 10, CancellationToken.None));

        Assert.Equal(1, exhausted.Exhausted);
        var (job, run, video) = await world.StateAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Failed, job.Status);
        Assert.Equal("vision_finalization_exhausted", job.FailureCode);
        Assert.Equal(ProcessingRunStatus.Failed, run.Status);
        Assert.Equal("vision_finalization_exhausted", run.ErrorCode);
        Assert.Equal(VideoProcessingStatus.Failed, video.ProcessingStatus);
        Assert.Equal(0, await world.TrackCountAsync(run.Id));
        Assert.Null(run.VisibilitySequence);
    }

    // -- fenced writes -----------------------------------------------------------------------

    [Fact]
    public async Task StaleClaimantCannotExtendFailOrNote()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var stale = (await world.ClaimAsync())!;
        world.Clock.Advance(TimeSpan.FromMinutes(6));
        var live = (await world.ClaimAsync())!;
        var before = await world.JobAsync(live.JobId);

        var extension = await world.WithLifecycleAsync(l => l.ExtendClaimAsync(stale, world.Policy, CancellationToken.None));
        var failure = await world.WithLifecycleAsync(l => l.FailAsync(stale, VisionFinalizationFailureCodes.PayloadInvalid, "stale", CancellationToken.None));
        var note = await world.WithLifecycleAsync(l => l.NoteTransientAsync(stale, VisionFinalizationFailureCodes.IoTransient, true, CancellationToken.None));
        var noteWithoutRelease = await world.WithLifecycleAsync(l => l.NoteTransientAsync(stale, VisionFinalizationFailureCodes.DbTransient, false, CancellationToken.None));

        Assert.Equal(VisionFinalizationClaimStatus.Lost, extension.Status);
        Assert.Equal(VisionFinalizationTransitionKind.Stale, failure.Kind);
        Assert.Equal(VisionFinalizationTransitionKind.Stale, note.Kind);
        Assert.Equal(VisionFinalizationTransitionKind.Stale, noteWithoutRelease.Kind);
        var after = await world.JobAsync(live.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, after.Status);
        Assert.Null(after.FailureCode);
        Assert.Null(after.FinalizationLastErrorCode);
        Assert.Equal(before.FinalizationClaimExpiresAtUtc, after.FinalizationClaimExpiresAtUtc);
        Assert.Equal(before.FinalizationClaimTokenHash, after.FinalizationClaimTokenHash);
        Assert.True(after.FinalizationOwnedBy(live.ClaimToken.Span, world.Clock.GetUtcNow()));
    }

    [Fact]
    public async Task LiveClaimantNotesATransientAndReleasesForTheNextCycle()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        world.Clock.Advance(TimeSpan.FromSeconds(10));

        var note = await world.WithLifecycleAsync(l => l.NoteTransientAsync(claim, VisionFinalizationFailureCodes.IoTransient, true, CancellationToken.None));

        Assert.Equal(VisionFinalizationTransitionKind.Noted, note.Kind);
        var job = await world.JobAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, job.Status);
        Assert.Equal("vision_finalization_io_transient", job.FinalizationLastErrorCode);
        Assert.Null(job.FailureCode);
        Assert.Equal(world.Clock.GetUtcNow(), job.FinalizationClaimExpiresAtUtc);
        Assert.NotNull(job.FinalizationClaimTokenHash);
        Assert.Equal(FinalizationClaimState.Expired, job.FinalizationClaimStateAt(world.Clock.GetUtcNow()));
        // Reclaimable now, without waiting out the granted duration.
        var next = await world.ClaimAsync();
        Assert.NotNull(next);
        Assert.Equal(2, next.FinalizationAttemptCount);
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            world.WithLifecycleAsync(l => l.NoteTransientAsync(next, VisionFinalizationFailureCodes.PayloadInvalid, false, CancellationToken.None)).GetAwaiter().GetResult());
    }

    [Fact]
    public async Task LiveClaimantFailsTheJobRunAndVideoDeterministically()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        world.Clock.Advance(TimeSpan.FromSeconds(10));

        var failure = await world.WithLifecycleAsync(l => l.FailAsync(claim, VisionFinalizationFailureCodes.StagingMissing, "crops unit 3", CancellationToken.None));

        Assert.Equal(VisionFinalizationTransitionKind.Failed, failure.Kind);
        var (job, run, video) = await world.StateAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Failed, job.Status);
        Assert.Equal("vision_finalization_staging_missing", job.FailureCode);
        Assert.Equal("crops unit 3", job.FailureDetails);
        Assert.Equal(world.Clock.GetUtcNow(), job.CompletedAtUtc);
        Assert.Null(job.FinalizationClaimTokenHash);
        Assert.Null(job.FinalizationClaimExpiresAtUtc);
        Assert.Null(job.FinalizationClaimExtendedAtUtc);
        Assert.Equal(ProcessingRunStatus.Failed, run.Status);
        Assert.Equal("vision_finalization_staging_missing", run.ErrorCode);
        Assert.Equal(VideoProcessingStatus.Failed, video.ProcessingStatus);
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            world.WithLifecycleAsync(l => l.FailAsync(claim, VisionFinalizationFailureCodes.IoTransient, null, CancellationToken.None)).GetAwaiter().GetResult());
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            world.WithLifecycleAsync(l => l.FailAsync(claim, VisionFinalizationFailureCodes.Exhausted, null, CancellationToken.None)).GetAwaiter().GetResult());
    }

    // -- reconciliation (F3 plan §7.5) -------------------------------------------------------

    [Fact]
    public async Task FinalPermittedClaimantCrashIsExhaustedByReconciliation()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var policy = world.Policy with { MaximumAttempts = 1 };
        var claim = (await world.ClaimAsync(policy))!;
        // The host dies here. Nothing else touches the job.

        world.Clock.Advance(TimeSpan.FromMinutes(4));
        Assert.Equal(0, (await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(policy, 10, CancellationToken.None))).Exhausted);
        world.Clock.Advance(TimeSpan.FromMinutes(1)); // claim expired, attempts exhausted
        Assert.Null(await world.ClaimAsync(policy));
        var pass = await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(policy, 10, CancellationToken.None));

        Assert.Equal(1, pass.Exhausted);
        Assert.Empty(pass.MalformedJobIds);
        Assert.Empty(pass.InvariantJobIds);
        var (job, run, video) = await world.StateAsync(claim.JobId);
        Assert.Equal(VisionJobStatus.Failed, job.Status);
        Assert.Equal("vision_finalization_exhausted", job.FailureCode);
        Assert.Null(job.FailureDetails);
        Assert.Equal(handOff.Lease.AttemptCount, job.AttemptCount);
        Assert.Equal(1, job.FinalizationAttemptCount);
        Assert.NotNull(job.CompletionDigest);
        Assert.Equal(ProcessingRunStatus.Failed, run.Status);
        Assert.Equal(VideoProcessingStatus.Failed, video.ProcessingStatus);
        Assert.Equal(0, await world.TrackCountAsync(run.Id));
        Assert.Equal(0L, await world.VisibilityAllocationsAsync());
        Assert.Equal(0, (await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(policy, 10, CancellationToken.None))).Exhausted);
    }

    [Fact]
    public async Task ReconciliationSkipsALiveClaimAndARowLockedByAPublisher()
    {
        using var world = await FinalizationWorld.CreateAsync();
        await world.HandOffAsync();
        var policy = world.Policy with { MaximumAttempts = 1 };
        var claim = (await world.ClaimAsync(policy))!;

        // Live claim, attempts exhausted: excluded by the predicate (so never even refused by the domain).
        var live = await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(policy, 10, CancellationToken.None));
        Assert.Equal(0, live.Exhausted);
        Assert.Empty(live.InvariantJobIds);

        // Expired claim, but the row is locked by a publisher in another transaction: skipped.
        world.Clock.Advance(TimeSpan.FromMinutes(6));
        using var scope = world.Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        await using (var publisher = await db.Database.BeginTransactionAsync())
        {
            _ = await db.VisionJobs.FromSqlInterpolated($"SELECT * FROM vision_jobs WHERE id = {claim.JobId} FOR UPDATE").SingleAsync();
            var locked = await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(policy, 10, CancellationToken.None));
            Assert.Equal(0, locked.Exhausted);
            await publisher.RollbackAsync();
        }

        Assert.Equal(1, (await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(policy, 10, CancellationToken.None))).Exhausted);
    }

    // -- canonical and malformed claim states (F3 plan §5.2) ---------------------------------

    [Theory]
    [InlineData(true, false, false)]   // hash without expiry
    [InlineData(false, true, false)]   // expiry without hash
    [InlineData(true, true, false)]    // no extended-at
    [InlineData(false, false, true)]   // extended-at alone
    public async Task MalformedClaimIsNeverClaimedOrExhaustedAndIsReportedOnce(bool hash, bool expiry, bool extendedAt)
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var past = world.Clock.GetUtcNow().AddMinutes(-1);
        await world.SetClaimTripleAsync(handOff.Lease.JobId, hash ? new byte[32] : null, expiry ? past : null, extendedAt ? past : null);
        // Attempts remain and the deadline is ahead: an OR-shaped claim predicate would select
        // this row and the domain would refuse it, which surfaces as an exception, not a null.
        Assert.Null(await world.ClaimAsync());
        // Attempts and deadline both exhausted: an OR-shaped reconciliation rule would act on this row.
        await world.ExecuteSqlAsync("UPDATE vision_jobs SET finalization_attempt_count = 3 WHERE id = $1", handOff.Lease.JobId);
        world.Clock.Advance(TimeSpan.FromHours(7));
        var before = await world.JobAsync(handOff.Lease.JobId);
        Assert.Equal(FinalizationClaimState.Malformed, before.FinalizationClaimStateAt(world.Clock.GetUtcNow()));

        Assert.Null(await world.ClaimAsync());
        var first = await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(world.Policy, 10, CancellationToken.None));
        var second = await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(world.Policy, 10, CancellationToken.None));
        var counts = await world.WithLifecycleAsync(l => l.CountAsync(CancellationToken.None));

        Assert.Equal(0, first.Exhausted);
        Assert.Empty(first.InvariantJobIds); // never selected, so never refused by the domain either
        Assert.Empty(second.InvariantJobIds);
        Assert.Equal([handOff.Lease.JobId], first.MalformedJobIds);
        Assert.Equal([handOff.Lease.JobId], second.MalformedJobIds);
        Assert.Equal(1, counts.FinalizingJobs);
        Assert.Equal(0, counts.LiveClaims);
        Assert.Equal(1, counts.MalformedClaims);
        var after = await world.JobAsync(handOff.Lease.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, after.Status);
        Assert.Equal(before.FinalizationClaimTokenHash, after.FinalizationClaimTokenHash);
        Assert.Equal(before.FinalizationClaimExpiresAtUtc, after.FinalizationClaimExpiresAtUtc);
        Assert.Equal(before.FinalizationClaimExtendedAtUtc, after.FinalizationClaimExtendedAtUtc);
        Assert.Equal(3, after.FinalizationAttemptCount);
    }

    [Fact]
    public async Task CanonicalExpiredClaimIsReclaimableAndExhaustible()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var (_, hash) = FinalizationWorld.Token(3);
        var past = world.Clock.GetUtcNow().AddMinutes(-1);
        await world.SetClaimTripleAsync(handOff.Lease.JobId, hash, past, past.AddMinutes(-5));

        var claim = await world.ClaimAsync();
        Assert.NotNull(claim);
        Assert.Equal(1, claim.FinalizationAttemptCount);

        // Exhaustible once expired again and out of attempts.
        var policy = world.Policy with { MaximumAttempts = 1 };
        world.Clock.Advance(TimeSpan.FromMinutes(6));
        Assert.Equal(1, (await world.WithLifecycleAsync(l => l.ExhaustAbandonedAsync(policy, 10, CancellationToken.None))).Exhausted);
    }

    // -- inputs, counts and cleanup ----------------------------------------------------------

    [Fact]
    public async Task InputsAreReadWithoutALockOrTransaction()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var handOff = await world.HandOffAsync();
        var claim = (await world.ClaimAsync())!;
        world.Sql.Clear();

        var inputs = await world.WithLifecycleAsync(l => l.LoadInputsAsync(claim, CancellationToken.None));

        Assert.NotNull(inputs);
        Assert.NotNull(inputs.Payload);
        Assert.Equal(claim.JobId, inputs.Payload.JobId);
        Assert.Equal(claim.AttemptCount, inputs.Payload.AttemptCount);
        Assert.Equal(handOff.Lease.DurationMs, inputs.VideoDurationMs);
        Assert.DoesNotContain(world.Sql.Commands, x => x.Contains("FOR UPDATE", StringComparison.OrdinalIgnoreCase));
        Assert.DoesNotContain(world.Sql.Commands, x => x.StartsWith("BEGIN", StringComparison.OrdinalIgnoreCase));

        await world.ExecuteSqlAsync("DELETE FROM vision_finalization_payloads WHERE job_id = $1", claim.JobId);
        var missing = await world.WithLifecycleAsync(l => l.LoadInputsAsync(claim, CancellationToken.None));
        Assert.NotNull(missing);
        Assert.Null(missing.Payload);
    }

    [Fact]
    public async Task CountsComeFromPostgresAndTrackHandOffClaimAndTerminalTransitions()
    {
        using var world = await FinalizationWorld.CreateAsync();
        Assert.Equal(new VisionFinalizationCounts(0, 0, 0, null), await world.WithLifecycleAsync(l => l.CountAsync(CancellationToken.None)));

        var first = await world.HandOffAsync(cameraCode: "CAM-1");
        world.Clock.Advance(TimeSpan.FromSeconds(1));
        var second = await world.HandOffAsync(cameraCode: "CAM-2");
        var handedOff = await world.WithLifecycleAsync(l => l.CountAsync(CancellationToken.None));
        Assert.Equal(2, handedOff.FinalizingJobs);
        Assert.Equal(0, handedOff.LiveClaims);
        Assert.Equal(0, handedOff.MalformedClaims);
        Assert.Equal(first.Ack.AcceptedAtUtc, handedOff.OldestFinalizingAcceptedAtUtc);

        var claim = (await world.ClaimAsync())!;
        Assert.Equal(1, (await world.WithLifecycleAsync(l => l.CountAsync(CancellationToken.None))).LiveClaims);

        await world.WithLifecycleAsync(l => l.FailAsync(claim, VisionFinalizationFailureCodes.PayloadInvalid, null, CancellationToken.None));
        var afterFailure = await world.WithLifecycleAsync(l => l.CountAsync(CancellationToken.None));
        Assert.Equal(1, afterFailure.FinalizingJobs);
        Assert.Equal(0, afterFailure.LiveClaims);
        Assert.Equal(second.Ack.AcceptedAtUtc, afterFailure.OldestFinalizingAcceptedAtUtc);
    }

    [Fact]
    public async Task PayloadCleanupIsTerminalOnlyGraceBoundedAndIdempotent()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var finalizing = await world.HandOffAsync(cameraCode: "CAM-1");
        var failed = await world.HandOffAsync(cameraCode: "CAM-2");
        var claim = (await world.ClaimAsync())!;
        Assert.Equal(finalizing.Lease.JobId, claim.JobId);
        await world.WithLifecycleAsync(l => l.FailAsync(claim, VisionFinalizationFailureCodes.PayloadInvalid, null, CancellationToken.None));
        var terminalAt = world.Clock.GetUtcNow();
        Assert.Equal(2, await world.PayloadCountAsync());

        Assert.Equal(0, await world.WithLifecycleAsync(l => l.CleanUpPayloadsAsync(100, TimeSpan.FromMinutes(1), CancellationToken.None)));
        world.Clock.Advance(TimeSpan.FromMinutes(1));
        Assert.Equal(1, await world.WithLifecycleAsync(l => l.CleanUpPayloadsAsync(100, TimeSpan.FromMinutes(1), CancellationToken.None)));
        Assert.Equal(0, await world.WithLifecycleAsync(l => l.CleanUpPayloadsAsync(100, TimeSpan.Zero, CancellationToken.None)));

        Assert.Equal(1, await world.PayloadCountAsync());
        var remaining = await world.JobAsync(failed.Lease.JobId);
        Assert.Equal(VisionJobStatus.Finalizing, remaining.Status);
        var terminal = await world.JobAsync(finalizing.Lease.JobId);
        Assert.Equal(VisionJobStatus.Failed, terminal.Status);
        Assert.Equal(terminalAt, terminal.CompletedAtUtc);
    }

    private static async Task<Guid> AnyJobIdAsync(FinalizationWorld world)
    {
        using var scope = world.Factory.Services.CreateScope();
        return (await scope.ServiceProvider.GetRequiredService<MaviDbContext>().VisionJobs.AsNoTracking().SingleAsync()).Id;
    }
}
