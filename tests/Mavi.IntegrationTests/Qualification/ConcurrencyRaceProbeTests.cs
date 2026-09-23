using System.Data.Common;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.Infrastructure.SceneAnalytics;
using Mavi.Infrastructure.Storage;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Logging.Abstractions;
using Npgsql;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// Plan §12 / exit-gate item 9: snapshot and revision consistency while a writer
/// actually races a reader.
/// </summary>
/// <remarks>
/// <para>
/// The existing ordering tests prove the barrier is taken in the right place, and the
/// sequential tests prove what each side sees before and after a publication. Neither
/// puts a writer <i>inside</i> a reader. These do: the reader is stopped at a chosen
/// statement by an interceptor or a repository decorator, the writer is started while
/// it is stopped, and only then is the reader let go.
/// </para>
/// <para>
/// No sleep decides an outcome. The only wait is for an observable database fact —
/// a writer's advisory-lock request appearing in <c>pg_locks</c> as not granted — and
/// it is bounded so a regression fails rather than hangs.
/// </para>
/// <para>
/// There are two protections, and each probe names the one it exercises. A read that
/// resolves its scope and reads its facts in one transaction holds the shared barrier,
/// so a publication must <b>wait</b> for it. The heatmap reads evidence outside any
/// transaction after its scope has committed, so a publication can land in that gap;
/// there the protection is that everything after the scope is <b>pinned</b> to the
/// identity and snapshot the scope resolved.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class ConcurrencyRaceProbeTests(PostgresFixture fixture) : IDisposable
{
    private const int Runs = 4;
    private const int TracksPerRun = 25;
    private static readonly TimeSpan Bound = TimeSpan.FromSeconds(30);

    private static readonly SceneAnalyticsOptions Options = new()
    {
        LeaseSeconds = 900,
        MaxUnitDurationSeconds = 600,
        ReclaimGraceSeconds = 60,
        MaximumAttempts = 3,
    };

    private static SceneAnalysisExecutionIdentity Identity { get; } =
        new(QualificationCorpus.AlgorithmVersion, QualificationCorpus.ParametersSha256);

    private readonly List<MaviDbContext> _contexts = [];

    public void Dispose()
    {
        foreach (var context in _contexts) context.Dispose();
    }

    [Fact]
    public async Task AnAggregateStoppedInsideItsSnapshotIsUnmovedByAUnitCompletionThatMustWaitForIt()
    {
        var manifest = await CorpusAsync();
        var revision2 = await ActivateRevisionAsync(manifest);
        var claim = await QueueAndClaimAsync(manifest.RunIds[0], revision2);
        var query = new AnalyticsAggregateQuery(manifest.CameraId, manifest.WindowFromUtc, manifest.WindowToUtc, 3_600, null);

        // The answer before anything races it: revision 2 is active and nothing has yet
        // been evaluated against it.
        var before = await new AnalyticsAggregateRepository(Context()).AggregateAsync(query, default);
        Assert.Equal(revision2, before.Identity!.SceneRevisionId);
        Assert.Equal(0, before.Coverage!.EvaluatedRuns);

        // Stopped just before its first fact read — after it has taken the shared
        // barrier, allocated its snapshot and resolved its scope and coverage.
        var pause = new PauseInterceptor(sql => sql.Contains("track_zone_visits", StringComparison.Ordinal) && sql.TrimStart().StartsWith("SELECT", StringComparison.OrdinalIgnoreCase));
        var reading = new AnalyticsAggregateRepository(Context(pause)).AggregateAsync(query, default);
        await pause.Reached.WaitAsync(Bound);

        // The unit computes its facts outside any transaction and then must publish
        // them. It gets as far as the exclusive barrier and no further.
        var writing = Executor(manifest).ExecuteAsync(claim, Identity, Options, default);
        await WaitForAWaitingAdvisoryLockAsync();
        Assert.False(writing.IsCompleted);

        pause.Release();
        var during = await reading;

        // Wholly on the near side of the publication: same identity, same coverage,
        // same facts as the answer taken before the writer existed.
        Assert.True(during.IsSuccess);
        Assert.Equal(before.Identity.SceneRevisionId, during.Identity!.SceneRevisionId);
        Assert.Equal(before.Coverage, during.Coverage);
        AssertSameFacts(before.Facts!, during.Facts!);

        var written = await writing.WaitAsync(Bound);
        Assert.True(written.IsSuccess);
        var unit = await UnitAsync(claim.AnalysisId);
        Assert.True(unit.VisibilitySequence > during.Identity.SnapshotVisibilitySequence);

        // And the next reader sees the publication in full: the run is evaluated and
        // every one of its Tracks is counted, not some of them.
        var after = await new AnalyticsAggregateRepository(Context()).AggregateAsync(query, default);
        Assert.Equal(revision2, after.Identity!.SceneRevisionId);
        Assert.Equal(1, after.Coverage!.EvaluatedRuns);
        Assert.Equal(TracksPerRun, after.Coverage.AnalysedTracks);
        Assert.Equal(TracksPerRun, after.Facts!.TrackIntervals.Count);
    }

    [Fact]
    public async Task AHeatmapStoppedBetweenItsScopeAndItsEvidenceDrawsTheWorldItsScopeResolved()
    {
        var manifest = await CorpusAsync();
        var query = new AnalyticsHeatmapQuery(manifest.CameraId, manifest.WindowFromUtc, manifest.WindowToUtc, null, 64, null);

        var before = await Service(new AnalyticsAggregateRepository(Context()), manifest).HeatmapAsync(query, default);
        Assert.True(before.IsSuccess);
        Assert.Equal(manifest.RevisionId, before.Identity!.SceneRevisionId);
        Assert.Equal(Runs * TracksPerRun, before.TrackCount);

        // Stopped after the scope has resolved and committed, before the candidate
        // listing and the first artefact read. Nothing is held across this gap.
        var paused = new PausingRepository(new AnalyticsAggregateRepository(Context()));
        var drawing = Service(paused, manifest).HeatmapAsync(query, default);
        await paused.Reached.WaitAsync(Bound);

        // Two publications land in the gap, and neither has to wait: a new revision is
        // activated, and a unit is analysed and published against it. Both complete
        // while the heatmap is stopped.
        var revision2 = await ActivateRevisionAsync(manifest).WaitAsync(Bound);
        var claim = await QueueAndClaimAsync(manifest.RunIds[0], revision2);
        var written = await Executor(manifest).ExecuteAsync(claim, Identity, Options, default).WaitAsync(Bound);
        Assert.True(written.IsSuccess);
        Assert.False(drawing.IsCompleted);

        paused.Release();
        var during = await drawing.WaitAsync(Bound);

        // Revision 1's map, exactly. Had the listing followed the activation it would
        // have read revision 2's single run; had it followed the new unit without its
        // revision it would have counted run 0's Tracks twice.
        Assert.True(during.IsSuccess);
        Assert.Equal(before.Identity.SceneRevisionId, during.Identity!.SceneRevisionId);
        Assert.Equal(before.Coverage, during.Coverage);
        Assert.Equal(before.TrackCount, during.TrackCount);
        Assert.Equal(before.Grid!.Values, during.Grid!.Values);

        // The next heatmap is revision 2's, and only what revision 2 has evaluated.
        var after = await Service(new AnalyticsAggregateRepository(Context()), manifest).HeatmapAsync(query, default);
        Assert.True(after.IsSuccess);
        Assert.Equal(revision2, after.Identity!.SceneRevisionId);
        Assert.Equal(1, after.Coverage!.EvaluatedRuns);
        Assert.Equal(TracksPerRun, after.TrackCount);
        Assert.Equal((long)TracksPerRun * QualificationCorpus.SealedTrajectorySampleCount, after.Grid!.SampleCount);
    }

    [Fact]
    public async Task ARevisionActivationWaitsForAUnitCommitAlreadyHoldingThePublicationBarrier()
    {
        var manifest = await CorpusAsync();
        var revision2 = await ActivateRevisionAsync(manifest);
        var claim = await QueueAndClaimAsync(manifest.RunIds[0], revision2);

        // Stopped immediately after the commit has taken the exclusive barrier: its
        // facts are written but uncommitted, and its sequence is about to be allocated.
        var pause = new PauseInterceptor(
            sql => sql.Contains("pg_advisory_xact_lock(", StringComparison.Ordinal),
            afterExecution: true);
        var committing = Executor(manifest, pause).ExecuteAsync(claim, Identity, Options, default);
        await pause.Reached.WaitAsync(Bound);

        var activating = ActivateRevisionAsync(manifest);
        await WaitForAWaitingAdvisoryLockAsync();
        Assert.False(activating.IsCompleted);

        // Nothing is observable yet: the unit's facts are inside an open transaction.
        Assert.Null((await UnitAsync(claim.AnalysisId)).VisibilitySequence);

        pause.Release();
        Assert.True((await committing.WaitAsync(Bound)).IsSuccess);
        var revision3 = await activating.WaitAsync(Bound);

        // The unit published under its own pinned identity, revision 2; the activation
        // landed after it. Neither was interleaved into the other.
        var unit = await UnitAsync(claim.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Completed, unit.Status);
        Assert.Equal(revision2, unit.RevisionId);
        Assert.NotNull(unit.VisibilitySequence);

        // Revision 3 is current and has evaluated nothing, so revision 2's facts are
        // not read as revision 3's: its coverage reports every run unevaluated.
        var current = await new AnalyticsAggregateRepository(Context()).AggregateAsync(
            new AnalyticsAggregateQuery(manifest.CameraId, manifest.WindowFromUtc, manifest.WindowToUtc, 3_600, null),
            default);
        Assert.Equal(revision3, current.Identity!.SceneRevisionId);
        Assert.Equal(0, current.Coverage!.EvaluatedRuns);
        Assert.Equal(0, current.Coverage.AnalysedTracks);
        Assert.False(current.Coverage.Complete);
        Assert.Empty(current.Facts!.TrackIntervals);
    }

    // --- World ---------------------------------------------------------------

    private Task<CorpusManifest> CorpusAsync() =>
        new QualificationCorpus(fixture).BuildAsync(
            seed: 20260922,
            videoCount: Runs,
            tracksPerRun: TracksPerRun,
            zoneCount: 4,
            lineCount: 2,
            visitsPerTrack: 1,
            crossingsPerTrack: 1,
            sealTrajectories: true);

    private async Task<Guid> ActivateRevisionAsync(CorpusManifest manifest)
    {
        await using var db = fixture.CreateDbContext();
        var repository = new SceneConfigurationRepository(db);
        var configuration = await repository.GetByCameraAsync(manifest.CameraId, default)
            ?? throw new InvalidOperationException("The corpus camera has no scene configuration.");
        var active = await repository.GetRevisionAsync(configuration.ActiveRevisionId!.Value, default);
        var revision = configuration.SaveRevision(
            active,
            QualificationScene.Draft(4, 2),
            active!.RevisionNumber,
            SceneRules.UnattributedDevelopmentActor,
            DateTimeOffset.UtcNow);
        await repository.AddRevisionAsync(revision, default);
        await repository.SaveChangesAsync(default);
        return revision.Id;
    }

    private async Task<SceneAnalysisClaim> QueueAndClaimAsync(Guid runId, Guid revisionId)
    {
        var db = Context();
        var lifecycle = new SceneAnalysisLifecycle(db, TimeProvider.System);
        var queued = await lifecycle.RequestAnalysisAsync(
            new SceneAnalysisIdentity(
                runId, revisionId, QualificationCorpus.AlgorithmVersion, QualificationCorpus.ParametersSha256, null),
            default);
        Assert.Equal(SceneAnalysisQueueOutcome.Created, queued.Outcome);

        var claim = await lifecycle.ClaimNextAsync(Identity, Options.ToLeasePolicy(), default);
        Assert.NotNull(claim);
        Assert.Equal(queued.AnalysisId, claim.AnalysisId);
        return claim;
    }

    private SceneAnalysisExecutor Executor(CorpusManifest manifest, IInterceptor? interceptor = null)
    {
        var db = Context(interceptor);
        return new SceneAnalysisExecutor(
            new SceneAnalysisLifecycle(db, TimeProvider.System),
            new SceneAnalysisEvidenceReader(db, Accepted(manifest)),
            new SceneConfigurationRepository(db),
            NullLogger<SceneAnalysisExecutor>.Instance);
    }

    private static AnalyticsAggregateService Service(IAnalyticsAggregateRepository repository, CorpusManifest manifest) =>
        new(repository, new HeatmapEvidenceReader(Accepted(manifest)), NullLogger<AnalyticsAggregateService>.Instance);

    private static AcceptedEvidenceReader Accepted(CorpusManifest manifest) =>
        new(Microsoft.Extensions.Options.Options.Create(new MediaStorageOptions
        {
            RootPath = manifest.MediaRoot!,
            EvidenceRootPath = manifest.EvidenceRoot!,
        }));

    private MaviDbContext Context(IInterceptor? interceptor = null)
    {
        var builder = new DbContextOptionsBuilder<MaviDbContext>()
            .UseNpgsql(fixture.ConnectionString, npgsql => npgsql.UseVector());
        if (interceptor is not null) builder.AddInterceptors(interceptor);
        var db = new MaviDbContext(builder.Options);
        _contexts.Add(db);
        return db;
    }

    private async Task<SceneAnalysis> UnitAsync(Guid analysisId)
    {
        await using var db = fixture.CreateDbContext();
        return await db.SceneAnalyses.AsNoTracking().SingleAsync(unit => unit.Id == analysisId);
    }

    /// <summary>
    /// Returns once some session is waiting for an advisory lock it has not been
    /// granted — the writer, queued behind the barrier the stopped party holds.
    /// </summary>
    private async Task WaitForAWaitingAdvisoryLockAsync()
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        using var deadline = new CancellationTokenSource(Bound);
        while (true)
        {
            await using var command = new NpgsqlCommand(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted", connection);
            if ((long)(await command.ExecuteScalarAsync(deadline.Token))! > 0) return;

            // Polling an observable condition, not timing an outcome: the assertion
            // that follows is about the lock table, never about how long this took.
            await Task.Delay(20, deadline.Token);
        }
    }

    private static void AssertSameFacts(AnalyticsFactSet expected, AnalyticsFactSet actual)
    {
        Assert.Equal(expected.Zones, actual.Zones);
        Assert.Equal(expected.Lines, actual.Lines);
        Assert.Equal(expected.ZoneVisits.Count, actual.ZoneVisits.Count);
        Assert.Equal(expected.LineCrossings.Count, actual.LineCrossings.Count);
        Assert.Equal(expected.ZoneSummaries.Count, actual.ZoneSummaries.Count);
        Assert.Equal(expected.TrackIntervals.Count, actual.TrackIntervals.Count);
    }

    /// <summary>
    /// Stops the first matching statement until released — before it executes, or
    /// after, so a lock it takes is held while stopped.
    /// </summary>
    private sealed class PauseInterceptor(Func<string, bool> matches, bool afterExecution = false) : DbCommandInterceptor
    {
        private readonly TaskCompletionSource _reached = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource _release = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _fired;

        public Task Reached => _reached.Task;

        public void Release() => _release.TrySetResult();

        public override async ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(
            DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result,
            CancellationToken cancellationToken = default)
        {
            if (!afterExecution) await StopIfMatchedAsync(command);
            return result;
        }

        public override async ValueTask<int> NonQueryExecutedAsync(
            DbCommand command, CommandExecutedEventData eventData, int result,
            CancellationToken cancellationToken = default)
        {
            if (afterExecution) await StopIfMatchedAsync(command);
            return result;
        }

        private async Task StopIfMatchedAsync(DbCommand command)
        {
            if (!matches(command.CommandText) || Interlocked.Exchange(ref _fired, 1) == 1) return;
            _reached.TrySetResult();
            await _release.Task;
        }
    }

    /// <summary>
    /// The real repository, stopped once its heatmap scope has resolved and committed.
    /// </summary>
    private sealed class PausingRepository(IAnalyticsAggregateRepository inner) : IAnalyticsAggregateRepository
    {
        private readonly TaskCompletionSource _reached = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource _release = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public Task Reached => _reached.Task;

        public void Release() => _release.TrySetResult();

        public Task<AnalyticsAggregateResult> AggregateAsync(AnalyticsAggregateQuery query, CancellationToken cancellationToken) =>
            inner.AggregateAsync(query, cancellationToken);

        public async Task<AnalyticsHeatmapScope> ResolveHeatmapScopeAsync(AnalyticsHeatmapQuery query, CancellationToken cancellationToken)
        {
            var scope = await inner.ResolveHeatmapScopeAsync(query, cancellationToken);
            _reached.TrySetResult();
            await _release.Task;
            return scope;
        }

        public Task<IReadOnlyList<HeatmapCandidateTrack>> ListHeatmapCandidatesAsync(
            AnalyticsHeatmapQuery query, AnalyticsResolvedIdentity identity, CancellationToken cancellationToken) =>
            inner.ListHeatmapCandidatesAsync(query, identity, cancellationToken);
    }
}
