using System.Diagnostics;
using System.Globalization;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Application.Modules.SceneAnalytics.Configuration;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Contracts.Api.Analytics;
using Mavi.Domain.SceneAnalytics;
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

    /// <summary>
    /// The version that qualifies is the version the platform requires — the same
    /// number, not a copy of it that can drift.
    /// </summary>
    /// <remarks>
    /// Runs in the ordinary suite and needs no database. The product refuses any
    /// major version other than its required one, so treating "18 or later" as
    /// qualification-grade would let a run on a planner the platform does not accept
    /// be presented as satisfying the exit gate. This states the two are equal; the
    /// gate itself now compares for equality rather than a lower bound.
    /// </remarks>
    [Fact]
    public void TheVersionThatQualifiesIsTheVersionTheProductRequires() =>
        Assert.Equal(
            QualificationGate.RequiredPostgreSqlMajorVersion,
            new Mavi.Api.Startup.DatabasePrerequisiteOptions().RequiredPostgreSqlMajorVersion);

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
        var verdict = new QualificationVerdict(QualificationGate.IsQualificationGrade(environment));
        QualificationGate.RequireRepositoryProvenance(verdict, environment);
        var runId = QualificationGate.NewRunId();
        QualificationGate.Begin(EvidenceFile, runId, environment);

        var tracks = Setting("MAVI_QUAL_UNIT_TRACKS", QualificationUnitTracks);
        var zoneCount = Setting("MAVI_QUAL_ZONES", 4);

        // An override may shrink the workload for a cheap shape check, but it may not
        // shrink it and still be called qualification evidence: the plan's item is a
        // 1,000-Track run, and a file reporting 20 Tracks under that heading would
        // misrepresent what was measured.
        verdict.RequireForQualification(
            "workload is the plan's 1,000-Track run",
            tracks >= QualificationUnitTracks,
            $"MAVI_QUAL_UNIT_TRACKS resolved to {tracks}; the plan requires at least {QualificationUnitTracks}");

        var manifest = await new QualificationCorpus(fixture).BuildAsync(
            seed: Setting("MAVI_QUAL_SEED", 20260922),
            videoCount: 1,
            tracksPerRun: tracks,
            zoneCount: zoneCount,
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
            // Write the diagnostic, then fail. Returning green here would let a
            // regression in corpus construction or lifecycle eligibility pass the
            // qualification command while measuring no throughput at all — the same
            // shape of silent emptiness the visibility-sequence defect produced.
            var diagnostic = QualificationGate.Write(EvidenceFile, new
            {
                runId,
                environment,
                manifest,
                status = "no unit claimable — corpus did not produce an eligible run",
            });
            throw new QualificationFailedException(
                "No analytical unit was claimable, so no throughput was measured. "
                + $"Diagnostic: {diagnostic}");
        }

        var stopwatch = Stopwatch.StartNew();
        var result = await executor.ExecuteAsync(
            claim,
            new SceneAnalysisExecutionIdentity(QualificationCorpus.AlgorithmVersion, QualificationCorpus.ParametersSha256),
            Options,
            default);
        stopwatch.Stop();

        await using var reader = fixture.CreateDbContext();
        var outcomes = await reader.TrackAnalysisOutcomes.CountAsync();
        var zoneVisits = await reader.TrackZoneVisits.CountAsync();
        var zoneSummaries = await reader.TrackZoneSummaries.CountAsync();
        var lineCrossings = await reader.TrackLineCrossings.CountAsync();
        var motionSummaries = await reader.TrackMotionSummaries.CountAsync();
        var unit = await reader.SceneAnalyses.AsNoTracking().SingleAsync(x => x.Id == claim.AnalysisId);

        // What the workload must have done to be worth timing. Every one of these is
        // derived from the corpus and the product's own semantics, not chosen to make
        // the numbers pass: each Track is sealed with a valid trajectory, so each must
        // be analysed, none may be unavailable, and the engine emits one outcome and
        // one motion summary per analysed Track and one zone summary per enabled zone.
        verdict.RequireIntegrity("the unit executed successfully", result.IsSuccess,
            $"executor reported IsSuccess={result.IsSuccess}");
        verdict.RequireIntegrityEqual("every Track was analysed", tracks, result.AnalysedTrackCount);
        verdict.RequireIntegrityEqual("no Track was unavailable", 0, result.UnavailableTrackCount);
        verdict.RequireIntegrityEqual("one outcome per Track", tracks, outcomes);
        verdict.RequireIntegrityEqual("one motion summary per Track", tracks, motionSummaries);
        verdict.RequireIntegrityEqual("one zone summary per Track per zone", (long)tracks * zoneCount, zoneSummaries);

        // Zone visits and line crossings depend on where each seeded path runs, so
        // their totals are not a fixed multiple of the population. They are still
        // deterministic for a given seed, and a corpus that produced none of either
        // would be timing an engine with no geometry to find.
        verdict.RequireIntegrity("the corpus exercised zone entry", zoneVisits > 0,
            $"{zoneVisits} zone visits derived");
        verdict.RequireIntegrity("the corpus exercised line crossing", lineCrossings > 0,
            $"{lineCrossings} line crossings derived");

        verdict.RequireIntegrity("the unit reached Completed", unit.Status == SceneAnalysisStatus.Completed,
            $"unit status is {unit.Status}");
        verdict.RequireIntegrity("the unit was published", unit.VisibilitySequence is > 0,
            $"visibility sequence is {unit.VisibilitySequence?.ToString(CultureInfo.InvariantCulture) ?? "null"}");

        var path = QualificationGate.Write(EvidenceFile, new
        {
            runId,
            verdict = verdict.ToEvidence(),
            environment,
            manifest,
            trackCount = tracks,
            succeeded = result.IsSuccess,
            analysedTracks = result.AnalysedTrackCount,
            unavailableTracks = result.UnavailableTrackCount,
            unitStatus = unit.Status.ToString(),
            elapsedMs = stopwatch.Elapsed.TotalMilliseconds,
            msPerTrack = stopwatch.Elapsed.TotalMilliseconds / Math.Max(tracks, 1),
            rowsWritten = new
            {
                outcomes,
                zoneVisits,
                zoneSummaries,
                lineCrossings,
                motionSummaries,
            },
        });

        verdict.Enforce(path);
    }

    private const string EvidenceFile = "analytics-unit-throughput.json";

    /// <summary>The population exit-gate item 4 names: a synthetic 1,000-Track run.</summary>
    private const int QualificationUnitTracks = 1_000;

    /// <summary>
    /// Exit-gate item 6: the heatmap at its frozen envelope — the maximum covered
    /// runs and the maximum candidate Tracks, every one with real sealed evidence.
    /// </summary>
    [Fact]
    public async Task TheHeatmapIsTimedAtItsFrozenFanOutEnvelope()
    {
        if (!QualificationGate.Enabled) return;

        var environment = await QualificationGate.CaptureEnvironmentAsync(fixture.ConnectionString);
        var verdict = new QualificationVerdict(QualificationGate.IsQualificationGrade(environment));
        QualificationGate.RequireRepositoryProvenance(verdict, environment);
        var runId = QualificationGate.NewRunId();
        QualificationGate.Begin(HeatmapEvidenceFile, runId, environment);

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

        // The envelope is only measured if the corpus actually resolved to it. A
        // regression in visibility, scope or coverage would otherwise leave a timing
        // file describing a fraction of the intended fan-out under the heading of the
        // product's maximum.
        verdict.RequireIntegrity("the heatmap scope resolved", scope.IsSuccess,
            $"scope failure is {scope.Failure}");
        verdict.RequireIntegrityEqual(
            "covered runs are the product's maximum", AnalyticsQueryRules.MaximumHeatmapRuns, scope.CoveredRunCount);
        verdict.RequireIntegrityEqual(
            "candidate Tracks are the product's maximum", AnalyticsQueryRules.MaximumHeatmapTracks, scope.CandidateTrackCount);

        var measurements = new List<object>();
        var invocation = 0;
        foreach (var gridWidth in HeatmapGridWidths)
        {
            for (var repetition = 1; repetition <= HeatmapRepetitions; repetition++)
            {
                invocation++;
                var stopwatch = Stopwatch.StartNew();
                var result = await service.HeatmapAsync(
                    new AnalyticsHeatmapQuery(
                        manifest.CameraId, manifest.WindowFromUtc, manifest.WindowToUtc, null, gridWidth, null),
                    default);
                stopwatch.Stop();

                // Every candidate Track has a sealed trajectory of a known length, so the
                // work done is exactly determined: all of them must contribute, and the
                // sample total must be the whole corpus rather than whatever survived.
                // This is the assertion that would have caught a heatmap reading one run
                // of fifty and still emitting a timing file. Repeating each width keeps a
                // cold-ish first observation and warm observations instead of presenting
                // one favourable sample as a stable performance conclusion.
                var label = $"grid width {gridWidth}, repetition {repetition}";
                verdict.RequireIntegrity($"heatmap succeeded at {label}",
                    result.Failure == AnalyticsFailure.None, $"failure is {result.Failure}");
                verdict.RequireIntegrityEqual(
                    $"every candidate Track contributed at {label}",
                    scope.CandidateTrackCount, result.TrackCount);
                verdict.RequireIntegrityEqual(
                    $"every sealed sample was read at {label}",
                    (long)scope.CandidateTrackCount * QualificationCorpus.SealedTrajectorySampleCount,
                    result.Grid?.SampleCount ?? 0);
                verdict.RequireIntegrity($"the grid honours the requested width at {label}",
                    result.Grid is not null && result.Grid.Width == gridWidth,
                    $"grid is {result.Grid?.Width.ToString(CultureInfo.InvariantCulture) ?? "null"} wide");
                verdict.RequireIntegrity($"the grid is populated at {label}",
                    result.Grid is { MaxCellValue: > 0 } and { Height: > 0 },
                    $"max cell value {result.Grid?.MaxCellValue ?? 0}, height {result.Grid?.Height ?? 0}");

                measurements.Add(new
                {
                    gridWidth,
                    repetition,
                    invocation,
                    cacheState = invocation == 1 ? "cold-ish" : "warm",
                    failure = result.Failure.ToString(),
                    elapsedMs = stopwatch.Elapsed.TotalMilliseconds,
                    cells = result.Grid is null ? 0 : result.Grid.Width * result.Grid.Height,
                    contributingTracks = result.TrackCount,
                    sampleCount = result.Grid?.SampleCount ?? 0,
                    maxCellValue = result.Grid?.MaxCellValue ?? 0,
                });
            }
        }

        var path = QualificationGate.Write(HeatmapEvidenceFile, new
        {
            runId,
            verdict = verdict.ToEvidence(),
            environment,
            manifest,
            envelope = new
            {
                maximumRuns = AnalyticsQueryRules.MaximumHeatmapRuns,
                maximumTracks = AnalyticsQueryRules.MaximumHeatmapTracks,
                resolvedCoveredRuns = scope.CoveredRunCount,
                resolvedCandidateTracks = scope.CandidateTrackCount,
                scopeFailure = scope.Failure.ToString(),
            },
            measurements,
        });

        verdict.Enforce(path);
    }

    private const string HeatmapEvidenceFile = "heatmap-envelope.json";

    private const int HeatmapRepetitions = 3;

    private static readonly int[] HeatmapGridWidths = [48, 96, 128];
}
