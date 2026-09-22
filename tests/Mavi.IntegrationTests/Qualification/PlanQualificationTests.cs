using System.Diagnostics;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Contracts.Api.Analytics;
using Mavi.Domain.Intelligence;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// Parent-plan §Z: the latency and query plan of **every** §S predicate and
/// **every** §T aggregate, measured at 10^5 relevant facts.
/// </summary>
/// <remarks>
/// Skipped unless <c>MAVI_QUALIFICATION=1</c>. Point
/// <c>MAVI_TEST_DB_CONNECTION</c> at PostgreSQL 18 and this produces the
/// qualification evidence; against 16 it produces engineering observations, and
/// the captured environment records which it was in
/// <c>isQualificationGradeDatabase</c> so a reader never has to guess.
///
/// The corpus shape is read from the environment so the same harness serves the
/// 10^5 requirement and a quick shape check without editing code.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class PlanQualificationTests(PostgresFixture fixture)
{
    private const string EvidenceFile = "plan-qualification.json";

    private const int PageSize = 50;

    /// <summary>One §S measurement: the predicate, and the tables its SQL must reach.</summary>
    private sealed record PredicateCase(
        string Name,
        TrackAnalyticsQuery Analytics,
        IReadOnlyList<string> ExpectedTables);

    private static readonly string[] ZoneTables = ["track_zone_visits", "track_zone_summaries"];
    private static readonly string[] ZoneSummaryTables = ["track_zone_summaries"];
    private static readonly string[] LineTables = ["track_line_crossings"];
    private static readonly string[] MotionTables = ["track_motion_summaries"];
    private static readonly string[] AnalysisTables = ["scene_analyses"];

    /// <summary>The §T bucket sizes measured, from a minute to an hour.</summary>
    private static readonly int[] AggregateBucketSizes = [60, 900, 3_600];

    /// <summary>The class filters each §T bucket size is measured under.</summary>
    private static readonly ObjectClass?[] AggregateClassFilters = [null, ObjectClass.Person, ObjectClass.Vehicle];

    private static int Setting(string name, int fallback) =>
        int.TryParse(Environment.GetEnvironmentVariable(name), out var value) && value > 0 ? value : fallback;

    /// <summary>
    /// The §S predicate families this harness measures, keyed by the contract key
    /// each one exercises.
    /// </summary>
    /// <remarks>
    /// Declared separately from the measurement so the coverage guard below can
    /// check it without a database, and so both share one definition of "every
    /// predicate" rather than drifting apart.
    /// </remarks>
    internal static IReadOnlyList<(string Key, string Name)> PredicateCoverage =>
    [
        ("SceneRevisionId", "sceneRevisionId (explicit)"),
        ("AnalyticsAlgorithmVersion", "sceneRevisionId + analyticsAlgorithmVersion"),
        ("ZoneId", "zoneId (default dwelled)"),
        ("ZoneRelation", "zoneRelation=entered|exited|dwelled"),
        ("MinDwellMs", "minDwellMs"),
        ("LineId", "lineId"),
        ("CrossingDirection", "crossingDirection=aToB|bToA"),
        ("MotionDirection", "motionDirection, all eight headings"),
        ("MinStationaryMs", "minStationaryMs"),
        ("Loitering", "loitering, alone and with zoneId"),
        ("RequireCompleteCoverage", "analyticsCoverage control flag — not a predicate (§S)"),
    ];

    /// <summary>
    /// Every key of the frozen §S contract is named by the measurement plan.
    /// </summary>
    /// <remarks>
    /// Runs in the ordinary suite and needs no database, because it is a statement
    /// about the contract rather than about a server: if a future slice adds a
    /// search predicate, the parent plan's "every §S predicate" requirement is
    /// silently no longer met unless the harness is extended too. Reflecting over
    /// the query record is what makes that impossible to forget — a new property
    /// fails this immediately.
    /// </remarks>
    [Fact]
    public void TheMeasurementPlanNamesEverySearchPredicateTheContractDefines()
    {
        // The record's primary constructor is exactly the contract's key set.
        // Reading properties instead would drag in computed helpers such as
        // EffectiveZoneRelation, which are derived from keys rather than being
        // keys — the first version of this guard failed on precisely those two.
        var contractKeys = typeof(TrackAnalyticsQuery)
            .GetConstructors()
            .OrderByDescending(constructor => constructor.GetParameters().Length)
            .First()
            .GetParameters()
            .Select(parameter => parameter.Name!)
            .ToHashSet(StringComparer.Ordinal);

        var covered = PredicateCoverage.Select(entry => entry.Key).ToHashSet(StringComparer.Ordinal);

        var missing = contractKeys.Where(key => !covered.Contains(key)).OrderBy(key => key, StringComparer.Ordinal).ToList();
        Assert.True(
            missing.Count == 0,
            $"§S predicates not covered by the qualification harness: {string.Join(", ", missing)}");
    }

    /*
     * A plain Fact that returns when the gate is closed, rather than a skippable
     * one: adding a package to make a harness print "skipped" would be a new
     * dependency for a report's convenience, which Slice 7 forbids. The always-on
     * guard above is what stops this pair being vacuous in the ordinary suite —
     * this half measures, that half keeps the measurement honest about its own
     * coverage. When the gate is closed the evidence file is simply absent, and
     * absence is what the evidence documents record as NOT EXECUTED.
     */
    [Fact]
    public async Task EverySearchPredicateAndEveryAggregateIsPlannedAndTimed()
    {
        if (!QualificationGate.Enabled) return;

        var environment = await QualificationGate.CaptureEnvironmentAsync(fixture.ConnectionString);
        var verdict = new QualificationVerdict(QualificationGate.IsQualificationGrade(environment));
        var runId = QualificationGate.NewRunId();
        QualificationGate.Begin(EvidenceFile, runId, environment);

        // 40 runs x 250 Tracks x (1 outcome + 1 motion + 4 zone summaries + 3 visits
        // + 2 crossings) = 10,000 Tracks x 11 = 110,000 relevant facts, over the
        // parent plan's 10^5 prerequisite. The earlier default was 120 Tracks, which
        // this comment claimed was 528,000 and was in fact 52,800 — half the
        // prerequisite, so the unchanged command would have measured every §S and §T
        // plan below the volume the plan requires. The shape stays overridable so a
        // cheap check is still possible; the assertion below is what stops an
        // undersized run being mistaken for qualification evidence.
        var corpus = new QualificationCorpus(fixture);
        var manifest = await corpus.BuildAsync(
            seed: Setting("MAVI_QUAL_SEED", 20260922),
            videoCount: Setting("MAVI_QUAL_RUNS", 40),
            tracksPerRun: Setting("MAVI_QUAL_TRACKS", 250),
            zoneCount: Setting("MAVI_QUAL_ZONES", 4),
            lineCount: Setting("MAVI_QUAL_LINES", 2),
            visitsPerTrack: Setting("MAVI_QUAL_VISITS", 3),
            crossingsPerTrack: Setting("MAVI_QUAL_CROSSINGS", 2));

        var capture = new SqlCapture();
        var options = new DbContextOptionsBuilder<MaviDbContext>()
            .UseNpgsql(fixture.ConnectionString, npgsql => npgsql.UseVector())
            .AddInterceptors(capture)
            .Options;

        var zoneId = manifest.ZoneIds[0];
        var lineId = manifest.LineIds[0];

        // Every §S predicate family, named exactly as the contract names it, and
        // carrying the fact table whose presence in the generated SQL proves the
        // predicate was actually applied rather than silently dropped.
        var predicates = new List<PredicateCase>
        {
            new("zoneId (default dwelled)", TrackAnalyticsQuery.Empty with { ZoneId = zoneId }, ZoneTables),
            new("zoneRelation=entered", TrackAnalyticsQuery.Empty with { ZoneId = zoneId, ZoneRelation = TrackZoneRelation.Entered }, ZoneTables),
            new("zoneRelation=exited", TrackAnalyticsQuery.Empty with { ZoneId = zoneId, ZoneRelation = TrackZoneRelation.Exited }, ZoneTables),
            new("zoneRelation=dwelled", TrackAnalyticsQuery.Empty with { ZoneId = zoneId, ZoneRelation = TrackZoneRelation.Dwelled }, ZoneTables),
            new("minDwellMs", TrackAnalyticsQuery.Empty with { ZoneId = zoneId, MinDwellMs = 5_000 }, ZoneTables),
            new("lineId", TrackAnalyticsQuery.Empty with { LineId = lineId }, LineTables),
            new("crossingDirection=aToB", TrackAnalyticsQuery.Empty with { LineId = lineId, CrossingDirection = TrackCrossingDirection.AToB }, LineTables),
            new("crossingDirection=bToA", TrackAnalyticsQuery.Empty with { LineId = lineId, CrossingDirection = TrackCrossingDirection.BToA }, LineTables),
            new("minStationaryMs", TrackAnalyticsQuery.Empty with { MinStationaryMs = 5_000 }, MotionTables),
            new("loitering", TrackAnalyticsQuery.Empty with { Loitering = true }, ZoneSummaryTables),
            new("loitering + zoneId", TrackAnalyticsQuery.Empty with { Loitering = true, ZoneId = zoneId }, ZoneSummaryTables),
            // Identity-only predicates pin the analytical scope rather than a fact
            // family, so the analysis table is what must appear.
            new("sceneRevisionId (explicit)", TrackAnalyticsQuery.Empty with { SceneRevisionId = manifest.RevisionId }, AnalysisTables),
            new("sceneRevisionId + analyticsAlgorithmVersion", TrackAnalyticsQuery.Empty with
            {
                SceneRevisionId = manifest.RevisionId,
                AnalyticsAlgorithmVersion = QualificationCorpus.AlgorithmVersion,
            }, AnalysisTables),
            new("combination: zone + line + direction", TrackAnalyticsQuery.Empty with
            {
                ZoneId = zoneId, MinDwellMs = 2_000, LineId = lineId, CrossingDirection = TrackCrossingDirection.AToB,
            }, LineTables),
            new("combination: zone + motion + stationary + loitering", TrackAnalyticsQuery.Empty with
            {
                ZoneId = zoneId, MotionDirection = "NE", MinStationaryMs = 1_000, Loitering = true,
            }, MotionTables),
        };

        // motionDirection accepts eight values and each is its own predicate.
        foreach (var heading in QualificationScene.Headings)
        {
            predicates.Add(new(
                $"motionDirection={heading}",
                TrackAnalyticsQuery.Empty with { MotionDirection = heading },
                MotionTables));
        }

        var results = new List<object>();

        foreach (var (name, analytics, expectedTables) in predicates)
        {
            await using var db = new MaviDbContext(options);
            var repository = new TrackSearchRepository(db, TimeProvider.System);
            capture.Clear();

            var query = new TrackSearchQuery(
                manifest.CameraId, null, null, null,
                manifest.WindowFromUtc, manifest.WindowToUtc,
                null, null, null, PageSize, analytics);

            // SearchAnalyticsAsync, not SearchAsync. SearchAsync applies only the
            // non-analytic base candidate set, so every §S predicate handed to it was
            // silently discarded: each of these measurements planned and timed the
            // plain Track search, identically, while the evidence named a different
            // predicate each time. The table assertion below is what makes that
            // impossible to reintroduce.
            var stopwatch = Stopwatch.StartNew();
            var search = await repository.SearchAnalyticsAsync(
                query, cursor: null, take: PageSize + 1, cancellationToken: default);
            stopwatch.Stop();

            var page = search.Page as TrackAnalyticsSearchRepositoryPage;

            var plans = new List<object>();
            foreach (var statement in capture.Statements)
            {
                var plan = await SqlCapture.ExplainAsync(fixture.ConnectionString, statement);
                verdict.RequireIntegrity(
                    $"§S {name}: EXPLAIN produced a plan",
                    plan.Contains("cost=", StringComparison.Ordinal),
                    $"plan text was {plan.Length} characters");
                plans.Add(new { sql = statement.Sql, plan });
            }

            var sql = string.Concat(capture.Statements.Select(statement => statement.Sql));

            verdict.RequireIntegrity($"§S {name}: the query was accepted", search.IsValid,
                $"repository reported IsValid={search.IsValid}");
            verdict.RequireIntegrity($"§S {name}: an analytic page came back", page is not null,
                $"page type is {search.Page?.GetType().Name ?? "null"}");
            verdict.RequireIntegrity($"§S {name}: SQL was captured", capture.Statements.Count > 0,
                $"{capture.Statements.Count} statements intercepted");
            verdict.RequireIntegrity(
                $"§S {name}: the predicate reached the database",
                expectedTables.Any(table => sql.Contains(table, StringComparison.Ordinal)),
                $"generated SQL references none of {string.Join(", ", expectedTables)}");

            // The corpus gives every Track visits, crossings and a heading, so each of
            // these predicates has matching data by construction. An empty page here
            // means the measurement exercised nothing, not that the answer is zero.
            verdict.RequireIntegrity(
                $"§S {name}: the predicate selected from the corpus",
                page is { Items.Count: > 0 },
                $"{page?.Items.Count ?? 0} rows returned");

            results.Add(new
            {
                family = "S",
                predicate = name,
                elapsedMs = stopwatch.Elapsed.TotalMilliseconds,
                rows = page?.Items.Count ?? 0,
                valid = search.IsValid,
                coverageComplete = page?.Coverage.Complete,
                evaluatedRuns = page?.Coverage.EvaluatedRuns,
                expectedTables,
                dbQueryCount = capture.Statements.Count,
                plans,
            });
        }

        // Every §T aggregate, at three bucket sizes, unfiltered and class-filtered.
        //
        // The class filter is its own measurement, not a variant of the unfiltered
        // one: it changes AnalyticsScopeQuery.BaseCandidates and with it the joins
        // and cardinalities of every fact query, and this corpus holds both people
        // and vehicles, so the unfiltered call cannot stand in for it.
        var aggregateCases =
            from bucketSeconds in AggregateBucketSizes
            from objectClass in AggregateClassFilters
            select (bucketSeconds, objectClass);

        foreach (var (bucketSeconds, objectClass) in aggregateCases)
        {
            await using var db = new MaviDbContext(options);
            var repository = new AnalyticsAggregateRepository(db);
            capture.Clear();

            var aggregateQuery = new AnalyticsAggregateQuery(
                manifest.CameraId, manifest.WindowFromUtc, manifest.WindowToUtc, bucketSeconds, objectClass);

            // Timed across the whole §T path. The repository only materialises the
            // fact set; the counting rules — occupancy, unique tracks, repeated
            // visits, the per-bucket series — are the aggregator, and their cost
            // grows with facts and buckets. Stopping the clock at the repository
            // would report a latency the operator never experiences.
            var allocatedBytesBefore = GC.GetTotalAllocatedBytes(precise: true);
            var collectionsBefore = CaptureCollections();
            var totalStopwatch = Stopwatch.StartNew();
            var databaseStopwatch = Stopwatch.StartNew();
            var aggregate = await repository.AggregateAsync(aggregateQuery, default);
            databaseStopwatch.Stop();
            var applicationStopwatch = Stopwatch.StartNew();
            var series = aggregate.Facts is null
                ? null
                : AnalyticsAggregator.Compute(
                    aggregate.Facts, aggregateQuery.FromUtc, aggregateQuery.ToUtc, bucketSeconds);
            applicationStopwatch.Stop();
            totalStopwatch.Stop();
            var allocatedBytes = GC.GetTotalAllocatedBytes(precise: true) - allocatedBytesBefore;
            var collectionsAfter = CaptureCollections();

            var label = $"bucketSeconds={bucketSeconds}, objectClass={objectClass?.ToString() ?? "any"}";

            var plans = new List<object>();
            foreach (var statement in capture.Statements)
            {
                var plan = await SqlCapture.ExplainAsync(fixture.ConnectionString, statement);
                verdict.RequireIntegrity(
                    $"§T {label}: EXPLAIN produced a plan",
                    plan.Contains("cost=", StringComparison.Ordinal),
                    $"plan text was {plan.Length} characters");
                plans.Add(new { sql = statement.Sql, plan });
            }

            verdict.RequireIntegrity($"§T {label}: the aggregate resolved", aggregate.IsSuccess,
                $"failure is {aggregate.Failure}");
            verdict.RequireIntegrity($"§T {label}: SQL was captured", capture.Statements.Count > 0,
                $"{capture.Statements.Count} statements intercepted");
            verdict.RequireIntegrity($"§T {label}: the series was computed", series is not null,
                series is null ? "no fact set to compute from" : $"{series.Buckets.Count} buckets");
            verdict.RequireIntegrity($"§T {label}: the window produced buckets", series is { Buckets.Count: > 0 },
                $"{series?.Buckets.Count ?? 0} buckets");
            verdict.RequireIntegrity($"§T {label}: the geometry was resolved",
                aggregate.Facts is { Zones.Count: > 0, Lines.Count: > 0 },
                $"{aggregate.Facts?.Zones.Count ?? 0} zones, {aggregate.Facts?.Lines.Count ?? 0} lines");

            // The corpus writes visits and crossings for every Track of both classes,
            // so every one of these nine cases has facts to count. A case that fetched
            // none would be timing an empty aggregate under a populated heading.
            verdict.RequireIntegrity($"§T {label}: zone visits were fetched",
                aggregate.Facts is { ZoneVisits.Count: > 0 }, $"{aggregate.Facts?.ZoneVisits.Count ?? 0} visits");
            verdict.RequireIntegrity($"§T {label}: line crossings were fetched",
                aggregate.Facts is { LineCrossings.Count: > 0 }, $"{aggregate.Facts?.LineCrossings.Count ?? 0} crossings");

            results.Add(new
            {
                family = "T",
                predicate = $"aggregate all metrics, bucketSeconds={bucketSeconds}, "
                    + $"objectClass={objectClass?.ToString() ?? "any"}",
                elapsedMs = totalStopwatch.Elapsed.TotalMilliseconds,
                databaseMaterialisationMs = databaseStopwatch.Elapsed.TotalMilliseconds,
                applicationAggregationMs = applicationStopwatch.Elapsed.TotalMilliseconds,
                allocatedBytes,
                gcCollections = new
                {
                    generation0 = collectionsAfter[0] - collectionsBefore[0],
                    generation1 = collectionsAfter[1] - collectionsBefore[1],
                    generation2 = collectionsAfter[2] - collectionsBefore[2],
                },
                // Every §T metric is produced by this one call: zoneEntryCount,
                // zoneExitCount, zoneUniqueTrackCount, lineCrossingCount[direction],
                // occupancy/peakOccupancy, repeatedVisitTrackCount and classCount.
                zones = aggregate.Facts?.Zones.Count ?? 0,
                lines = aggregate.Facts?.Lines.Count ?? 0,
                buckets = series?.Buckets.Count ?? 0,
                zoneVisits = aggregate.Facts?.ZoneVisits.Count ?? 0,
                lineCrossings = aggregate.Facts?.LineCrossings.Count ?? 0,
                zoneSummaries = aggregate.Facts?.ZoneSummaries.Count ?? 0,
                trackIntervals = aggregate.Facts?.TrackIntervals.Count ?? 0,
                dbQueryCount = capture.Statements.Count,
                plans,
            });
        }

        verdict.RequireForQualification(
            "the corpus meets the plan's relevant-fact prerequisite",
            manifest.RelevantFactCount >= QualificationGate.MinimumRelevantFactCount,
            $"{manifest.RelevantFactCount} relevant facts against a required {QualificationGate.MinimumRelevantFactCount}");

        var path = QualificationGate.Write(EvidenceFile, new
        {
            runId,
            verdict = verdict.ToEvidence(),
            environment,
            manifest,
            relevantFactCount = manifest.RelevantFactCount,
            minimumRelevantFactCount = QualificationGate.MinimumRelevantFactCount,
            meetsFactPrerequisite = manifest.RelevantFactCount >= QualificationGate.MinimumRelevantFactCount,
            results,
        });

        Assert.True(File.Exists(path));

        // Everything above is recorded in the evidence; this is what decides whether
        // the evidence may be called evidence at all.
        verdict.Enforce(path);
    }

    private static int[] CaptureCollections() =>
        [GC.CollectionCount(0), GC.CollectionCount(1), GC.CollectionCount(2)];
}
