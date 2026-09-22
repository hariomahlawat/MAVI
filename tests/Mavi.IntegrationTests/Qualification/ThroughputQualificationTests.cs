using System.Diagnostics;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Application.Modules.SceneAnalytics.Configuration;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Contracts.Api.Analytics;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.Infrastructure.SceneAnalytics;
using Mavi.Infrastructure.Storage;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// Parent-plan §Z, the two work-volume measurements the query harness does not
/// cover: how long one analytical unit takes over a synthetic 1,000-Track run,
/// and what the heatmap costs at the very edge of its frozen fan-out envelope.
/// </summary>
/// <remarks>
/// <para>
/// Both open real sealed evidence through the production reader, so they measure
/// the I/O path as well as the query path. Both are gated on
/// <c>MAVI_QUALIFICATION=1</c> for the same reason as the plan harness: they
/// generate thousands of artefacts and take minutes.
/// </para>
/// <para>
/// Neither produces qualification evidence on its own. The captured environment
/// records the live server version, and a run against anything below PostgreSQL 18
/// is an engineering observation.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class ThroughputQualificationTests(PostgresFixture fixture)
{
    private static readonly SceneAnalyticsOptions Options = new()
    {
        LeaseSeconds = 3_600,
        MaxUnitDurationSeconds = 3_600,
        ReclaimGraceSeconds = 60,
        MaximumAttempts = 3,
    };

    private static int Setting(string name, int fallback) =>
        int.TryParse(Environment.GetEnvironmentVariable(name), out var value) && value > 0 ? value : fallback;

    /// <summary>
    /// The envelope this harness measures at is the one the product enforces.
    /// </summary>
    /// <remarks>
    /// Runs in the ordinary suite and needs no database. The plan requires the
    /// heatmap to be measured at its limits; if a later slice raises or lowers a
    /// limit, a harness pinned to its own copy of the number would quietly stop
    /// measuring the limit. Reading the contract's constants is what keeps the two
    /// the same number, and this states that they are.
    /// </remarks>
    [Fact]
    public void TheEnvelopeMeasuredIsTheEnvelopeEnforced()
    {
        Assert.Equal(AnalyticsQueryRules.MaximumHeatmapRuns, EnvelopeRuns);
        Assert.Equal(AnalyticsQueryRules.MaximumHeatmapTracks, EnvelopeRuns * EnvelopeTracksPerRun);
    }

    private const int EnvelopeRuns = AnalyticsQueryRules.MaximumHeatmapRuns;
    private const int EnvelopeTracksPerRun = AnalyticsQueryRules.MaximumHeatmapTracks / AnalyticsQueryRules.MaximumHeatmapRuns;

    /// <summary>
    /// Exit-gate item 4: analytical-unit duration and rows written, over a synthetic
    /// run of 1,000 Tracks with real sealed trajectories.
    /// </summary>
    [Fact]
    public async Task OneAnalyticalUnitOverASyntheticThousandTrackRunIsTimed()
    {
        if (!QualificationGate.Enabled) return;

        var environment = await QualificationGate.CaptureEnvironmentAsync(fixture.ConnectionString);
        var tracks = Setting("MAVI_QUAL_UNIT_TRACKS", 1_000);

        var manifest = await new QualificationCorpus(fixture).BuildAsync(
            seed: Setting("MAVI_QUAL_SEED", 20260922),
            videoCount: 1,
            tracksPerRun: tracks,
            zoneCount: Setting("MAVI_QUAL_ZONES", 4),
            lineCount: Setting("MAVI_QUAL_LINES", 2),
            visitsPerTrack: 0,
            crossingsPerTrack: 0,
            sealTrajectories: true,
            // Queued with no facts: the executor is what this measures, so it must
            // have the work still to do.
            completeUnits: false);

        await using var db = fixture.CreateDbContext();
        var lifecycle = new SceneAnalysisLifecycle(db, TimeProvider.System);
        var executor = new SceneAnalysisExecutor(
            lifecycle,
            new SceneAnalysisEvidenceReader(db, new AcceptedEvidenceReader(Microsoft.Extensions.Options.Options.Create(new MediaStorageOptions
            {
                RootPath = manifest.MediaRoot!,
                EvidenceRootPath = manifest.EvidenceRoot!,
            }))),
            new SceneConfigurationRepository(db),
            NullLogger<SceneAnalysisExecutor>.Instance);

        await lifecycle.QueueEligibleUnitsAsync(
            QualificationCorpus.AlgorithmVersion,
            QualificationCorpus.ParametersSha256,
            sourceCommit: null,
            manifest.WindowFromUtc.AddDays(-1),
            50,
            default);
        var claim = await lifecycle.ClaimNextAsync(
            new SceneAnalysisExecutionIdentity(QualificationCorpus.AlgorithmVersion, QualificationCorpus.ParametersSha256),
            Options.ToLeasePolicy(),
            default);

        if (claim is null)
        {
            QualificationGate.Write("analytics-unit-throughput.json", new
            {
                environment,
                manifest,
                status = "no unit claimable — corpus did not produce an eligible run",
            });
            return;
        }

        var stopwatch = Stopwatch.StartNew();
        var result = await executor.ExecuteAsync(
            claim,
            new SceneAnalysisExecutionIdentity(QualificationCorpus.AlgorithmVersion, QualificationCorpus.ParametersSha256),
            Options,
            default);
        stopwatch.Stop();

        await using var reader = fixture.CreateDbContext();
        var path = QualificationGate.Write("analytics-unit-throughput.json", new
        {
            environment,
            manifest,
            trackCount = tracks,
            succeeded = result.IsSuccess,
            analysedTracks = result.AnalysedTrackCount,
            unavailableTracks = result.UnavailableTrackCount,
            elapsedMs = stopwatch.Elapsed.TotalMilliseconds,
            msPerTrack = stopwatch.Elapsed.TotalMilliseconds / Math.Max(tracks, 1),
            rowsWritten = new
            {
                outcomes = await reader.TrackAnalysisOutcomes.CountAsync(),
                zoneVisits = await reader.TrackZoneVisits.CountAsync(),
                zoneSummaries = await reader.TrackZoneSummaries.CountAsync(),
                lineCrossings = await reader.TrackLineCrossings.CountAsync(),
                motionSummaries = await reader.TrackMotionSummaries.CountAsync(),
            },
        });

        Assert.True(File.Exists(path));
    }

    /// <summary>
    /// Exit-gate item 6: the heatmap at its frozen envelope — the maximum covered
    /// runs and the maximum candidate Tracks, every one with real sealed evidence.
    /// </summary>
    [Fact]
    public async Task TheHeatmapIsTimedAtItsFrozenFanOutEnvelope()
    {
        if (!QualificationGate.Enabled) return;

        var environment = await QualificationGate.CaptureEnvironmentAsync(fixture.ConnectionString);

        var manifest = await new QualificationCorpus(fixture).BuildAsync(
            seed: Setting("MAVI_QUAL_SEED", 20260922),
            videoCount: EnvelopeRuns,
            tracksPerRun: EnvelopeTracksPerRun,
            zoneCount: Setting("MAVI_QUAL_ZONES", 4),
            lineCount: Setting("MAVI_QUAL_LINES", 2),
            visitsPerTrack: 1,
            crossingsPerTrack: 1,
            sealTrajectories: true);

        await using var db = fixture.CreateDbContext();
        var repository = new AnalyticsAggregateRepository(db);
        var service = new AnalyticsAggregateService(
            repository,
            new HeatmapEvidenceReader(new AcceptedEvidenceReader(Microsoft.Extensions.Options.Options.Create(new MediaStorageOptions
            {
                RootPath = manifest.MediaRoot!,
                EvidenceRootPath = manifest.EvidenceRoot!,
            }))),
            NullLogger<AnalyticsAggregateService>.Instance);

        // The scope is resolved first and recorded, so the evidence says what the
        // measurement was actually taken over rather than what it was asked for.
        var scope = await repository.ResolveHeatmapScopeAsync(
            new AnalyticsHeatmapQuery(
                manifest.CameraId, manifest.WindowFromUtc, manifest.WindowToUtc, null, 96, null),
            default);

        var measurements = new List<object>();
        foreach (var gridWidth in new[] { 48, 96, 128 })
        {
            var stopwatch = Stopwatch.StartNew();
            var result = await service.HeatmapAsync(
                new AnalyticsHeatmapQuery(
                    manifest.CameraId, manifest.WindowFromUtc, manifest.WindowToUtc, null, gridWidth, null),
                default);
            stopwatch.Stop();

            measurements.Add(new
            {
                gridWidth,
                failure = result.Failure.ToString(),
                elapsedMs = stopwatch.Elapsed.TotalMilliseconds,
                cells = result.Grid is null ? 0 : result.Grid.Width * result.Grid.Height,
                contributingTracks = result.TrackCount,
                sampleCount = result.Grid?.SampleCount ?? 0,
                maxCellValue = result.Grid?.MaxCellValue ?? 0,
            });
        }

        var path = QualificationGate.Write("heatmap-envelope.json", new
        {
            environment,
            manifest,
            envelope = new
            {
                maximumRuns = AnalyticsQueryRules.MaximumHeatmapRuns,
                maximumTracks = AnalyticsQueryRules.MaximumHeatmapTracks,
                resolvedCoveredRuns = scope.CoveredRunCount,
                resolvedCandidateTracks = scope.CandidateTrackCount,
            },
            measurements,
        });

        Assert.True(File.Exists(path));
    }
}
