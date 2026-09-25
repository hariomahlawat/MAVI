using System.Data.Common;
using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.RegularExpressions;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Processing;
using Mavi.Contracts.Worker;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Npgsql;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// S1.4 B3-B (F4 plan §9): the asynchronous finalization envelope at the worst shape, through
/// the <b>real</b> hosted finalizer (not driven cycles, not a fake), the real lifecycle,
/// executor, accepted-evidence store and PostgreSQL, with the finalizer configuration read
/// from <c>appsettings.json</c> (only <c>VisionFinalization:Enabled</c> is set). Timing comes
/// from the test-only <see cref="PublicationTimelineRecorder"/> and
/// <see cref="FinalizationTimingDecorator"/>; event 1504 is retained as a cross-check only.
/// </summary>
/// <remarks>
/// <para>Opt-in and heavy; skipped unless <c>MAVI_QUALIFICATION=1</c>:</para>
/// <code>
/// MAVI_QUALIFICATION=1 MAVI_QUALIFICATION_OUT=... MAVI_S1_ENVELOPE_ROOT=/path/on/qualified/filesystem \
/// dotnet test tests/Mavi.IntegrationTests --filter "FullyQualifiedName~S1FinalizationEnvelopeTests"
/// </code>
/// <para>
/// The ordinary-suite facts below discriminate the instrumentation itself: a 750 ms delay
/// injected into the graph insert must grow graph persistence and the row-lock-to-commit
/// interval, and must not grow the visibility-barrier hold or the graph-build bracket.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class S1FinalizationEnvelopeTests
{
    public const string Schema = "s1-b3b-finalization-v1";
    private static readonly Regex Created = new(@"(\d+) created", RegexOptions.CultureInvariant);
    private static readonly Regex Adopted = new(@"(\d+) adopted", RegexOptions.CultureInvariant);

    // -- ordinary-suite discriminators of the instrumentation -----------------------------------

    [Fact]
    public void TheBarrierCommandIsTheExclusiveLockConstant()
    {
        var recorder = new PublicationTimelineRecorder();
        // Verified against the one expected value, read from the product by reflection.
        Assert.Equal("SELECT pg_advisory_xact_lock(1296127561, 1412505908)", recorder.BarrierSql);
        Assert.True(recorder.IsBarrier("SELECT  pg_advisory_xact_lock(1296127561,\n 1412505908)".Replace(",\n ", ", ", StringComparison.Ordinal)));
        Assert.False(recorder.IsBarrier(recorder.SharedBarrierSql));
        Assert.Contains("_shared", recorder.SharedBarrierSql, StringComparison.Ordinal);
        Assert.False(recorder.IsBarrier("SELECT * FROM vision_jobs WHERE id = $1 FOR UPDATE"));
    }

    [Theory]
    [InlineData("Finalizing", ProcessingPhases.Finalizing, 0, 0, 0, 404, null)]
    [InlineData("Finalizing", ProcessingPhases.Processing, 0, 0, 0, 404, VisibilityChecks.WrongPhase)]
    [InlineData("Finalizing", ProcessingPhases.Queued, 0, 0, 0, 404, VisibilityChecks.WrongPhase)]
    [InlineData("Finalizing", ProcessingPhases.Completed, 0, 0, 0, 404, VisibilityChecks.WrongPhase)]
    [InlineData("Finalizing", ProcessingPhases.Finalizing, 7, 0, 0, 404, VisibilityChecks.PublishedCount)]
    [InlineData("Finalizing", ProcessingPhases.Finalizing, 0, 1, 0, 404, VisibilityChecks.Search)]
    [InlineData("Finalizing", ProcessingPhases.Finalizing, 0, 0, 1, 404, VisibilityChecks.TrackRows)]
    [InlineData("Finalizing", ProcessingPhases.Finalizing, 0, 0, 0, 200, VisibilityChecks.Detail)]
    [InlineData("Completed", ProcessingPhases.Processing, 7, 1, 1, 200, null)]  // after publication nothing is premature
    public void EveryPrematureReadIsItsOwnViolation(string dbStatus, string apiPhase, int tracksCreated, int searchHits, long trackRows, int detailStatus, string? expected)
    {
        var snapshot = new VisibilitySnapshot(dbStatus, apiPhase, tracksCreated, searchHits, trackRows, [404, detailStatus]);
        Assert.Equal(expected is null ? [] : [expected], VisibilityChecks.Violations(snapshot));

        // The tally counts only Finalizing snapshots, and detail only where it was read.
        var tally = new VisibilityTally();
        tally.Add(snapshot, [Guid.CreateVersion7()]);
        tally.Add(snapshot with { DetailStatuses = [] }, []);
        Assert.Equal(dbStatus == "Finalizing" ? 2 : 0, tally.Probes);
        Assert.Equal(dbStatus == "Finalizing" ? 1 : 0, tally.DetailProbes);
        Assert.Equal(expected is null ? 0 : 2 - (expected == VisibilityChecks.Detail ? 1 : 0), tally.Total);
    }

    [Fact]
    public async Task ThePrematureVisibilityProbeReadsEveryRealApiWhileTheJobIsFinalizing()
    {
        var log = new LifecycleCallLog();
        var hold = new HoldGraphInsert();
        using var world = await FinalizationWorld.CreateAsync(
            overrideServices: services => FinalizationTimingDecorator.Register(services, log),
            configureDbContext: builder => builder.AddInterceptors(hold));
        var handOff = await world.HandOffAsync(lease => StagedRequestAsync(world, lease, 3));
        var jobId = handOff.Lease.JobId;
        var (_, _, video) = await world.StateAsync(jobId);
        using var client = world.Factory.CreateClient();
        Task<VisibilitySnapshot> ProbeAsync(IReadOnlyList<Guid> ids) =>
            VisibilityChecks.ProbeAsync(world.Factory.ConnectionString, client, video.Id, video.CameraId, jobId, ids);

        // After the hand-off, before any graph exists: the status API must say exactly
        // "finalizing" (a "processing" projection fails here), and no Track id exists yet.
        var early = await ProbeAsync(log.PendingTracks(jobId));
        Assert.True(early.DuringFinalizing);
        Assert.Equal(ProcessingPhases.Finalizing, early.ApiPhase);
        Assert.Empty(early.DetailStatuses);
        Assert.Empty(VisibilityChecks.Violations(early));

        // Inside the publication: the graph is built and its ids noted, its transaction open.
        var cycle = world.Host().RunCycleAsync(CancellationToken.None);
        await hold.Entered.Task.WaitAsync(TimeSpan.FromMinutes(1));
        var ids = log.PendingTracks(jobId);
        Assert.Equal(3, ids.Count);
        var inside = await ProbeAsync(ids);
        Assert.True(inside.DuringFinalizing);
        Assert.Equal(ProcessingPhases.Finalizing, inside.ApiPhase);
        Assert.Equal([404, 404, 404], inside.DetailStatuses);
        Assert.Empty(VisibilityChecks.Violations(inside));
        var tally = new VisibilityTally();
        tally.Add(early, []);
        tally.Add(inside, ids);
        Assert.Equal((2, 1, 0), (tally.Probes, tally.DetailProbes, tally.Total));

        hold.Release.TrySetResult();
        await cycle;
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(jobId)).Status);
        // The same ids are real Tracks now: the detail API exposes each of them, so the 404s
        // above withheld Tracks that exist, not ids that never would.
        var after = await ProbeAsync(ids);
        Assert.False(after.DuringFinalizing);
        Assert.Equal([200, 200, 200], after.DetailStatuses);
        Assert.Equal(ProcessingPhases.Completed, after.ApiPhase);
    }

    [Fact]
    public async Task OverlapIsASecondDurableUnclaimedHandOffBehindALiveFirstClaim()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var first = (await world.HandOffAsync(lease => StagedRequestAsync(world, lease, 2), cameraCode: "CAM-OVERLAP-1")).Lease.JobId;
        var second = (await world.HandOffAsync(lease => StagedRequestAsync(world, lease, 2), cameraCode: "CAM-OVERLAP-2")).Lease.JobId;
        var connection = world.Factory.ConnectionString;
        DateTimeOffset Now() => world.Clock.GetUtcNow();

        // Two Finalizing jobs, but no finalization running: not the limit being exercised.
        Assert.False((await OverlapSnapshot.TakeAsync(connection, first, second, Now())).IsOverlap);

        var claim = await world.ClaimAsync();
        Assert.Equal(first, claim!.JobId);  // claims follow acceptance order
        var overlap = await OverlapSnapshot.TakeAsync(connection, first, second, Now());
        Assert.True(overlap.IsOverlap);
        Assert.Equal((true, false, 1L, 1L, 1L), (overlap.FirstClaimLive, overlap.SecondClaimed, overlap.FirstPayloadRows, overlap.SecondPayloadRows, overlap.LiveClaims));

        // The second holding a claim too is two finalizations, not one waiting.
        var (_, hash) = FinalizationWorld.Token(7);
        await world.SetClaimTripleAsync(second, hash, Now().AddMinutes(5), Now());
        var both = await OverlapSnapshot.TakeAsync(connection, first, second, Now());
        Assert.True(both.SecondClaimed);
        Assert.Equal(2, both.LiveClaims);
        Assert.False(both.IsOverlap);
        await world.SetClaimTripleAsync(second, null, null, null);
        Assert.True((await OverlapSnapshot.TakeAsync(connection, first, second, Now())).IsOverlap);

        // An expired first claim is not a running finalization.
        var expired = await OverlapSnapshot.TakeAsync(connection, first, second, Now().AddHours(1));
        Assert.False(expired.FirstClaimLive);
        Assert.False(expired.IsOverlap);
    }

    [Fact]
    public async Task ASecondHandOffAfterTheFirstCompletedIsNoOverlap()
    {
        using var world = await FinalizationWorld.CreateAsync();
        var first = (await world.HandOffAsync(lease => StagedRequestAsync(world, lease, 2), cameraCode: "CAM-LATE-1")).Lease.JobId;
        await world.Host().RunCycleAsync(CancellationToken.None);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(first)).Status);
        world.Clock.Advance(TimeSpan.FromSeconds(1));
        // The deliberately delayed second hand-off.
        var second = (await world.HandOffAsync(lease => StagedRequestAsync(world, lease, 2), cameraCode: "CAM-LATE-2")).Lease.JobId;
        var connection = world.Factory.ConnectionString;

        var snapshot = await OverlapSnapshot.TakeAsync(connection, first, second, world.Clock.GetUtcNow());
        Assert.Equal((nameof(VisionJobStatus.Completed), nameof(VisionJobStatus.Finalizing)), (snapshot.FirstStatus, snapshot.SecondStatus));
        Assert.False(snapshot.IsOverlap);
        // The retained times say so independently: the second was accepted after the first completed.
        var (_, firstCompleted) = await HandOffTimesAsync(connection, first);
        var (secondAccepted, _) = await HandOffTimesAsync(connection, second);
        Assert.True(secondAccepted > firstCompleted, $"{secondAccepted:O} vs {firstCompleted:O}");
    }

    [Fact]
    public async Task BarrierHoldExcludesGraphPersistence()
    {
        // A discarded warm-up: the first publication in a process pays JIT and EF model costs
        // that would otherwise hide inside the comparison.
        _ = await PublishSmallAsync(delayGraphInsert: false);
        var plain = await PublishSmallAsync(delayGraphInsert: false);
        var delayed = await PublishSmallAsync(delayGraphInsert: true);

        Assert.Empty(plain.Timeline.OrderingProblems());
        Assert.Empty(delayed.Timeline.OrderingProblems());
        Assert.True(delayed.Timeline.GraphPersistenceBracketContainsOnlyAddAsync);
        // The delay sits inside graph persistence: the row lock is held through it ...
        Assert.True(delayed.Timeline.RowLockToCommitMs - plain.Timeline.RowLockToCommitMs >= 750,
            $"row lock to commit {plain.Timeline.RowLockToCommitMs} -> {delayed.Timeline.RowLockToCommitMs} ms");
        // ... but the visibility barrier is taken only after it.
        Assert.True(delayed.Timeline.BarrierHoldMs - plain.Timeline.BarrierHoldMs < 100,
            $"barrier hold {plain.Timeline.BarrierHoldMs} -> {delayed.Timeline.BarrierHoldMs} ms");
        Assert.True(delayed.Timeline.BarrierHoldMs < delayed.Timeline.RowLockToCommitMs - delayed.Timeline.GraphPersistenceMs);
        Assert.True(delayed.Timeline.RowLockToCommitMs >= 750 && delayed.Timeline.BarrierHoldMs < 750);
    }

    [Fact]
    public async Task SequenceAllocationsAreCountedInsideTheirPublication()
    {
        using var observer = new SequenceAllocationObserver();
        Assert.Equal("SELECT nextval('processing_visibility_sequence')", observer.SequenceSql);
        var small = await PublishSmallAsync(delayGraphInsert: false);
        Assert.NotNull(small.Timeline.Scope);
        Assert.Equal(1, observer.In(small.Timeline.Scope));

        // Discriminates: a scope that allocates twice counts two (a row count of the run's
        // visibility_sequence would still read one), and an allocation outside any
        // PublishAsync, such as a search snapshot's, counts in no scope.
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var before = observer.Total;
        await using (await db.Database.BeginTransactionAsync())
            await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, CancellationToken.None);
        Assert.Equal(before + 1, observer.Total);
        var twice = await AllocateInScopeAsync(db, 2);
        Assert.Equal(2, observer.In(twice));
        Assert.Equal(0, observer.In(null));
    }

    private static async Task<long> AllocateInScopeAsync(MaviDbContext db, int count)
    {
        var scope = PublicationScope.Enter();
        try
        {
            await using var transaction = await db.Database.BeginTransactionAsync();
            for (var i = 0; i < count; i++) await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, CancellationToken.None);
            await transaction.RollbackAsync();
            return scope;
        }
        finally
        {
            PublicationScope.Exit();
        }
    }

    [Fact]
    public async Task GraphPersistenceIsMeasuredAroundAddAsync()
    {
        // A discarded warm-up: the first publication in a process pays JIT and EF model costs
        // that would otherwise hide inside the comparison.
        _ = await PublishSmallAsync(delayGraphInsert: false);
        var plain = await PublishSmallAsync(delayGraphInsert: false);
        var delayed = await PublishSmallAsync(delayGraphInsert: true);

        Assert.True(plain.Timeline.GraphPersistenceMs > 0);
        Assert.True(plain.Timeline.GraphSaveChangesMs <= plain.Timeline.GraphPersistenceMs);
        Assert.True(plain.Timeline.GraphPersistenceBracketContainsOnlyAddAsync);
        Assert.True(delayed.Timeline.GraphPersistenceMs >= 750);
        Assert.True(delayed.Timeline.GraphPersistenceMs - plain.Timeline.GraphPersistenceMs >= 750,
            $"graph persistence {plain.Timeline.GraphPersistenceMs} -> {delayed.Timeline.GraphPersistenceMs} ms");
        // The in-memory build happens before PublishAsync: the insert delay cannot reach it.
        Assert.True(delayed.GraphBuildBracketMs - plain.GraphBuildBracketMs < 100,
            $"graph build bracket {plain.GraphBuildBracketMs} -> {delayed.GraphBuildBracketMs} ms");
        Assert.True(plain.GraphBuildBracketHasNoLifecycleCall && delayed.GraphBuildBracketHasNoLifecycleCall);
    }

    [Fact]
    public async Task ATimelineWithoutCommitIsRejected()
    {
        var recorder = new PublicationTimelineRecorder();
        var log = new LifecycleCallLog();
        var commitFault = new FailFirstPublicationCommit();
        using var world = await FinalizationWorld.CreateAsync(
            overrideServices: services => FinalizationTimingDecorator.Register(services, log),
            configureDbContext: builder => builder.AddInterceptors([.. recorder.All, commitFault]));
        var handOff = await world.HandOffAsync(lease => StagedRequestAsync(world, lease, 3));
        await world.Host().RunCycleAsync(CancellationToken.None);   // the commit call fails: ambiguous, noted, released
        Assert.True(commitFault.Fired);
        await world.Host().RunCycleAsync(CancellationToken.None);   // the retry publishes
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(handOff.Lease.JobId)).Status);

        var timelines = recorder.Analyze(handOff.Lease.JobId);
        Assert.Equal(2, timelines.Count);
        Assert.False(timelines[0].Committed);
        Assert.NotEmpty(timelines[0].OrderingProblems());
        Assert.True(timelines[1].Committed);
        Assert.Empty(timelines[1].OrderingProblems());
        var publishes = log.For(handOff.Lease.JobId).Where(c => c.Method == nameof(IVisionFinalizationLifecycle.PublishAsync)).ToList();
        Assert.Equal(["Ambiguous", "Published"], publishes.Select(c => c.Result));
    }

    [Fact]
    public async Task TheReferenceSynchronousPathIsTimedWithTheSameInstrument()
    {
        var recorder = new PublicationTimelineRecorder();
        using var factory = new ApiTestFactory { ConfigureDbContext = builder => builder.AddInterceptors(recorder.All) };
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();
        var (_, jobId, _) = await S1QualificationSupport.QueueAsync(factory, client);
        var (staged, _) = await S1QualificationSupport.StageAsync(factory.Services.GetRequiredService<IMediaStore>(), jobId, 1, 3);
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        recorder.Clear();
        using var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", S1QualificationSupport.Request(lease, staged, "3.0"));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        var timeline = Assert.Single(recorder.Analyze(jobId, scopedOnly: false));
        Assert.True(timeline.Committed);
        Assert.Empty(timeline.OrderingProblems());
        Assert.True(timeline.BarrierHoldMs > 0 && timeline.BarrierHoldMs < timeline.RowLockToCommitMs);
    }

    /// <summary>
    /// The deliberate delay inside the graph insert. The assertions require growth of at least
    /// 750 ms; the injected delay is a little larger so that the ordinary run-to-run spread of
    /// the undelayed insert (tens of ms) cannot fail a correct instrument.
    /// </summary>
    private static readonly TimeSpan InjectedDelay = TimeSpan.FromMilliseconds(900);

    internal sealed record SmallPublication(PublicationTimeline Timeline, double GraphBuildBracketMs, bool GraphBuildBracketHasNoLifecycleCall);

    /// <summary>One small publication through the real lifecycle and executor, instrumented.</summary>
    private static async Task<SmallPublication> PublishSmallAsync(bool delayGraphInsert)
    {
        var recorder = new PublicationTimelineRecorder();
        var log = new LifecycleCallLog();
        var interceptors = new List<IInterceptor>(recorder.All);
        if (delayGraphInsert) interceptors.Add(new DelayGraphInsert(InjectedDelay));
        using var world = await FinalizationWorld.CreateAsync(
            overrideServices: services => FinalizationTimingDecorator.Register(services, log),
            configureDbContext: builder => builder.AddInterceptors(interceptors));
        var handOff = await world.HandOffAsync(lease => StagedRequestAsync(world, lease, 20));
        await world.Host().RunCycleAsync(CancellationToken.None);
        Assert.Equal(VisionJobStatus.Completed, (await world.JobAsync(handOff.Lease.JobId)).Status);

        var timeline = Assert.Single(recorder.Analyze(handOff.Lease.JobId), t => t.Committed);
        var (bracketMs, clean) = GraphBuildBracket(log.For(handOff.Lease.JobId));
        return new SmallPublication(timeline, bracketMs, clean);
    }

    private static async Task<VisionJobCompleteRequest> StagedRequestAsync(FinalizationWorld world, VisionJobLeaseContract lease, int tracks)
    {
        var (staged, _) = await S1QualificationSupport.StageAsync(world.Factory.Services.GetRequiredService<IMediaStore>(), lease.JobId, lease.AttemptCount, tracks);
        return S1QualificationSupport.Request(lease, staged, WorkerContractRules.CompletionSchemaVersionV31);
    }

    /// <summary>
    /// The in-memory graph build bracket: last extension return to PublishAsync entry, and
    /// whether any other lifecycle call for the job fell inside it. It includes the executor's
    /// few statements around <c>FinalizationGraphBuilder.Build</c>, hence "bracket".
    /// </summary>
    private static (double Ms, bool NoLifecycleCall) GraphBuildBracket(IReadOnlyList<LifecycleCall> calls)
    {
        var (start, end, clean) = GraphBuildBracketTicks(calls);
        return (S1QualificationSupport.TicksMs(start, end), clean);
    }

    private static (long Start, long End, bool NoLifecycleCall) GraphBuildBracketTicks(IReadOnlyList<LifecycleCall> calls)
    {
        var publish = calls.Last(c => c.Method == nameof(IVisionFinalizationLifecycle.PublishAsync));
        var lastExtension = calls.Last(c => c.Method == nameof(IVisionFinalizationLifecycle.ExtendClaimAsync) && c.ExitTicks <= publish.EnterTicks);
        var clean = !calls.Any(c => c.EnterTicks > lastExtension.ExitTicks && c.EnterTicks < publish.EnterTicks);
        return (lastExtension.ExitTicks, publish.EnterTicks, clean);
    }

    /// <summary>Sleeps once inside the publication's first graph INSERT (test-only fault).</summary>
    private sealed class DelayGraphInsert(TimeSpan delay) : DbCommandInterceptor
    {
        private int _fired;

        public override async ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result, CancellationToken cancellationToken = default)
        {
            await MaybeDelayAsync(command, cancellationToken);
            return result;
        }

        public override async ValueTask<InterceptionResult<int>> NonQueryExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<int> result, CancellationToken cancellationToken = default)
        {
            await MaybeDelayAsync(command, cancellationToken);
            return result;
        }

        private async Task MaybeDelayAsync(DbCommand command, CancellationToken cancellationToken)
        {
            if (PublicationScope.Current is not null
                && command.CommandText.Contains("INSERT INTO tracks", StringComparison.Ordinal)
                && Interlocked.Exchange(ref _fired, 1) == 0)
            {
                await Task.Delay(delay, cancellationToken);
            }
        }
    }

    /// <summary>
    /// Holds the publication's first graph INSERT until released, so a test can read the APIs
    /// while the publication transaction is open (test-only).
    /// </summary>
    private sealed class HoldGraphInsert : DbCommandInterceptor
    {
        private int _fired;

        public TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public override async ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result, CancellationToken cancellationToken = default)
        {
            await MaybeHoldAsync(command, cancellationToken);
            return result;
        }

        public override async ValueTask<InterceptionResult<int>> NonQueryExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<int> result, CancellationToken cancellationToken = default)
        {
            await MaybeHoldAsync(command, cancellationToken);
            return result;
        }

        private async Task MaybeHoldAsync(DbCommand command, CancellationToken cancellationToken)
        {
            if (PublicationScope.Current is not null
                && command.CommandText.Contains("INSERT INTO tracks", StringComparison.Ordinal)
                && Interlocked.Exchange(ref _fired, 1) == 0)
            {
                Entered.TrySetResult();
                await Release.Task.WaitAsync(TimeSpan.FromMinutes(2), cancellationToken);
            }
        }
    }

    /// <summary>Makes the first publication's commit call fail before it reaches PostgreSQL.</summary>
    private sealed class FailFirstPublicationCommit : DbTransactionInterceptor
    {
        private int _fired;

        public bool Fired => _fired == 1;

        public override ValueTask<InterceptionResult> TransactionCommittingAsync(DbTransaction transaction, TransactionEventData eventData, InterceptionResult result, CancellationToken cancellationToken = default)
        {
            if (PublicationScope.Current is not null && Interlocked.Exchange(ref _fired, 1) == 0)
                throw new NpgsqlException("injected commit-call failure (test-only)");
            return ValueTask.FromResult(result);
        }
    }

    // -- the heavy, opt-in envelope -------------------------------------------------------------

    internal static List<string> NonAuthoritativeReasons(
        int tracks, int samplesPerRepeat, int repeats, int warmup, int referenceSamples, string optionsSource, bool enabled,
        string storageClass, IReadOnlyDictionary<string, string> environment)
    {
        var reasons = new List<string>();
        if (tracks != S1QualificationSupport.WorstTracks) reasons.Add($"tracks {tracks} != the {S1QualificationSupport.WorstTracks} contract maximum");
        if (samplesPerRepeat * repeats < 30) reasons.Add($"samples {samplesPerRepeat * repeats} < 30");
        if (repeats < 3) reasons.Add($"repeats {repeats} < 3");
        if (warmup < 1) reasons.Add("no warm-up sample excluded");
        if (referenceSamples < 5) reasons.Add($"reference samples {referenceSamples} < 5");
        if (optionsSource != "appsettings.json") reasons.Add("the finalizer ran with options other than the committed appsettings.json");
        if (!enabled) reasons.Add("the finalizer was not activated");
        reasons.AddRange(S1QualificationSupport.CommonNonAuthoritativeReasons(environment, storageClass));
        return reasons;
    }

    [Fact]
    public void OnlyTheFullEnvelopeOnTheCommittedActivatedConfigurationIsAuthoritative()
    {
        var qualified = new Dictionary<string, string>
        {
            [QualificationGate.QualificationGradeKey] = "true",
            [QualificationGate.GitWorkingTreeCleanKey] = "true",
            [QualificationGate.GitCommitObjectPresentKey] = "true",
        };
        var full = S1QualificationSupport.WorstTracks;
        Assert.Empty(NonAuthoritativeReasons(full, 10, 3, 1, 5, "appsettings.json", true, "ssd", qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(500, 10, 3, 1, 5, "appsettings.json", true, "ssd", qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(full, 9, 3, 1, 5, "appsettings.json", true, "ssd", qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(full, 10, 3, 1, 4, "appsettings.json", true, "ssd", qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(full, 10, 3, 1, 5, "overridden", true, "ssd", qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(full, 10, 3, 1, 5, "appsettings.json", false, "ssd", qualified));
        Assert.NotEmpty(NonAuthoritativeReasons(full, 10, 3, 1, 5, "appsettings.json", true, "hosted-runner", qualified));
    }

    [S1QualificationFact]
    public async Task AsynchronousFinalizationEnvelopeAtTheWorstShape()
    {
        var tracks = S1QualificationSupport.Setting("MAVI_S1_ENVELOPE_TRACKS", S1QualificationSupport.WorstTracks);
        var samplesPerRepeat = S1QualificationSupport.Setting("MAVI_S1_ENVELOPE_SAMPLES", 10);
        var repeats = S1QualificationSupport.Setting("MAVI_S1_ENVELOPE_REPEATS", 3);
        var warmup = S1QualificationSupport.Setting("MAVI_S1_ENVELOPE_WARMUP", 1);
        var referenceSamples = S1QualificationSupport.Setting("MAVI_S1_REFERENCE_SAMPLES", 5);
        var baselineSeconds = S1QualificationSupport.Setting("MAVI_S1_ENVELOPE_BASELINE_SECONDS", 30);
        var root = Environment.GetEnvironmentVariable("MAVI_S1_ENVELOPE_ROOT");
        Assert.False(string.IsNullOrWhiteSpace(root), "MAVI_S1_ENVELOPE_ROOT must name a directory on the filesystem being qualified.");

        var environment = await QualificationGate.CaptureEnvironmentAsync(Environment.GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION")!);
        var runId = QualificationGate.NewRunId();
        var fileName = $"s1-b3b-finalization.{S1QualificationSupport.RuntimeVariant()}.json";
        QualificationGate.Begin(fileName, runId, environment);
        var workRoot = Path.Combine(root!, $"mavi-s1-b3b-{runId}");
        var mediaRoot = Path.Combine(workRoot, "media");
        var evidenceRoot = Path.Combine(workRoot, "evidence");
        Directory.CreateDirectory(mediaRoot);
        Directory.CreateDirectory(evidenceRoot);
        var host = S1QualificationSupport.Host(evidenceRoot);
        try
        {
            var samples = new List<Dictionary<string, object?>>();
            var rejected = new List<object>();
            EnvelopeContext? context = null;
            using var sequences = new SequenceAllocationObserver();
            for (var repeat = 0; repeat < repeats; repeat++)
            {
                for (var index = 0; index < warmup + samplesPerRepeat; index++)
                {
                    var sample = await EnvelopeOnceAsync(mediaRoot, evidenceRoot, tracks, TimeSpan.FromSeconds(index == 0 && repeat == 0 ? baselineSeconds : Math.Min(baselineSeconds, 5)), sequences);
                    context ??= sample.Context;
                    sample.Values["repeat"] = repeat;
                    sample.Values["index"] = index;
                    sample.Values["warmup"] = index < warmup;
                    samples.Add(sample.Values);
                    rejected.AddRange(sample.Rejected);
                }
            }

            // §9.2 concurrency behaviour: two hand-offs back to back under the configured limit.
            var concurrency = await ConcurrencyOnceAsync(mediaRoot, evidenceRoot, tracks, sequences);

            var reference = new List<object>();
            for (var index = 0; index < referenceSamples; index++)
                reference.Add(await ReferenceOnceAsync(mediaRoot, evidenceRoot, tracks));

            var reasons = NonAuthoritativeReasons(tracks, samplesPerRepeat, repeats, warmup, reference.Count, context!.OptionsSource,
                (bool)context.Configuration["Enabled"], (string)host["storageClass"]!, environment);
            var path = S1QualificationSupport.WriteOutput(fileName, new
            {
                schema = Schema,
                status = "complete",
                authoritative = reasons.Count == 0,
                nonAuthoritativeReasons = reasons,
                runId,
                variant = S1QualificationSupport.RuntimeVariant(),
                environment,
                host,
                workRoot,
                shape = new { tracks, observations = tracks * 4, stagedObjects = tracks * S1QualificationSupport.ObjectsPerTrack },
                hostedServiceUsed = true,
                optionsSource = context.OptionsSource,
                configuration = context.Configuration,
                barrierCommandText = PublicationTimelineRecorder.ReadBarrierSql(),
                effectiveCommandTimeoutSeconds = context.CommandTimeoutSeconds,
                rejectedTimelines = rejected,
                concurrency,
                inProcessHostNote = "The API host runs in the test process (WebApplicationFactory): RSS and CPU are the process's, host plus harness.",
                reference = new { samples = reference },
                samples,
            });
            Console.WriteLine($"S1 B3-B envelope evidence: {path}");
        }
        finally
        {
            if (Directory.Exists(workRoot)) Directory.Delete(workRoot, recursive: true);
        }
    }

    private sealed class EnvelopeContext
    {
        public required string OptionsSource { get; init; }
        public required Dictionary<string, object> Configuration { get; init; }
        public required int CommandTimeoutSeconds { get; init; }
    }

    private sealed record EnvelopeSample(Dictionary<string, object?> Values, EnvelopeContext Context, List<object> Rejected);

    private static void Empty(string root)
    {
        foreach (var entry in Directory.EnumerateFileSystemEntries(root))
        {
            if (Directory.Exists(entry)) Directory.Delete(entry, recursive: true);
            else File.Delete(entry);
        }
    }

    private static async Task<EnvelopeSample> EnvelopeOnceAsync(string mediaRoot, string evidenceRoot, int trackCount, TimeSpan baseline, SequenceAllocationObserver sequences)
    {
        Empty(mediaRoot);
        Empty(evidenceRoot);
        await S1QualificationSupport.ResetDatabaseAsync(mediaRoot, evidenceRoot);
        var recorder = new PublicationTimelineRecorder();
        var log = new LifecycleCallLog();
        var logs = new VisionFinalizationSubmissionApiTests.CapturingLoggerProvider();
        using var factory = new ApiTestFactory
        {
            EnableAsynchronousFinalization = true,
            EnableVisionFinalizationHost = true,  // the real hosted finalizer, on its own schedule
            MediaRootOverride = mediaRoot,
            EvidenceRootOverride = evidenceRoot,
            ConfigureDbContext = builder => builder.AddInterceptors(recorder.All),
            OverrideServices = services =>
            {
                services.AddSingleton<ILoggerProvider>(logs);
                FinalizationTimingDecorator.Register(services, log);
            },
        };
        using var client = factory.CreateClient();
        client.Timeout = Timeout.InfiniteTimeSpan;
        var context = new EnvelopeContext
        {
            OptionsSource = S1QualificationSupport.OptionsSource(factory.Services),
            Configuration = S1QualificationSupport.EffectiveConfiguration(factory.Services),
            CommandTimeoutSeconds = S1QualificationSupport.EffectiveCommandTimeoutSeconds(factory.Services),
        };
        var (videoId, jobId, cameraId) = await S1QualificationSupport.QueueAsync(factory, client);
        var (staged, shape) = await S1QualificationSupport.StageAsync(factory.Services.GetRequiredService<IMediaStore>(), jobId, 1, trackCount);

        using var probeClient = factory.CreateClient();
        await using var prober = new ApiContentionProber(probeClient,
            ["/api/health", "/api/videos", $"/api/videos/{videoId}/processing", $"/api/tracks?cameraId={cameraId}"], TimeSpan.FromMilliseconds(500));
        prober.Start();
        await Task.Delay(baseline);

        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        Assert.Equal(jobId, lease.JobId);
        var request = S1QualificationSupport.Request(lease, staged, WorkerContractRules.CompletionSchemaVersionV31);
        var cpuBefore = Process.GetCurrentProcess().TotalProcessorTime;
        using (var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request))
        {
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        }

        prober.Phase("during");
        var acceptedAt = (await StateAsync(factory, jobId)).AcceptedAtUtc!.Value;
        var options = context.Configuration;
        var ceiling = TimeSpan.FromSeconds((int)options["MaximumFinalizationDurationSeconds"] + (int)options["ClaimSeconds"] + (int)options["PollIntervalSeconds"] + 60);
        var rss = new List<long>();
        var visibility = new VisibilityTally();
        var deadline = DateTime.UtcNow + ceiling;
        VisionJobStatus status;
        while (true)
        {
            rss.Add(Process.GetCurrentProcess().WorkingSet64);
            var pending = log.PendingTracks(jobId);
            visibility.Add(await VisibilityChecks.ProbeAsync(factory.ConnectionString, client, videoId, cameraId, jobId, pending), pending);
            status = (await StateAsync(factory, jobId)).Status;
            if (status is VisionJobStatus.Completed or VisionJobStatus.Failed) break;
            Assert.True(DateTime.UtcNow < deadline, "the job did not reach a terminal state within the effective bound");
            // Once the graph is built the ids exist and the publication window is short: probe
            // it closely enough to read Track detail inside it.
            await Task.Delay(pending.Count > 0 ? 100 : 1000);
        }

        prober.Phase("after");
        var cpuSeconds = (Process.GetCurrentProcess().TotalProcessorTime - cpuBefore).TotalSeconds;
        Assert.Equal(VisionJobStatus.Completed, status);
        // After publication the graph is visible, with its counts.
        var afterStatus = await ProcessingAsync(client, videoId);
        Assert.Equal("completed", afterStatus.Phase);
        Assert.Equal(trackCount, afterStatus.TracksCreated);

        var contention = prober.Result();
        var detailAfterPublication = new List<int>();
        foreach (var trackId in log.PendingTracks(jobId))
        {
            using var detail = await client.GetAsync($"/api/tracks/{trackId}");
            detailAfterPublication.Add((int)detail.StatusCode);
        }

        var calls = log.For(jobId);
        var timelines = recorder.Analyze(jobId);
        var publishCalls = calls.Where(c => c.Method == nameof(IVisionFinalizationLifecycle.PublishAsync)).ToList();
        string TransitionOf(PublicationTimeline t) =>
            publishCalls.FirstOrDefault(c => c.EnterTicks <= t.Ticks.GetValueOrDefault("transactionBegun") && t.Ticks.GetValueOrDefault("transactionBegun") <= c.ExitTicks)?.Result ?? "unknown";
        var published = timelines.Where(t => t.Committed && TransitionOf(t) == "Published").ToList();
        var rejected = timelines.Except(published).Select(t => (object)new { reason = t.Committed ? TransitionOf(t) : "not committed", timeline = t.ToOutput(TransitionOf(t)) }).ToList();
        var timeline = Assert.Single(published);
        Assert.Empty(timeline.OrderingProblems());

        var extensions = calls.Where(c => c.Method == nameof(IVisionFinalizationLifecycle.ExtendClaimAsync)).ToList();
        var claim = calls.First(c => c.Method == nameof(IVisionFinalizationLifecycle.ClaimNextAsync) && c.Result == "claimed");
        var load = calls.Last(c => c.Method == nameof(IVisionFinalizationLifecycle.LoadInputsAsync));
        var (buildStart, buildEnd, buildClean) = GraphBuildBracketTicks(calls);
        var published1504 = logs.Entries.Where(e => e.EventId.Id == 1504).Select(e => e.Message).ToList();
        var message = Assert.Single(published1504);
        var created = int.Parse(Created.Match(message).Groups[1].Value, CultureInfo.InvariantCulture);
        var adopted = int.Parse(Adopted.Match(message).Groups[1].Value, CultureInfo.InvariantCulture);
        Assert.Equal(shape.StagedObjects, S1QualificationSupport.FileCount(evidenceRoot));

        var values = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["acceptedAtUtc"] = acceptedAt.ToString("O", CultureInfo.InvariantCulture),
            ["publicationTimeline"] = timeline.ToOutput("Published"),
            ["graphBuildBracket"] = new { lastExtensionReturned = buildStart, publishEntered = buildEnd },
            ["bracketProofs"] = new
            {
                graphPersistenceBracketContainsOnlyAddAsync = timeline.GraphPersistenceBracketContainsOnlyAddAsync,
                graphBuildBracketContainsNoLifecycleCall = buildClean,
                singleBarrierCommand = timeline.SingleBarrierCommand,
            },
            ["publications"] = published.Count,
            // nextval calls inside this job's PublishAsync (search and analytics snapshots also
            // allocate from the same sequence, outside any publication scope).
            ["sequenceAllocations"] = sequences.In(timeline.Scope),
            ["runVisibilitySequence"] = await RunVisibilitySequenceAsync(factory.ConnectionString, jobId),
            // Which visibility checks ran, and what each found (the checker needs them all).
            ["visibility"] = visibility.ToOutput(detailAfterPublication),
            ["prematureVisibilityObserved"] = visibility.Total,
            ["prematureVisibilityProbes"] = visibility.Probes,
            ["extensionCount"] = extensions.Count,
            ["createdObjects"] = created,
            ["adoptedObjects"] = adopted,
            ["acceptedEvidenceFiles"] = S1QualificationSupport.FileCount(evidenceRoot),
            ["longestCommandMs"] = LongestCommandMs(recorder),
            ["claimAcquisitionMs"] = (claim.ExitUtc - acceptedAt).TotalMilliseconds,
            ["payloadLoadMs"] = S1QualificationSupport.TicksMs(load.EnterTicks, load.ExitTicks),
            ["payloadRevalidationAndPlanMs"] = S1QualificationSupport.TicksMs(load.ExitTicks, extensions[0].EnterTicks),
            ["sealWallMs"] = S1QualificationSupport.TicksMs(extensions[0].ExitTicks, extensions[^1].ExitTicks),
            ["perBatchWallMs"] = extensions.Zip(extensions.Skip(1), (a, b) => S1QualificationSupport.TicksMs(a.ExitTicks, b.ExitTicks)).ToList(),
            ["throughputTracksPerSecond"] = trackCount / ((timeline.CommitCompletedUtc!.Value - acceptedAt).TotalSeconds),
            ["event1504CrossCheck"] = message,
            // This sample's own API record: an error in any sample is a failure, not only the first's.
            ["apiContention"] = contention,
            ["apiHostRss"] = new { samplesBytes = rss, peakBytes = rss.Max() },
            ["apiProcessCpuSeconds"] = cpuSeconds,
        };
        return new EnvelopeSample(values, context, rejected);
    }

    private static async Task<long?> RunVisibilitySequenceAsync(string connectionString, Guid jobId)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("SELECT r.visibility_sequence FROM processing_runs r JOIN vision_jobs j ON j.processing_run_id = r.id WHERE j.id = $1", connection);
        command.Parameters.AddWithValue(jobId);
        return await command.ExecuteScalarAsync() is long value ? value : null;
    }

    /// <summary>Live finalization claims across every job, as the health count defines them.</summary>
    internal const string LiveClaimsSql =
        "SELECT count(*) FROM vision_jobs WHERE status = 'Finalizing' AND finalization_claim_token_hash IS NOT NULL AND finalization_claim_expires_at_utc > now()";

    /// <summary>F4 plan §9.2 concurrency behaviour: an integrity check, not a timing.</summary>
    /// <remarks>
    /// Two worst-shape jobs
    /// handed off back to back under <c>MaxConcurrentFinalizations</c> from configuration. Live
    /// claims are sampled throughout; with a limit of one, the second job must stay unclaimed
    /// until the first has published, and both must publish exactly once. None of that means
    /// anything unless the two actually overlapped, so the sampler also retains the first
    /// atomic snapshot (<see cref="OverlapSnapshot"/>) in which the first job is Finalizing under
    /// a live claim while the second, already durably handed off, is Finalizing and unclaimed;
    /// and each job's accepted and completed times, so the checker can refuse a run in which the
    /// second hand-off came after the first had already completed.
    /// </remarks>
    private static async Task<object> ConcurrencyOnceAsync(string mediaRoot, string evidenceRoot, int trackCount, SequenceAllocationObserver sequences)
    {
        Empty(mediaRoot);
        Empty(evidenceRoot);
        await S1QualificationSupport.ResetDatabaseAsync(mediaRoot, evidenceRoot);
        var recorder = new PublicationTimelineRecorder();
        var log = new LifecycleCallLog();
        using var factory = new ApiTestFactory
        {
            EnableAsynchronousFinalization = true,
            EnableVisionFinalizationHost = true,
            MediaRootOverride = mediaRoot,
            EvidenceRootOverride = evidenceRoot,
            ConfigureDbContext = builder => builder.AddInterceptors(recorder.All),
            OverrideServices = services => FinalizationTimingDecorator.Register(services, log),
        };
        using var client = factory.CreateClient();
        client.Timeout = Timeout.InfiniteTimeSpan;
        var configuration = S1QualificationSupport.EffectiveConfiguration(factory.Services);
        var limit = (int)configuration["MaxConcurrentFinalizations"];
        var (_, first, _) = await S1QualificationSupport.QueueAsync(factory, client);
        var (_, second, _) = await S1QualificationSupport.QueueAsync(factory, client);
        var store = factory.Services.GetRequiredService<IMediaStore>();
        var (stagedFirst, _) = await S1QualificationSupport.StageAsync(store, first, 1, trackCount);
        var (stagedSecond, _) = await S1QualificationSupport.StageAsync(store, second, 1, trackCount);

        var samples = new List<long>();
        var secondClaimedBeforeFirstPublished = false;
        OverlapSnapshot? overlap = null;
        var overlapSnapshots = 0;
        using var cancel = new CancellationTokenSource();
        var sampler = Task.Run(async () =>
        {
            while (!cancel.IsCancellationRequested)
            {
                // One statement, one snapshot of both jobs and the live claims.
                var snapshot = await OverlapSnapshot.TakeAsync(factory.ConnectionString, first, second);
                samples.Add(snapshot.LiveClaims);
                if (snapshot.FirstStatus != nameof(VisionJobStatus.Completed) && snapshot.SecondClaimed) secondClaimedBeforeFirstPublished = true;
                if (snapshot.IsOverlap)
                {
                    overlap ??= snapshot;
                    overlapSnapshots++;
                }

                await Task.Delay(50);
            }
        });

        foreach (var (jobId, staged) in new[] { (first, stagedFirst), (second, stagedSecond) })
        {
            var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
            Assert.Equal(jobId, lease.JobId);
            using var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", S1QualificationSupport.Request(lease, staged, WorkerContractRules.CompletionSchemaVersionV31));
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        }

        var ceiling = TimeSpan.FromSeconds(2 * ((int)configuration["MaximumFinalizationDurationSeconds"] + (int)configuration["ClaimSeconds"] + (int)configuration["PollIntervalSeconds"]) + 60);
        var deadline = DateTime.UtcNow + ceiling;
        while (true)
        {
            var states = new[] { (await StateAsync(factory, first)).Status, (await StateAsync(factory, second)).Status };
            if (states.All(s => s is VisionJobStatus.Completed or VisionJobStatus.Failed)) break;
            Assert.True(DateTime.UtcNow < deadline, "the two jobs did not reach a terminal state within twice the effective bound");
            await Task.Delay(500);
        }

        await cancel.CancelAsync();
        await sampler;
        var jobs = new List<object>();
        foreach (var jobId in new[] { first, second })
        {
            var published = recorder.Analyze(jobId).Where(t => t.Committed).ToList();
            var publishes = log.For(jobId).Count(c => c.Method == nameof(IVisionFinalizationLifecycle.PublishAsync) && c.Result == "Published");
            var (acceptedAtUtc, completedAtUtc) = await HandOffTimesAsync(factory.ConnectionString, jobId);
            jobs.Add(new
            {
                jobId,
                finalState = (await StateAsync(factory, jobId)).Status.ToString(),
                publications = publishes,
                sequenceAllocations = published.Sum(t => sequences.In(t.Scope)),
                acceptedAtUtc,
                completedAtUtc,
            });
        }

        return new
        {
            maxConcurrentFinalizations = limit,
            jobs,
            liveClaimSamples = samples,
            maxLiveClaims = samples.DefaultIfEmpty(0).Max(),
            secondClaimedBeforeFirstPublished,
            // Observed, never assumed: null unless a snapshot showed the overlap.
            overlapObserved = overlap is not null,
            overlapSnapshot = overlap?.ToOutput(),
            overlapSnapshots,
        };
    }

    /// <summary>The job's durable hand-off time and its completion time, from the database.</summary>
    internal static async Task<(DateTimeOffset? AcceptedAtUtc, DateTimeOffset? CompletedAtUtc)> HandOffTimesAsync(string connectionString, Guid jobId)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("SELECT finalization_accepted_at_utc, completed_at_utc FROM vision_jobs WHERE id = $1", connection);
        command.Parameters.AddWithValue(jobId);
        await using var reader = await command.ExecuteReaderAsync();
        await reader.ReadAsync();
        return (reader.IsDBNull(0) ? null : reader.GetFieldValue<DateTimeOffset>(0), reader.IsDBNull(1) ? null : reader.GetFieldValue<DateTimeOffset>(1));
    }

    private static async Task<object> ReferenceOnceAsync(string mediaRoot, string evidenceRoot, int trackCount)
    {
        Empty(mediaRoot);
        Empty(evidenceRoot);
        await S1QualificationSupport.ResetDatabaseAsync(mediaRoot, evidenceRoot);
        var recorder = new PublicationTimelineRecorder();
        // The synchronous path: the gate off, completion 3.0, the same instrument.
        using var factory = new ApiTestFactory { MediaRootOverride = mediaRoot, EvidenceRootOverride = evidenceRoot, ConfigureDbContext = builder => builder.AddInterceptors(recorder.All) };
        using var client = factory.CreateClient();
        client.Timeout = Timeout.InfiniteTimeSpan;
        var (_, jobId, _) = await S1QualificationSupport.QueueAsync(factory, client);
        var (staged, _) = await S1QualificationSupport.StageAsync(factory.Services.GetRequiredService<IMediaStore>(), jobId, 1, trackCount);
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        using var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", S1QualificationSupport.Request(lease, staged, "3.0"));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var timeline = Assert.Single(recorder.Analyze(jobId, scopedOnly: false), t => t.Committed);
        Assert.Empty(timeline.OrderingProblems());
        return new { publicationTimeline = timeline.ToOutput("Published"), barrierHoldMs = timeline.BarrierHoldMs };
    }

    private static double LongestCommandMs(PublicationTimelineRecorder recorder)
    {
        var events = recorder.Events;
        var started = events.Where(e => e.Kind == TimelineEventKind.CommandExecuting && e.CommandId is not null)
            .GroupBy(e => e.CommandId!.Value).ToDictionary(g => g.Key, g => g.Min(e => e.Ticks));
        return events.Where(e => e.Kind == TimelineEventKind.CommandExecuted && e.CommandId is { } id && started.ContainsKey(id))
            .Select(e => S1QualificationSupport.TicksMs(started[e.CommandId!.Value], e.Ticks))
            .DefaultIfEmpty(0).Max();
    }

    private sealed record JobState(VisionJobStatus Status, DateTimeOffset? AcceptedAtUtc);

    private static async Task<JobState> StateAsync(ApiTestFactory factory, Guid jobId)
    {
        using var scope = factory.Services.CreateScope();
        var job = await scope.ServiceProvider.GetRequiredService<MaviDbContext>().VisionJobs.AsNoTracking().SingleAsync(x => x.Id == jobId);
        return new JobState(job.Status, job.FinalizationAcceptedAtUtc);
    }

    private sealed record RunStatus(string Phase, int TracksCreated);

    private static async Task<RunStatus> ProcessingAsync(HttpClient client, Guid videoId)
    {
        using var document = JsonDocument.Parse(await client.GetStringAsync($"/api/videos/{videoId}/processing"));
        var run = document.RootElement.GetProperty("latestRun");
        return new RunStatus(run.GetProperty("phase").GetString()!, run.GetProperty("tracksCreated").GetInt32());
    }
}
