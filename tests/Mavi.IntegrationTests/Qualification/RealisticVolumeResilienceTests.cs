using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Application.Modules.SceneAnalytics.Configuration;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Contracts.Api.Analytics;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.Infrastructure.SceneAnalytics;
using Mavi.Infrastructure.Storage;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// Plan §11 / exit-gate item 8: cancellation and failure at realistic volume, over
/// the same corpus the qualification harnesses measure.
/// </summary>
/// <remarks>
/// <para>
/// The one-Track tests in <c>SceneAnalyticsExecutorTests</c> and
/// <c>AnalyticsHeatmapRepositoryTests</c> prove each rule. These prove the rules still
/// hold when the interruption lands part-way through the heaviest work the product
/// accepts: the heatmap at its frozen 50-run / 2,000-Track envelope, and one
/// analytical unit over a 1,000-Track run.
/// </para>
/// <para>
/// Every interruption is placed deterministically, by counting evidence reads through
/// a decorator over the production reader, never by timing. So each test states
/// exactly how much work had been done when the interruption arrived and how much was
/// done after it, and a retry is compared with an uninterrupted answer rather than
/// with a number chosen to pass.
/// </para>
/// <para>
/// These run in the ordinary suite. The envelope corpus builds in seconds, and a
/// correctness property that only holds at volume is worth checking on every head,
/// on PostgreSQL 18 in CI, rather than once on one machine.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class RealisticVolumeResilienceTests(PostgresFixture fixture) : IDisposable
{
    private readonly List<MaviDbContext> _contexts = [];

    public void Dispose()
    {
        foreach (var context in _contexts) context.Dispose();
    }

    private const int Seed = 20260922;
    private const int UnitTracks = 1_000;
    private const int EnvelopeRuns = AnalyticsQueryRules.MaximumHeatmapRuns;
    private const int EnvelopeTracksPerRun = AnalyticsQueryRules.MaximumHeatmapTracks / AnalyticsQueryRules.MaximumHeatmapRuns;
    private const int EnvelopeTracks = AnalyticsQueryRules.MaximumHeatmapTracks;

    private static readonly SceneAnalyticsOptions Options = new()
    {
        LeaseSeconds = 900,
        MaxUnitDurationSeconds = 600,
        ReclaimGraceSeconds = 60,
        MaximumAttempts = 3,
    };

    private static SceneAnalysisExecutionIdentity Identity { get; } =
        new(QualificationCorpus.AlgorithmVersion, QualificationCorpus.ParametersSha256);

    // --- Heatmap at the envelope ---------------------------------------------

    [Fact]
    public async Task AHeatmapCancelledPartWayThroughItsEnvelopeReturnsNoMapAndStopsReading()
    {
        var manifest = await EnvelopeCorpusAsync();
        var query = HeatmapQuery(manifest);

        var baseline = await Heatmap(Production(manifest)).HeatmapAsync(query, default);
        AssertCompleteEnvelope(baseline);

        // Cancelled from inside the 500th artefact read, as a client disconnect would
        // arrive while the service is deep in its evidence loop.
        using var cancellation = new CancellationTokenSource();
        var counting = new CountingHeatmapReader(Production(manifest), cancelAt: 500, cancellation);

        await Assert.ThrowsAnyAsync<OperationCanceledException>(
            () => Heatmap(counting).HeatmapAsync(query, cancellation.Token));

        // No result object exists to be mapped onto a 200, and nothing was read after
        // the cancellation: the expensive work stopped at the next artefact boundary
        // instead of running the envelope out and discarding it.
        Assert.Equal(500, counting.Reads);

        // The heatmap persists nothing, so there is nothing to clean up — and the
        // proof of that is that the next request is exactly the uninterrupted answer.
        var retry = await Heatmap(Production(manifest)).HeatmapAsync(query, default);
        AssertSameMap(baseline, retry);
    }

    [Fact]
    public async Task AHeatmapWhoseEvidenceFailsPartWayThroughItsEnvelopeFailsClosedAndRecovers()
    {
        var manifest = await EnvelopeCorpusAsync();
        var query = HeatmapQuery(manifest);

        var baseline = await Heatmap(Production(manifest)).HeatmapAsync(query, default);
        AssertCompleteEnvelope(baseline);

        // The 1,337th candidate in the service's own read order. Its bytes are
        // replaced with another Track's sealed trajectory — decodable, well formed,
        // and not this Track's evidence. That is the case a decoder alone would pass.
        const int failing = 1_337;
        await using var db = fixture.CreateDbContext();
        var candidates = await new AnalyticsAggregateRepository(db).ListHeatmapCandidatesAsync(
            query, baseline.Identity!, default);
        Assert.Equal(EnvelopeTracks, candidates.Count);

        var victim = EvidencePath(manifest, candidates[failing - 1].StorageKey!);
        var donor = EvidencePath(manifest, candidates[0].StorageKey!);
        var original = await File.ReadAllBytesAsync(victim);
        await File.WriteAllBytesAsync(victim, await File.ReadAllBytesAsync(donor));

        var counting = new CountingHeatmapReader(Production(manifest));
        var failed = await Heatmap(counting).HeatmapAsync(query, default);

        // Not a thinner map: no map. 1,336 good Tracks had already been accumulated,
        // and none of them is returned as though it were the answer.
        Assert.Equal(AnalyticsFailure.EvidenceUnreadable, failed.Failure);
        Assert.Null(failed.Grid);
        Assert.Equal(0, failed.TrackCount);
        Assert.Equal(failing, counting.Reads);

        await File.WriteAllBytesAsync(victim, original);
        var recovered = await Heatmap(Production(manifest)).HeatmapAsync(query, default);
        AssertSameMap(baseline, recovered);
    }

    // --- One analytical unit over 1,000 Tracks --------------------------------

    [Fact]
    public async Task AUnitCancelledPartWayThroughAThousandTracksPublishesNothingAndIsReclaimedToTheFullAnswer()
    {
        var manifest = await UnitCorpusAsync();
        var clock = new MutableTimeProvider(manifest.WindowFromUtc.AddDays(1));

        await using var hostA = fixture.CreateDbContext();
        var lifecycleA = new SceneAnalysisLifecycle(hostA, clock);
        await lifecycleA.QueueEligibleUnitsAsync(
            QualificationCorpus.AlgorithmVersion, QualificationCorpus.ParametersSha256, null,
            manifest.WindowFromUtc.AddDays(-1), 50, default);
        var claimA = await lifecycleA.ClaimNextAsync(Identity, Options.ToLeasePolicy(), default);
        Assert.NotNull(claimA);

        // Host A is stopped after its 400th trajectory read.
        using var stopping = new CancellationTokenSource();
        var countingA = new CountingUnitReader(UnitReader(hostA, manifest), cancelAt: 400, stopping);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(
            () => Executor(hostA, lifecycleA, countingA).ExecuteAsync(claimA, Identity, Options, stopping.Token));
        Assert.Equal(400, countingA.Reads);

        // Nothing of the 400 Tracks already computed reached the database, and the unit
        // did not claim to have finished.
        var cancelled = await UnitAsync(claimA.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Running, cancelled.Status);
        Assert.Null(cancelled.VisibilitySequence);
        Assert.Equal(new FactCounts(0, 0, 0, 0, 0), await FactCountsAsync());

        // And a reader is told the run is pending, not that it holds zero activity.
        var pending = await CoverageAsync(manifest);
        Assert.Equal(1, pending.PendingRuns);
        Assert.Equal(0, pending.EvaluatedRuns);
        Assert.Equal(0, pending.AnalysedTracks);
        Assert.False(pending.Complete);

        // The abandoned lease holds until it and its grace have passed.
        await using var hostB = fixture.CreateDbContext();
        var lifecycleB = new SceneAnalysisLifecycle(hostB, clock);
        Assert.Null(await lifecycleB.ClaimNextAsync(Identity, Options.ToLeasePolicy(), default));

        clock.Advance(TimeSpan.FromSeconds(Options.LeaseSeconds + Options.ReclaimGraceSeconds + 1));
        var claimB = await lifecycleB.ClaimNextAsync(Identity, Options.ToLeasePolicy(), default);
        Assert.NotNull(claimB);
        Assert.Equal(claimA.AnalysisId, claimB.AnalysisId);
        Assert.Equal(claimA.AttemptCount + 1, claimB.AttemptCount);
        Assert.False(claimA.ClaimToken.Span.SequenceEqual(claimB.ClaimToken.Span));

        var result = await Executor(hostB, lifecycleB, UnitReader(hostB, manifest))
            .ExecuteAsync(claimB, Identity, Options, default);
        Assert.True(result.IsSuccess);
        Assert.Equal(UnitTracks, result.AnalysedTrackCount);
        Assert.Equal(0, result.UnavailableTrackCount);
        Assert.Equal(FullUnitAnswer, await FactCountsAsync());

        // Host A's claim is now stale at 1,000 Tracks exactly as it is at one: it can
        // neither complete nor fail the unit that replaced it.
        Assert.Equal(
            SceneAnalyticsErrorCodes.AttemptStale,
            (await lifecycleA.CommitFactsAsync(claimA, SceneAnalysisFacts.Empty, default)).ErrorCode);
        Assert.Equal(
            SceneAnalyticsErrorCodes.AttemptStale,
            (await lifecycleA.ReportFailureAsync(claimA, "late", null, Options.MaximumAttempts, default)).ErrorCode);
        Assert.Equal(FullUnitAnswer, await FactCountsAsync());

        var completed = await UnitAsync(claimB.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Completed, completed.Status);
        var covered = await CoverageAsync(manifest);
        Assert.Equal(1, covered.EvaluatedRuns);
        Assert.Equal(UnitTracks, covered.AnalysedTracks);
        Assert.True(covered.Complete);
    }

    [Fact]
    public async Task AUnitWhoseEvidenceStoreFailsPartWayThroughAThousandTracksPublishesNothingAndRetriesToTheFullAnswer()
    {
        var manifest = await UnitCorpusAsync();
        var clock = new MutableTimeProvider(manifest.WindowFromUtc.AddDays(1));

        await using var host = fixture.CreateDbContext();
        var lifecycle = new SceneAnalysisLifecycle(host, clock);
        await lifecycle.QueueEligibleUnitsAsync(
            QualificationCorpus.AlgorithmVersion, QualificationCorpus.ParametersSha256, null,
            manifest.WindowFromUtc.AddDays(-1), 50, default);
        var first = await lifecycle.ClaimNextAsync(Identity, Options.ToLeasePolicy(), default);
        Assert.NotNull(first);

        // An I/O fault on the 600th read says nothing about the evidence, so it must
        // fail the attempt rather than write the Track off as Unavailable.
        var faulting = new CountingUnitReader(UnitReader(host, manifest), faultAt: 600);
        var failed = await Executor(host, lifecycle, faulting).ExecuteAsync(first, Identity, Options, default);

        Assert.False(failed.IsSuccess);
        Assert.Equal(SceneAnalyticsErrorCodes.TrajectoryReadFailed, failed.FailureCode);
        Assert.Equal(600, faulting.Reads);
        Assert.Equal(new FactCounts(0, 0, 0, 0, 0), await FactCountsAsync());

        var requeued = await UnitAsync(first.AnalysisId);
        Assert.Equal(SceneAnalysisStatus.Queued, requeued.Status);
        Assert.Null(requeued.VisibilitySequence);
        Assert.Equal(1, (await CoverageAsync(manifest)).PendingRuns);

        var second = await lifecycle.ClaimNextAsync(Identity, Options.ToLeasePolicy(), default);
        Assert.NotNull(second);
        Assert.Equal(first.AnalysisId, second.AnalysisId);

        var result = await Executor(host, lifecycle, UnitReader(host, manifest))
            .ExecuteAsync(second, Identity, Options, default);
        Assert.True(result.IsSuccess);
        Assert.Equal(UnitTracks, result.AnalysedTrackCount);
        Assert.Equal(FullUnitAnswer, await FactCountsAsync());
        Assert.True((await CoverageAsync(manifest)).Complete);
    }

    /// <summary>
    /// What the seeded 1,000-Track unit derives when nothing interrupts it.
    /// </summary>
    /// <remarks>
    /// The same figures the qualification harness recorded on the Development machine
    /// (Windows, PostgreSQL 18), on the superseded Ubuntu pass and in this repository's
    /// Linux container: one outcome, one motion summary and four zone summaries per
    /// Track, 185 zone visits and 1,391 line crossings. Asserting the exact totals is
    /// what makes "the retry produced the full answer" a comparison rather than a
    /// count that is merely non-zero.
    /// </remarks>
    private static readonly FactCounts FullUnitAnswer = new(
        Outcomes: UnitTracks,
        ZoneVisits: 185,
        ZoneSummaries: UnitTracks * 4,
        LineCrossings: 1_391,
        MotionSummaries: UnitTracks);

    // --- Corpus ---------------------------------------------------------------

    private Task<CorpusManifest> EnvelopeCorpusAsync() =>
        new QualificationCorpus(fixture).BuildAsync(
            seed: Seed,
            videoCount: EnvelopeRuns,
            tracksPerRun: EnvelopeTracksPerRun,
            zoneCount: 4,
            lineCount: 2,
            visitsPerTrack: 1,
            crossingsPerTrack: 1,
            sealTrajectories: true);

    private Task<CorpusManifest> UnitCorpusAsync() =>
        new QualificationCorpus(fixture).BuildAsync(
            seed: Seed,
            videoCount: 1,
            tracksPerRun: UnitTracks,
            zoneCount: 4,
            lineCount: 2,
            visitsPerTrack: 0,
            crossingsPerTrack: 0,
            sealTrajectories: true,
            completeUnits: false);

    private static AnalyticsHeatmapQuery HeatmapQuery(CorpusManifest manifest) =>
        new(manifest.CameraId, manifest.WindowFromUtc, manifest.WindowToUtc, null, 64, null);

    private static AcceptedEvidenceReader Accepted(CorpusManifest manifest) =>
        new(Microsoft.Extensions.Options.Options.Create(new MediaStorageOptions
        {
            RootPath = manifest.MediaRoot!,
            EvidenceRootPath = manifest.EvidenceRoot!,
        }));

    private static HeatmapEvidenceReader Production(CorpusManifest manifest) => new(Accepted(manifest));

    private static SceneAnalysisEvidenceReader UnitReader(MaviDbContext db, CorpusManifest manifest) =>
        new(db, Accepted(manifest));

    private AnalyticsAggregateService Heatmap(IHeatmapEvidenceReader reader)
    {
        var db = fixture.CreateDbContext();
        _contexts.Add(db);
        return new AnalyticsAggregateService(
            new AnalyticsAggregateRepository(db),
            reader,
            NullLogger<AnalyticsAggregateService>.Instance);
    }

    private static SceneAnalysisExecutor Executor(
        MaviDbContext db,
        SceneAnalysisLifecycle lifecycle,
        ISceneAnalysisEvidenceReader reader) =>
        new(lifecycle, reader, new SceneConfigurationRepository(db), NullLogger<SceneAnalysisExecutor>.Instance);

    private static string EvidencePath(CorpusManifest manifest, string storageKey) =>
        Path.Combine(
            manifest.EvidenceRoot!,
            storageKey["evidence/".Length..].Replace('/', Path.DirectorySeparatorChar));

    private async Task<SceneAnalysis> UnitAsync(Guid analysisId)
    {
        await using var db = fixture.CreateDbContext();
        return await db.SceneAnalyses.AsNoTracking().SingleAsync(unit => unit.Id == analysisId);
    }

    private async Task<FactCounts> FactCountsAsync()
    {
        await using var db = fixture.CreateDbContext();
        return new FactCounts(
            await db.TrackAnalysisOutcomes.CountAsync(),
            await db.TrackZoneVisits.CountAsync(),
            await db.TrackZoneSummaries.CountAsync(),
            await db.TrackLineCrossings.CountAsync(),
            await db.TrackMotionSummaries.CountAsync());
    }

    private async Task<Mavi.Application.Modules.Intelligence.TrackAnalyticsCoverage> CoverageAsync(CorpusManifest manifest)
    {
        await using var db = fixture.CreateDbContext();
        var result = await new AnalyticsAggregateRepository(db).AggregateAsync(
            new AnalyticsAggregateQuery(manifest.CameraId, manifest.WindowFromUtc, manifest.WindowToUtc, 3_600, null),
            default);
        Assert.True(result.IsSuccess);
        return result.Coverage!;
    }

    private static void AssertCompleteEnvelope(AnalyticsHeatmapResult result)
    {
        Assert.Equal(AnalyticsFailure.None, result.Failure);
        Assert.Equal(EnvelopeTracks, result.TrackCount);
        Assert.Equal((long)EnvelopeTracks * QualificationCorpus.SealedTrajectorySampleCount, result.Grid!.SampleCount);
    }

    private static void AssertSameMap(AnalyticsHeatmapResult expected, AnalyticsHeatmapResult actual)
    {
        Assert.Equal(AnalyticsFailure.None, actual.Failure);
        Assert.Equal(expected.Identity!.SceneRevisionId, actual.Identity!.SceneRevisionId);
        Assert.Equal(expected.Identity.AlgorithmVersion, actual.Identity.AlgorithmVersion);
        Assert.Equal(expected.Coverage, actual.Coverage);
        Assert.Equal(expected.TrackCount, actual.TrackCount);
        Assert.Equal(expected.Grid!.SampleCount, actual.Grid!.SampleCount);
        Assert.Equal(expected.Grid.Values, actual.Grid.Values);
    }

    private sealed record FactCounts(
        int Outcomes,
        int ZoneVisits,
        int ZoneSummaries,
        int LineCrossings,
        int MotionSummaries);

    /// <summary>
    /// The production heatmap reader, counted, and optionally cancelled from inside a
    /// chosen read.
    /// </summary>
    private sealed class CountingHeatmapReader(
        IHeatmapEvidenceReader inner,
        int cancelAt = 0,
        CancellationTokenSource? cancellation = null) : IHeatmapEvidenceReader
    {
        public int Reads { get; private set; }

        public async Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken)
        {
            var payload = await inner.ReadTrajectoryAsync(storageKey, cancellationToken);
            Reads++;
            if (Reads == cancelAt)
            {
                await cancellation!.CancelAsync();
            }

            return payload;
        }
    }

    /// <summary>
    /// The production unit evidence reader, counted, and optionally cancelled or
    /// faulted at a chosen read.
    /// </summary>
    private sealed class CountingUnitReader(
        ISceneAnalysisEvidenceReader inner,
        int cancelAt = 0,
        CancellationTokenSource? cancellation = null,
        int faultAt = 0) : ISceneAnalysisEvidenceReader
    {
        public int Reads { get; private set; }

        public Task<IReadOnlyList<SceneAnalysisTrackEvidence>> ListRunTracksAsync(
            Guid processingRunId,
            CancellationToken cancellationToken) =>
            inner.ListRunTracksAsync(processingRunId, cancellationToken);

        public async Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken)
        {
            Reads++;
            if (Reads == faultAt)
            {
                throw new IOException("Injected evidence-store fault.");
            }

            var payload = await inner.ReadTrajectoryAsync(storageKey, cancellationToken);
            if (Reads == cancelAt)
            {
                await cancellation!.CancelAsync();
            }

            return payload;
        }
    }
}
