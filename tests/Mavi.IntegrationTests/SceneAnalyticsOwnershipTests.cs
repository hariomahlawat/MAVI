using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// Attempt fencing against a real database: who owns a unit, when ownership is lost, and
/// what an attempt that has lost it is allowed to do.
/// </summary>
/// <remarks>
/// <para>
/// The answer to the last question is: nothing. A stale attempt must not delete facts,
/// insert facts, complete, fail, supersede or allocate a visibility sequence. These tests
/// assert the absence of each, because a fence that is merely usually respected is not a
/// fence.
/// </para>
/// <para>
/// Lease expiry is the thing most easily mistaken for loss of ownership. It is not: a
/// unit past its lease is <i>reclaimable</i>, and an attempt that overruns and then
/// finishes still commits. Both halves of that are tested here.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneAnalyticsOwnershipTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    /// <summary>
    /// The frozen stale-completion scenario, step for step: A claims, A's lease passes,
    /// B reclaims, B completes, and A's late completion is rejected without disturbing
    /// anything B wrote.
    /// </summary>
    [Fact]
    public async Task AReclaimedAttemptCannotAlterTheUnitThatTookItsPlace()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);

        // 1–2. A claims and starts computing.
        var a = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        Assert.Equal(1, a!.AttemptCount);

        // 3. A's lease passes, and so does the reclaim grace.
        world.Clock.Advance(Policy.LeaseDuration + Policy.ReclaimGrace + TimeSpan.FromSeconds(1));

        // 4. B reclaims: new attempt, new token.
        var b = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        Assert.Equal(a.AnalysisId, b!.AnalysisId);
        Assert.Equal(2, b.AttemptCount);

        // 5. B completes with its facts.
        Assert.True((await lifecycle.CommitFactsAsync(b, world.Facts(b.AnalysisId, "S"), default)).IsSuccess);
        var afterB = await world.UnitAsync(b.AnalysisId);
        var factsAfterB = await FactFingerprintAsync(world, b.AnalysisId);

        // 6. A, still holding its own attempt and token, tries to finish.
        var late = await lifecycle.CommitFactsAsync(a, world.Facts(a.AnalysisId, "N"), default);

        // 7. Rejected, and nothing of B's moved.
        Assert.False(late.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.AttemptStale, late.ErrorCode);

        var afterA = await world.UnitAsync(b.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Completed, afterA.Status);
        Assert.Equal(afterB.AttemptCount, afterA.AttemptCount);
        Assert.Equal(afterB.VisibilitySequence, afterA.VisibilitySequence);
        Assert.Equal(afterB.CompletedAtUtc, afterA.CompletedAtUtc);
        Assert.Equal(afterB.AnalysedTrackCount, afterA.AnalysedTrackCount);
        Assert.Equal(factsAfterB, await FactFingerprintAsync(world, b.AnalysisId));
    }

    /// <summary>
    /// The same fence on the failure path. A stale attempt reporting a failure must not
    /// be able to mark the current owner failed — that would be a denial of service by a
    /// host that has already lost the unit.
    /// </summary>
    [Fact]
    public async Task AReclaimedAttemptCannotFailTheCurrentOwner()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);

        var a = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        world.Clock.Advance(Policy.LeaseDuration + Policy.ReclaimGrace + TimeSpan.FromSeconds(1));
        var b = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        var before = await world.UnitAsync(b!.AnalysisId);

        var late = await lifecycle.ReportFailureAsync(
            a!, SceneAnalyticsErrorCodes.EngineFailed, "late", Policy.MaximumAttempts, default);

        Assert.False(late.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.AttemptStale, late.ErrorCode);

        var after = await world.UnitAsync(b.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Running, after.Status);
        Assert.Equal(before.AttemptCount, after.AttemptCount);
        Assert.Equal(before.ClaimTokenHash, after.ClaimTokenHash);
        Assert.Null(after.FailureCode);

        // B still owns the unit and can still finish.
        Assert.True((await lifecycle.CommitFactsAsync(b, world.Facts(b.AnalysisId), default)).IsSuccess);
    }

    /// <summary>
    /// Ownership is lost when the row changes hands, not when a clock passes. An attempt
    /// that overran its lease but was never reclaimed still commits — correct work is not
    /// discarded for a clock margin.
    /// </summary>
    [Fact]
    public async Task AnAttemptWhoseLeaseExpiredButWasNotReclaimedStillCompletes()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);

        // Well past the lease and the grace; nobody reclaimed it.
        world.Clock.Advance(Policy.LeaseDuration + Policy.ReclaimGrace + TimeSpan.FromHours(2));

        var result = await lifecycle.CommitFactsAsync(claim!, world.Facts(claim!.AnalysisId), default);

        Assert.True(result.IsSuccess);
        Assert.Equal(SceneAnalysisStatus.Completed, (await world.UnitAsync(claim.AnalysisId)).Status);
    }

    /// <summary>
    /// The last permitted attempt is not killed the instant it overruns: inside the
    /// grace it still owns the unit and still completes.
    /// </summary>
    [Fact]
    public async Task TheLastAttemptStillCompletesInsideTheReclaimGrace()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        var claim = await ClaimLastAttemptAsync(world, lifecycle);

        world.Clock.Advance(Policy.LeaseDuration + TimeSpan.FromSeconds(30));
        Assert.Equal(0, await lifecycle.ExhaustAbandonedUnitsAsync(Policy, default));

        Assert.True((await lifecycle.CommitFactsAsync(claim, world.Facts(claim.AnalysisId), default)).IsSuccess);
    }

    /// <summary>
    /// Terminal exhaustion clears the claim-token hash, which invalidates the overrunning
    /// attempt exactly as a reclaim would. Its late completion then writes nothing, and
    /// in particular does not resurrect a unit the reconciler terminated.
    /// </summary>
    [Fact]
    public async Task AnExhaustedUnitCannotBeResurrectedByItsOverrunningAttempt()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        var claim = await ClaimLastAttemptAsync(world, lifecycle);

        world.Clock.Advance(Policy.LeaseDuration + Policy.ReclaimGrace + TimeSpan.FromSeconds(1));
        Assert.Equal(1, await lifecycle.ExhaustAbandonedUnitsAsync(Policy, default));

        var late = await lifecycle.CommitFactsAsync(claim, world.Facts(claim.AnalysisId), default);

        Assert.False(late.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.AttemptStale, late.ErrorCode);

        var unit = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Failed, unit.Status);
        Assert.Equal(SceneAnalyticsErrorCodes.AttemptsExhausted, unit.FailureCode);
        Assert.Null(unit.VisibilitySequence);
        Assert.Equal(0, await world.Read().TrackAnalysisOutcomes.CountAsync());
    }

    /// <summary>
    /// A rejected attempt must write <i>nothing</i>, not merely fail to complete. The
    /// facts it would have replaced are still the ones the owner committed.
    /// </summary>
    [Fact]
    public async Task ARejectedCompletionDeletesNoFacts()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);

        var a = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        world.Clock.Advance(Policy.LeaseDuration + Policy.ReclaimGrace + TimeSpan.FromSeconds(1));
        var b = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await lifecycle.CommitFactsAsync(b!, world.Facts(b!.AnalysisId, "S"), default);

        // A's facts are empty, so a fence that failed open would leave no facts at all.
        await lifecycle.CommitFactsAsync(a!, SceneAnalysisFacts.Empty, default);

        await using var reader = world.Read();
        Assert.Single(await reader.TrackAnalysisOutcomes.ToListAsync());
        Assert.Equal("S", (await reader.TrackMotionSummaries.AsNoTracking().SingleAsync()).Heading);
    }

    /// <summary>
    /// The case the token exists for. A retry resets the attempt counter, so an attempt
    /// from the previous cycle can hold the same number as the current owner; only the
    /// token separates them. An ownership check reduced to an attempt comparison would
    /// let this through.
    /// </summary>
    [Fact]
    public async Task AnAttemptNumberThatCollidesAcrossARetryIsStillRejected()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);

        // Old cycle, attempt 1.
        var old = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        Assert.Equal(1, old!.AttemptCount);
        await lifecycle.ReportFailureAsync(
            old, SceneAnalyticsErrorCodes.EngineFailed, null, maximumAttempts: 1, default);
        Assert.Equal(SceneAnalysisStatus.Failed, (await world.UnitAsync(old.AnalysisId)).Status);

        // New cycle, also attempt 1.
        Assert.True((await lifecycle.RetryAsync(old.AnalysisId, default)).IsSuccess);
        var current = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        Assert.Equal(old.AnalysisId, current!.AnalysisId);
        Assert.Equal(old.AttemptCount, current.AttemptCount);
        Assert.NotEqual(old.ClaimToken.ToArray(), current.ClaimToken.ToArray());

        var late = await lifecycle.CommitFactsAsync(old, world.Facts(old.AnalysisId), default);

        Assert.False(late.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.AttemptStale, late.ErrorCode);
        Assert.Equal(SceneAnalysisStatus.Running, (await world.UnitAsync(old.AnalysisId)).Status);
    }

    /// <summary>
    /// A superseded unit is fact-bearing and immutable. No attempt, stale or otherwise,
    /// may move it back.
    /// </summary>
    [Fact]
    public async Task AStaleAttemptCannotDisturbASupersededUnit()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);

        var first = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await lifecycle.CommitFactsAsync(first!, world.Facts(first!.AnalysisId, "N"), default);

        var newRevisionId = await world.ActivateNewRevisionAsync(Now.AddMinutes(1));
        world.Clock.Advance(TimeSpan.FromMinutes(2));
        await lifecycle.RequestAnalysisAsync(
            world.IdentityFor(newRevisionId, SceneAnalyticsWorld.AlgorithmVersion), default);
        var second = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await lifecycle.CommitFactsAsync(second!, world.Facts(second!.AnalysisId, "S"), default);

        var superseded = await world.UnitAsync(first.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Superseded, superseded.Status);
        var fingerprint = await FactFingerprintAsync(world, first.AnalysisId);

        // The attempt that produced the superseded unit surrendered its token at
        // completion, so its own claim no longer validates against the row.
        var late = await lifecycle.CommitFactsAsync(first, world.Facts(first.AnalysisId, "E"), default);

        Assert.False(late.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.AttemptStale, late.ErrorCode);
        var after = await world.UnitAsync(first.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Superseded, after.Status);
        Assert.Equal(superseded.VisibilitySequence, after.VisibilitySequence);
        Assert.Equal(fingerprint, await FactFingerprintAsync(world, first.AnalysisId));
    }

    // --- The token itself --------------------------------------------------

    /// <summary>
    /// The plaintext claim token exists in the executing host's memory and nowhere else.
    /// This reads every text and binary column of the unit and asserts the token is in
    /// none of them, including after a failure that carries operator-visible details.
    /// </summary>
    [Fact]
    public async Task ThePlaintextClaimTokenIsNeverPersistedAnywhereOnTheUnit()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        await lifecycle.ReportFailureAsync(
            claim!, SceneAnalyticsErrorCodes.EngineFailed, "engine threw", Policy.MaximumAttempts, default);

        var token = claim!.ClaimToken.ToArray();
        var hex = Convert.ToHexStringLower(token);
        var base64 = Convert.ToBase64String(token);

        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(
            "SELECT scene_analyses::text FROM scene_analyses WHERE id = @id;", connection);
        command.Parameters.AddWithValue("id", claim.AnalysisId);
        var row = (string?)await command.ExecuteScalarAsync() ?? "";

        Assert.DoesNotContain(hex, row, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain(base64, row, StringComparison.Ordinal);

        // And the claim does not volunteer it when something interpolates it into a log.
        Assert.DoesNotContain(hex, claim.ToString(), StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain(base64, claim.ToString(), StringComparison.Ordinal);
    }

    /// <summary>Two claims never mint the same token.</summary>
    [Fact]
    public async Task EveryClaimMintsAFreshToken()
    {
        var world = await CreateAsync();
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);

        var tokens = new List<string>();
        for (var attempt = 1; attempt <= Policy.MaximumAttempts; attempt++)
        {
            var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
            tokens.Add(Convert.ToHexStringLower(claim!.ClaimToken.Span));
            world.Clock.Advance(Policy.LeaseDuration + Policy.ReclaimGrace + TimeSpan.FromSeconds(1));
        }

        Assert.Equal(tokens.Count, tokens.Distinct(StringComparer.Ordinal).Count());
        Assert.All(tokens, token => Assert.Equal(SceneAnalysis.ClaimTokenByteLength * 2, token.Length));
    }

    // --- Helpers -----------------------------------------------------------

    private Task<SceneAnalyticsWorld> CreateAsync() => SceneAnalyticsWorld.CreateAsync(fixture, Now);

    private static Task<int> QueueAsync(SceneAnalysisLifecycle lifecycle) =>
        lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            sourceCommit: null,
            earliestRunCompletedAtUtc: Now.AddDays(-1),
            batchSize: 50,
            default);

    private static async Task<SceneAnalysisClaim> ClaimLastAttemptAsync(
        SceneAnalyticsWorld world,
        SceneAnalysisLifecycle lifecycle)
    {
        await QueueAsync(lifecycle);
        SceneAnalysisClaim? claim = null;
        for (var attempt = 1; attempt <= Policy.MaximumAttempts; attempt++)
        {
            claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
            if (attempt < Policy.MaximumAttempts)
            {
                world.Clock.Advance(Policy.LeaseDuration + Policy.ReclaimGrace + TimeSpan.FromSeconds(1));
            }
        }

        return claim!;
    }

    /// <summary>Every fact of one unit, rendered as text, so "unchanged" can be asserted literally.</summary>
    private static async Task<string> FactFingerprintAsync(SceneAnalyticsWorld world, Guid analysisId)
    {
        await using var db = world.Read();
        var outcomes = await db.TrackAnalysisOutcomes.AsNoTracking()
            .Where(x => x.AnalysisId == analysisId).OrderBy(x => x.TrackId)
            .Select(x => $"{x.TrackId}|{x.Outcome}|{x.ReferencePoint}|{x.SampleCount}").ToListAsync();
        var visits = await db.TrackZoneVisits.AsNoTracking()
            .Where(x => x.AnalysisId == analysisId).OrderBy(x => x.ZoneId).ThenBy(x => x.VisitIndex)
            .Select(x => $"{x.ZoneId}|{x.VisitIndex}|{x.DwellMs}|{x.EntryHeading}|{x.ExitHeading}").ToListAsync();
        var summaries = await db.TrackZoneSummaries.AsNoTracking()
            .Where(x => x.AnalysisId == analysisId).OrderBy(x => x.ZoneId)
            .Select(x => $"{x.ZoneId}|{x.VisitCount}|{x.TotalDwellMs}|{x.Loitering}").ToListAsync();
        var crossings = await db.TrackLineCrossings.AsNoTracking()
            .Where(x => x.AnalysisId == analysisId).OrderBy(x => x.LineId).ThenBy(x => x.CrossingIndex)
            .Select(x => $"{x.LineId}|{x.CrossingIndex}|{x.Direction}|{x.PointX}|{x.PointY}").ToListAsync();
        var motion = await db.TrackMotionSummaries.AsNoTracking()
            .Where(x => x.AnalysisId == analysisId).OrderBy(x => x.TrackId)
            .Select(x => $"{x.TrackId}|{x.Heading}|{x.LongestStationaryMs}|{x.TotalStationaryMs}").ToListAsync();

        return string.Join("\n", [.. outcomes, .. visits, .. summaries, .. crossings, .. motion]);
    }
}
