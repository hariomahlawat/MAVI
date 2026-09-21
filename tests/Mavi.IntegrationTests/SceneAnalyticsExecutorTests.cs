using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>
/// One analysis unit executed end to end: real sealed trajectory bytes, the real decoder,
/// the real engine, the real fenced commit, against a real database.
/// </summary>
/// <remarks>
/// The distinction these tests exist to hold is between evidence that is unusable and an
/// attempt that cannot proceed. A Track whose trajectory is absent, corrupt or too short
/// is written off as <c>Unavailable</c> and the unit completes around it; a fault that
/// says nothing about the evidence fails the attempt so it can be retried.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SceneAnalyticsExecutorTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalyticsOptions Options = new()
    {
        LeaseSeconds = 900,
        MaxUnitDurationSeconds = 300,
        ReclaimGraceSeconds = 60,
        MaximumAttempts = 3,
    };

    [Fact]
    public async Task AUnitWithRealTrajectoryEvidenceCompletesWithFacts()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;

        var claim = await QueueAndClaimAsync(lifecycle);
        var result = await executor.ExecuteAsync(claim, SceneAnalyticsWorld.ExecutionIdentity, Options, default);

        Assert.True(result.IsSuccess);
        Assert.Equal(1, result.AnalysedTrackCount);
        Assert.Equal(0, result.UnavailableTrackCount);

        var unit = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Completed, unit.Status);
        Assert.NotNull(unit.VisibilitySequence);

        await using var reader = world.Read();
        var outcome = await reader.TrackAnalysisOutcomes.AsNoTracking().SingleAsync();
        Assert.Equal(TrackAnalysisOutcomeKind.Analysed, outcome.Outcome);
        Assert.Equal("bbox-centre", outcome.ReferencePoint);
        Assert.True(outcome.SampleCount > 0);

        // The fixture path sits inside the zone for most of its length, so there is a
        // visit to find; asserting only that a row exists would pass on an empty result.
        var visit = await reader.TrackZoneVisits.AsNoTracking().SingleAsync();
        Assert.Equal(world.ZoneId, visit.ZoneId);
        Assert.True(visit.DwellMs > 0);
        Assert.Equal(world.RecordingStartUtc.AddMilliseconds(visit.EntryOffsetMs), visit.EntryTimestampUtc);

        var summary = await reader.TrackZoneSummaries.AsNoTracking().SingleAsync();
        Assert.True(summary.VisitCount > 0);
        Assert.NotNull(summary.FirstEntryTimestampUtc);

        Assert.Single(await reader.TrackMotionSummaries.ToListAsync());
    }

    /// <summary>
    /// Absolute fact timestamps come from the video's recording start, never from the
    /// host's clock: the same evidence analysed tomorrow must produce the same stamps.
    /// </summary>
    [Fact]
    public async Task FactTimestampsAreDerivedFromTheRecordingNotTheClock()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing());
        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;

        var claim = await QueueAndClaimAsync(lifecycle);
        world.Clock.Advance(TimeSpan.FromDays(3));
        await executor.ExecuteAsync(claim, SceneAnalyticsWorld.ExecutionIdentity, Options, default);

        await using var reader = world.Read();
        var crossing = await reader.TrackLineCrossings.AsNoTracking().SingleAsync();
        Assert.Equal(world.RecordingStartUtc.AddMilliseconds(crossing.OffsetMs), crossing.TimestampUtc);
        Assert.True(crossing.TimestampUtc < world.Clock.GetUtcNow());
    }

    /// <summary>The fixture line runs across the middle of the frame, so a straight
    /// left-to-right path must cross it exactly once, in a known direction.</summary>
    [Fact]
    public async Task AStraightCrossingIsDetectedAndPersisted()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing());
        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;

        await executor.ExecuteAsync(
            await QueueAndClaimAsync(lifecycle), SceneAnalyticsWorld.ExecutionIdentity, Options, default);

        await using var reader = world.Read();
        var crossing = await reader.TrackLineCrossings.AsNoTracking().SingleAsync();
        Assert.Equal(world.LineId, crossing.LineId);
        Assert.Contains(crossing.Direction, SceneAnalyticsVocabulary.CrossingDirections);
        Assert.InRange(crossing.PointX, 0, 1);
        Assert.InRange(crossing.PointY, 0, 1);
    }

    // --- Unusable evidence: the Track is written off, the unit completes ----

    [Theory]
    [InlineData(TrackUnusable.NoArtefact, SceneAnalyticsErrorCodes.TrajectoryMissing)]
    [InlineData(TrackUnusable.ArtefactRecordedButAbsent, SceneAnalyticsErrorCodes.TrajectoryMissing)]
    [InlineData(TrackUnusable.DigestMismatch, SceneAnalyticsErrorCodes.TrajectoryIntegrityFailed)]
    [InlineData(TrackUnusable.TooShort, SceneAnalyticsErrorCodes.TrajectoryTooShort)]
    [InlineData(TrackUnusable.Corrupt, SceneAnalyticsErrorCodes.TrajectoryInvalid)]
    public async Task UnusableEvidenceBecomesAnOutcomeAndNeverFailsTheUnit(
        TrackUnusable kind,
        string expectedReason)
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        switch (kind)
        {
            case TrackUnusable.NoArtefact:
                break;
            case TrackUnusable.ArtefactRecordedButAbsent:
                await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing(), write: false);
                break;
            case TrackUnusable.DigestMismatch:
                await world.AttachTrajectoryAsync(
                    TrajectoryPayload.StraightCrossing(), declaredSha256: new string('c', 64));
                break;
            case TrackUnusable.TooShort:
                await world.AttachTrajectoryAsync(TrajectoryPayload.Encode([(0, 0.5, 0.5)]));
                break;
            case TrackUnusable.Corrupt:
                await world.AttachTrajectoryAsync([0x82, 0xa1, 0x76, 0x01, 0xa6, 0x70, 0x6f, 0x69, 0x6e, 0x74, 0x73, 0xc0]);
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(kind), kind, null);
        }

        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;

        var claim = await QueueAndClaimAsync(lifecycle);
        var result = await executor.ExecuteAsync(claim, SceneAnalyticsWorld.ExecutionIdentity, Options, default);

        Assert.True(result.IsSuccess);
        Assert.Equal(0, result.AnalysedTrackCount);
        Assert.Equal(1, result.UnavailableTrackCount);

        var unit = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Completed, unit.Status);
        Assert.Equal(1, unit.UnavailableTrackCount);

        await using var reader = world.Read();
        var outcome = await reader.TrackAnalysisOutcomes.AsNoTracking().SingleAsync();
        Assert.Equal(TrackAnalysisOutcomeKind.Unavailable, outcome.Outcome);
        Assert.Equal(expectedReason, outcome.Reason);
        Assert.Null(outcome.ReferencePoint);

        // A Track that could not be read derives nothing, but is still accounted for.
        Assert.Empty(await reader.TrackZoneVisits.ToListAsync());
        Assert.Empty(await reader.TrackMotionSummaries.ToListAsync());
    }

    public enum TrackUnusable
    {
        NoArtefact,
        ArtefactRecordedButAbsent,
        DigestMismatch,
        TooShort,
        Corrupt,
    }

    // --- Faults that fail the attempt --------------------------------------

    /// <summary>
    /// The pinned revision is protected by a foreign key, so this should be unreachable.
    /// It is still handled, and handled as permanent: burning the remaining attempts on
    /// a condition that cannot change would only delay the same answer.
    /// </summary>
    [Fact]
    public async Task AMissingRevisionFailsTheUnitWithoutConsumingItsAttempts()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;
        var claim = await QueueAndClaimAsync(lifecycle);

        await using (var writer = world.Read())
        {
            await writer.Database.ExecuteSqlInterpolatedAsync(
                $"UPDATE scene_analyses SET revision_id = revision_id WHERE id = {claim.AnalysisId}");
        }

        // The revision cannot be deleted while a unit references it, so the executor is
        // asked about a unit whose revision it cannot load.
        var orphaned = new SceneAnalysisClaim(
            claim.AnalysisId,
            claim.Identity with { RevisionId = Guid.CreateVersion7() },
            claim.AttemptCount,
            claim.ClaimToken,
            claim.LeaseExpiresAtUtc);

        var result = await executor.ExecuteAsync(
            orphaned, SceneAnalyticsWorld.ExecutionIdentity, Options, default);

        Assert.False(result.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.RevisionMissing, result.FailureCode);

        var unit = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Failed, unit.Status);
        Assert.Equal(SceneAnalyticsErrorCodes.RevisionMissing, unit.FailureCode);
    }

    /// <summary>
    /// An attempt that runs past its bound is cancelled by its own executor, well before
    /// the lease could expire, and is counted as an attempt rather than left to be
    /// reclaimed.
    /// </summary>
    [Fact]
    public async Task AnAttemptThatExceedsItsDurationBoundIsCancelledAndCounted()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing());
        var (_, lifecycle, db) = world.Executor();
        await using var __ = db;
        var claim = await QueueAndClaimAsync(lifecycle);

        var stalling = world.ExecutorWith(new StallingEvidenceReader(), lifecycle);
        var result = await stalling.ExecuteAsync(
            claim,
            SceneAnalyticsWorld.ExecutionIdentity,
            new SceneAnalyticsOptions
            {
                LeaseSeconds = Options.LeaseSeconds,
                MaxUnitDurationSeconds = 1,
                ReclaimGraceSeconds = Options.ReclaimGraceSeconds,
                MaximumAttempts = Options.MaximumAttempts,
            },
            default);

        Assert.False(result.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.UnitTimeout, result.FailureCode);

        var unit = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(1, unit.AttemptCount);
        Assert.Equal(SceneAnalysisStatus.Queued, unit.Status);
        Assert.Equal(SceneAnalyticsErrorCodes.UnitTimeout, unit.FailureCode);
    }

    /// <summary>
    /// An I/O fault says nothing about the evidence, so the Track is not written off and
    /// the attempt is retried.
    /// </summary>
    [Fact]
    public async Task AnIoFaultFailsTheAttemptRatherThanTheTrack()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing());
        var (_, lifecycle, db) = world.Executor();
        await using var __ = db;
        var claim = await QueueAndClaimAsync(lifecycle);

        var faulting = world.ExecutorWith(new FaultingEvidenceReader(), lifecycle);
        var result = await faulting.ExecuteAsync(claim, SceneAnalyticsWorld.ExecutionIdentity, Options, default);

        Assert.False(result.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.TrajectoryReadFailed, result.FailureCode);

        var unit = await world.UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Queued, unit.Status);
        Assert.Equal(0, await world.Read().TrackAnalysisOutcomes.CountAsync());
    }

    /// <summary>
    /// A host that lost its unit while computing discards its results and says so, rather
    /// than reporting a failure that would overwrite the current owner's state.
    /// </summary>
    [Fact]
    public async Task AnExecutionThatLostItsUnitReportsStaleAndWritesNothing()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing());
        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;

        var a = await QueueAndClaimAsync(lifecycle);
        world.Clock.Advance(TimeSpan.FromSeconds(Options.LeaseSeconds + Options.ReclaimGraceSeconds + 1));
        var b = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Options.ToLeasePolicy(), default);

        var result = await executor.ExecuteAsync(a, SceneAnalyticsWorld.ExecutionIdentity, Options, default);

        Assert.False(result.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.AttemptStale, result.FailureCode);

        // B still owns the unit, and A's rejection left no failure behind.
        var unit = await world.UnitAsync(b!.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Running, unit.Status);
        Assert.Null(unit.FailureCode);
        Assert.Equal(0, await world.Read().TrackAnalysisOutcomes.CountAsync());
    }

    /// <summary>
    /// An attempt that lost its unit while failing must report that it is stale, not the
    /// fault it was about to record.
    /// </summary>
    /// <remarks>
    /// Lifecycle state is already protected — the fenced transition writes nothing — but
    /// an executor that ignored the transition result would log and return the original
    /// engine or I/O cause, describing a unit this host no longer owns.
    /// </remarks>
    [Fact]
    public async Task AnAttemptThatLostItsUnitWhileFailingReportsStaleNotTheOriginalFault()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing());
        var (_, lifecycle, db) = world.Executor();
        await using var __ = db;

        var a = await QueueAndClaimAsync(lifecycle);
        world.Clock.Advance(TimeSpan.FromSeconds(Options.LeaseSeconds + Options.ReclaimGraceSeconds + 1));
        var b = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Options.ToLeasePolicy(), default);

        // A's read fails, so A tries to report a retryable I/O failure — but B owns the unit.
        var faulting = world.ExecutorWith(new FaultingEvidenceReader(), lifecycle);
        var result = await faulting.ExecuteAsync(a, SceneAnalyticsWorld.ExecutionIdentity, Options, default);

        Assert.False(result.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.AttemptStale, result.FailureCode);

        var unit = await world.UnitAsync(b!.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Running, unit.Status);
        Assert.Null(unit.FailureCode);
    }

    // --- Idempotency -------------------------------------------------------

    /// <summary>
    /// The same evidence and the same revision produce the same facts, every time. That
    /// is what makes an analysis reproducible from the identity recorded beside it.
    /// </summary>
    [Fact]
    public async Task ReExecutingAUnitProducesIdenticalFacts()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(TrajectoryPayload.DwellThenLeave());
        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;

        var first = await QueueAndClaimAsync(lifecycle);
        await executor.ExecuteAsync(first, SceneAnalyticsWorld.ExecutionIdentity, Options, default);
        var after = await FingerprintAsync(world, first.AnalysisId);

        await using (var writer = world.Read())
        {
            await writer.Database.ExecuteSqlInterpolatedAsync(
                $"UPDATE scene_analyses SET status = 'Failed' WHERE id = {first.AnalysisId}");
        }

        await lifecycle.RetryAsync(first.AnalysisId, default);
        var second = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Options.ToLeasePolicy(), default);
        await executor.ExecuteAsync(second!, SceneAnalyticsWorld.ExecutionIdentity, Options, default);

        Assert.Equal(after, await FingerprintAsync(world, first.AnalysisId));
    }

    // --- Helpers -----------------------------------------------------------

    private static async Task<SceneAnalysisClaim> QueueAndClaimAsync(
        Mavi.Infrastructure.Persistence.Repositories.SceneAnalysisLifecycle lifecycle)
    {
        await lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            sourceCommit: null,
            Now.AddDays(-1),
            50,
            default);
        return await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Options.ToLeasePolicy(), default)
            ?? throw new InvalidOperationException("No unit was claimable.");
    }

    /// <summary>Facts rendered as text, so "identical" can be asserted literally.</summary>
    private static async Task<string> FingerprintAsync(SceneAnalyticsWorld world, Guid analysisId)
    {
        await using var db = world.Read();
        var visits = await db.TrackZoneVisits.AsNoTracking().Where(x => x.AnalysisId == analysisId)
            .OrderBy(x => x.VisitIndex)
            .Select(x => $"{x.ZoneId}|{x.VisitIndex}|{x.EntryOffsetMs}|{x.ExitOffsetMs}|{x.DwellMs}|{x.EntryHeading}")
            .ToListAsync();
        var crossings = await db.TrackLineCrossings.AsNoTracking().Where(x => x.AnalysisId == analysisId)
            .OrderBy(x => x.CrossingIndex)
            .Select(x => $"{x.LineId}|{x.CrossingIndex}|{x.OffsetMs}|{x.Direction}|{x.PointX}|{x.PointY}")
            .ToListAsync();
        var motion = await db.TrackMotionSummaries.AsNoTracking().Where(x => x.AnalysisId == analysisId)
            .Select(x => $"{x.Heading}|{x.PathLengthNormalised}|{x.MeanDisplacementRate}|{x.TotalStationaryMs}")
            .ToListAsync();
        return string.Join("\n", [.. visits, .. crossings, .. motion]);
    }

    /// <summary>Never returns; used to exercise the duration bound.</summary>
    private sealed class StallingEvidenceReader : ISceneAnalysisEvidenceReader
    {
        public async Task<IReadOnlyList<SceneAnalysisTrackEvidence>> ListRunTracksAsync(
            Guid processingRunId,
            CancellationToken cancellationToken)
        {
            await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
            throw new InvalidOperationException("Unreachable.");
        }

        public Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Unreachable.");
    }

    /// <summary>Lists one Track, then fails to read its bytes.</summary>
    private sealed class FaultingEvidenceReader : ISceneAnalysisEvidenceReader
    {
        public Task<IReadOnlyList<SceneAnalysisTrackEvidence>> ListRunTracksAsync(
            Guid processingRunId,
            CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<SceneAnalysisTrackEvidence>>(
                [new SceneAnalysisTrackEvidence(
                    Guid.CreateVersion7(),
                    Mavi.Domain.Intelligence.ObjectClass.Person,
                    Now,
                    "evidence/run/attempt-0001/trajectories/person-000001.msgpack",
                    null)]);

        public Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken) =>
            throw new IOException("The evidence volume is unavailable.");
    }
}
