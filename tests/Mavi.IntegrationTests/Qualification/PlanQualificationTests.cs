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

        // Defaults reach ~10^5 facts: 40 runs x 120 Tracks x (1 outcome + 1 motion
        // + 4 summaries + 3 visits + 2 crossings) = 528,000... deliberately
        // overridable so a shape check is cheap.
        var corpus = new QualificationCorpus(fixture);
        var manifest = await corpus.BuildAsync(
            seed: Setting("MAVI_QUAL_SEED", 20260922),
            videoCount: Setting("MAVI_QUAL_RUNS", 40),
            tracksPerRun: Setting("MAVI_QUAL_TRACKS", 120),
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

        // Every §S predicate family, named exactly as the contract names it.
        var predicates = new List<(string Name, TrackAnalyticsQuery Analytics)>
        {
            ("zoneId (default dwelled)", TrackAnalyticsQuery.Empty with { ZoneId = zoneId }),
            ("zoneRelation=entered", TrackAnalyticsQuery.Empty with { ZoneId = zoneId, ZoneRelation = TrackZoneRelation.Entered }),
            ("zoneRelation=exited", TrackAnalyticsQuery.Empty with { ZoneId = zoneId, ZoneRelation = TrackZoneRelation.Exited }),
            ("zoneRelation=dwelled", TrackAnalyticsQuery.Empty with { ZoneId = zoneId, ZoneRelation = TrackZoneRelation.Dwelled }),
            ("minDwellMs", TrackAnalyticsQuery.Empty with { ZoneId = zoneId, MinDwellMs = 5_000 }),
            ("lineId", TrackAnalyticsQuery.Empty with { LineId = lineId }),
            ("crossingDirection=aToB", TrackAnalyticsQuery.Empty with { LineId = lineId, CrossingDirection = TrackCrossingDirection.AToB }),
            ("crossingDirection=bToA", TrackAnalyticsQuery.Empty with { LineId = lineId, CrossingDirection = TrackCrossingDirection.BToA }),
            ("minStationaryMs", TrackAnalyticsQuery.Empty with { MinStationaryMs = 5_000 }),
            ("loitering", TrackAnalyticsQuery.Empty with { Loitering = true }),
            ("loitering + zoneId", TrackAnalyticsQuery.Empty with { Loitering = true, ZoneId = zoneId }),
            ("sceneRevisionId (explicit)", TrackAnalyticsQuery.Empty with { SceneRevisionId = manifest.RevisionId }),
            ("sceneRevisionId + analyticsAlgorithmVersion", TrackAnalyticsQuery.Empty with
            {
                SceneRevisionId = manifest.RevisionId,
                AnalyticsAlgorithmVersion = QualificationCorpus.AlgorithmVersion,
            }),
            ("combination: zone + line + direction", TrackAnalyticsQuery.Empty with
            {
                ZoneId = zoneId, MinDwellMs = 2_000, LineId = lineId, CrossingDirection = TrackCrossingDirection.AToB,
            }),
            ("combination: zone + motion + stationary + loitering", TrackAnalyticsQuery.Empty with
            {
                ZoneId = zoneId, MotionDirection = "NE", MinStationaryMs = 1_000, Loitering = true,
            }),
        };

        // motionDirection accepts eight values and each is its own predicate.
        foreach (var heading in QualificationScene.Headings)
        {
            predicates.Add(($"motionDirection={heading}", TrackAnalyticsQuery.Empty with { MotionDirection = heading }));
        }

        var results = new List<object>();

        foreach (var (name, analytics) in predicates)
        {
            await using var db = new MaviDbContext(options);
            var repository = new TrackSearchRepository(db, TimeProvider.System);
            capture.Clear();

            var query = new TrackSearchQuery(
                manifest.CameraId, null, null, null,
                manifest.WindowFromUtc, manifest.WindowToUtc,
                null, null, null, 50, analytics);

            var stopwatch = Stopwatch.StartNew();
            var page = await repository.SearchAsync(query, cursor: null, take: 50, cancellationToken: default);
            stopwatch.Stop();

            var plans = new List<object>();
            foreach (var statement in capture.Statements)
            {
                plans.Add(new
                {
                    sql = statement.Sql,
                    plan = await SqlCapture.ExplainAsync(fixture.ConnectionString, statement),
                });
            }

            results.Add(new
            {
                family = "S",
                predicate = name,
                elapsedMs = stopwatch.Elapsed.TotalMilliseconds,
                rows = page.Items.Count,
                dbQueryCount = capture.Statements.Count,
                plans,
            });
        }

        // Every §T aggregate, through the real service, once per metric family.
        foreach (var bucketSeconds in new[] { 60, 900, 3_600 })
        {
            await using var db = new MaviDbContext(options);
            var repository = new AnalyticsAggregateRepository(db);
            capture.Clear();

            var stopwatch = Stopwatch.StartNew();
            var aggregate = await repository.AggregateAsync(
                new AnalyticsAggregateQuery(
                    manifest.CameraId, manifest.WindowFromUtc, manifest.WindowToUtc, bucketSeconds, null),
                default);
            stopwatch.Stop();

            var plans = new List<object>();
            foreach (var statement in capture.Statements)
            {
                plans.Add(new
                {
                    sql = statement.Sql,
                    plan = await SqlCapture.ExplainAsync(fixture.ConnectionString, statement),
                });
            }

            results.Add(new
            {
                family = "T",
                predicate = $"aggregate all metrics, bucketSeconds={bucketSeconds}",
                elapsedMs = stopwatch.Elapsed.TotalMilliseconds,
                // Every §T metric is produced by this one call: zoneEntryCount,
                // zoneExitCount, zoneUniqueTrackCount, lineCrossingCount[direction],
                // occupancy/peakOccupancy, repeatedVisitTrackCount and classCount.
                zones = aggregate.Facts?.Zones.Count ?? 0,
                lines = aggregate.Facts?.Lines.Count ?? 0,
                zoneVisits = aggregate.Facts?.ZoneVisits.Count ?? 0,
                lineCrossings = aggregate.Facts?.LineCrossings.Count ?? 0,
                zoneSummaries = aggregate.Facts?.ZoneSummaries.Count ?? 0,
                trackIntervals = aggregate.Facts?.TrackIntervals.Count ?? 0,
                dbQueryCount = capture.Statements.Count,
                plans,
            });
        }

        var path = QualificationGate.Write("plan-qualification.json", new
        {
            environment,
            manifest,
            relevantFactCount = manifest.RelevantFactCount,
            results,
        });

        Assert.True(File.Exists(path));
    }
}
