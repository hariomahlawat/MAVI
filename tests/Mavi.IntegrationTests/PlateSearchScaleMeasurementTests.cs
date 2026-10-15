using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.IntegrationTests.Qualification;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using Xunit.Abstractions;

namespace Mavi.IntegrationTests;

/// <summary>Runs only when <c>MAVI_PLATE_SEARCH_SCALE_DB</c> names a scratch database (never a <c>mavi_test</c> database).</summary>
public sealed class PlateSearchScaleFactAttribute : FactAttribute
{
    public const string Variable = "MAVI_PLATE_SEARCH_SCALE_DB";

    public PlateSearchScaleFactAttribute()
    {
        var connection = Environment.GetEnvironmentVariable(Variable);
        if (string.IsNullOrWhiteSpace(connection))
            Skip = $"opt-in measurement; set {Variable} to a scratch database's connection string";
        else if (new NpgsqlConnectionStringBuilder(connection).Database is { } database &&
                 database.StartsWith("mavi_test", StringComparison.Ordinal))
            Skip = $"{Variable} must not name an integration-test database";
    }
}

/// <summary>
/// Plan §2.8, measured (Stage 4 PR-4, cold review P1-1/P1-2): plate searches over 10^6 Vehicle Tracks and
/// 10^6 <c>plate_track_texts</c> rows on a frozen, skewed corpus, through the real repository, with the
/// plans of the real statements. The record is <c>docs/qualification/stage4/2026-10-13-plate-search-at-scale.md</c>.
/// </summary>
/// <remarks>
/// <para>
/// <b>Frozen before any result was read</b> (corpus <see cref="CorpusId"/>, the query set
/// <see cref="FrozenQueries"/>, the sample counts and both bounds). Changing any of them is a new corpus
/// or query-set version, never an edit after seeing timings.
/// </para>
/// <para>
/// <b>Corpus.</b> 10 cameras × 100 videos, one completed visible run of 1 000 Vehicle Tracks per video,
/// Track start times 2.592 s apart over 30 days (newer runs hold newer Tracks), one Read plate and one
/// Track text per Track. Skewed: in runs 21–1 000 the state code is <c>KA</c> for 70 % of Tracks,
/// <c>MH</c> for 10 % and one of 34 other codes for the remaining 20 %; the oldest 20 runs (2 % of the
/// Tracks) are all <c>XQ0</c><i>d</i>, a text dense in old data and absent from new data. District,
/// series and number are hash-uniform. Readiness is mixed: every tenth run's only analysis is of an
/// older identity, so for the measured identity 900 runs are Ready and 100 are not.
/// </para>
/// <para>
/// <b>Modes</b> (<c>MAVI_PLATE_SEARCH_SCALE_MODE</c>). <c>development</c> (default) is the authority for
/// the 300 ms budget and runs on the pinned Development host. <c>ci</c> is an informational CI diagnostic on CI PostgreSQL
/// (workflow <c>plate-search-scale-informational.yml</c>, not a merge gate, not qualification evidence):
/// it asserts the intended plan shape of the real statements and a catastrophic bound of
/// <see cref="CatastrophicMilliseconds"/> (10× the budget: a shared hosted runner with PostgreSQL's
/// default 128 MB of shared buffers against a ≈ 1 GB corpus is expected to be several times slower than
/// the Development host, and an order-of-magnitude margin keeps runner noise from failing it while a
/// change of complexity class — a scan or an id list of the installation per page — still fails it; a
/// lost index fails the shape assertions whatever the time). Both modes assert the shape. When
/// <c>MAVI_PLATE_SEARCH_SCALE_OUT</c> is set, <c>development</c> writes <c>plate-search-scale.json</c> and
/// <c>plate-search-scale-plans.txt</c> (with the budget), and <c>ci</c> writes
/// <c>plate-search-scale-ci-diagnostic.json</c> and <c>plate-search-scale-ci-diagnostic-plans.txt</c>,
/// which carry the catastrophic bound only, never the budget, and state <c>qualificationEvidence: false</c>.
/// </para>
/// <para>
/// <b>Stress probe.</b> <c>S1 prefix XQ0</c> is declared before measuring as the walk's known worst
/// case (more in-scope matches than the sparse path's cap, all of them at the far end of the page
/// order), so its cost grows with the scope by design. It is measured and reported, with fewer samples,
/// and is outside both bounds; it is never a pass. (Since ADR-018 the candidate read is bounded by the matching
/// texts rather than by the scope; the probe keeps its frozen definition and its place outside both bounds.)
/// </para>
/// <para>
/// <b>Query set v2</b> (<see cref="QuerySetV2Id"/>, owner decision 2026-10-16 on cold review P1-2): frozen and
/// hashed (<see cref="QuerySetV2Sha256"/>) before it was measured, beside v1, which is unchanged
/// (<see cref="QuerySetSha256"/>). It adds the filter classes v1 did not exercise: a common text under a
/// historical upper time bound, and under a minimum confidence, duration or subclass that rejects every Track of
/// the corpus (whose Tracks are all 0.8 mean confidence, 4 000 ms and without a subclass, so a reject-all
/// threshold is the meaningful selective case; 0.8 itself is the inclusive boundary); a lower bound alone; a
/// historical continuation; and a combined analytic search on a never-configured camera. Same samples and
/// bounds; every v2 query is budgeted.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class PlateSearchScaleMeasurementTests(ITestOutputHelper output)
{
    public const string CorpusId = "mavi-plate-search-skewed-v1";
    public const string QuerySetId = "mavi-plate-search-queries-v1";
    public const string QuerySetV2Id = "mavi-plate-search-skewed-queries-v2";

    /// <summary>SHA-256 of <see cref="Canonical"/> over the v1 set (frozen at <c>b9cb50eb</c>, unchanged; pinned 2026-10-16).</summary>
    public const string QuerySetSha256 = "93bcebaabd402917fc44f946dc18714f8c0d0e9744e26016610c0ff6da7fee98";

    /// <summary>SHA-256 of <see cref="Canonical"/> over the v2 set, pinned when v2 was frozen, before it was measured.</summary>
    public const string QuerySetV2Sha256 = "b2d7d728a4ae23f5241864e55aa56a5a8a17f558c303941bdb06d09f6b0e92fa";
    private const string ModeVariable = "MAVI_PLATE_SEARCH_SCALE_MODE";
    private const string OutputVariable = "MAVI_PLATE_SEARCH_SCALE_OUT";

    private const int Runs = 1_000;
    private const int TracksPerRun = 1_000;
    private const int PageSize = 50;
    private const int WarmUps = 3;
    private const int Samples = 20;
    private const int StressWarmUps = 1;
    private const int StressSamples = 5;
    private const double BudgetMilliseconds = 300;
    private const double CatastrophicMilliseconds = 3_000;
    private const string Fingerprint = "521d596506f98622a5d4e49e8b8a6f7d51c0ec7d8199f257ef097e4db723eb25";
    private const string OlderFingerprint = "0f0e0d0c0b0a09080706050403020100f0e0d0c0b0a09080706050403020100f";
    private const string UnpublishedFingerprint = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    private static readonly JsonSerializerOptions Indented = new() { WriteIndented = true };
    private static readonly DateTimeOffset Epoch =new(2026, 9, 1, 0, 0, 0, TimeSpan.Zero);

    /// <summary>How a frozen query is issued.</summary>
    private enum Kind
    {
        /// <summary>A first page under the measured identity.</summary>
        FirstPage,
        /// <summary>A first page scoped to the newest Ready run.</summary>
        NewestReadyRun,
        /// <summary>A first page with a one-day time window (a Track-level filter) over the newest day.</summary>
        NewestDay,
        /// <summary>The continuation page N (2 or 5), from cursors minted by the preceding pages.</summary>
        Continuation,
        /// <summary>No preferred identity: every run NotConfigured.</summary>
        NotConfigured,
        /// <summary>A preferred identity no run has published: no run Ready.</summary>
        NoRunReady,
        /// <summary>v2: a first page with the query's Track-level filters (<see cref="Filters"/>).</summary>
        Filtered,
        /// <summary>v2: the continuation page N of a filtered query.</summary>
        FilteredContinuation,
        /// <summary>v2: a first page scoped to camera 1 with an analytic predicate (loitering); no camera is configured.</summary>
        AnalyticsUnconfiguredCamera,
    }

    /// <summary>
    /// v2's Track-level filters: time bounds as whole days after the corpus epoch (2026-09-01T00:00Z), and the
    /// minimum confidence, duration and subclass, as the API would pass them.
    /// </summary>
    private sealed record Filters(int? FromDays = null, int? ToDays = null, double? MinimumConfidence = null, long? MinimumDurationMs = null, string? Subclass = null)
    {
        public string Canonical() => string.Create(CultureInfo.InvariantCulture,
            $"from={FromDays};to={ToDays};confidence={MinimumConfidence:R};duration={MinimumDurationMs};subclass={Subclass}");
    }

    private sealed record Frozen(string Name, TrackPlateQuery Plate, Kind Kind, int PageNumber = 1, bool Stress = false, Filters? Filter = null);

    /// <summary>The frozen query set (<see cref="QuerySetId"/>). <c>&lt;newest&gt;</c> is the newest Ready Track's own text.</summary>
    private static readonly Frozen[] FrozenQueries =
    [
        new("Q01 contains KA0 (broad, 3 characters)", new("KA0", TrackPlateMatch.Contains), Kind.FirstPage),
        new("Q02 prefix KA0 (broad, 3 characters)", new("KA0", TrackPlateMatch.Prefix), Kind.FirstPage),
        new("Q03 contains KA01", new("KA01", TrackPlateMatch.Contains), Kind.FirstPage),
        new("Q04 prefix KA01", new("KA01", TrackPlateMatch.Prefix), Kind.FirstPage),
        new("Q05 contains 1234", new("1234", TrackPlateMatch.Contains), Kind.FirstPage),
        new("Q06 exact <newest>", new("<newest>", TrackPlateMatch.Exact), Kind.FirstPage),
        new("Q07 contains ZZ99ZZ (no match)", new("ZZ99ZZ", TrackPlateMatch.Contains), Kind.FirstPage),
        new("Q08 contains KA0 + processingRunId", new("KA0", TrackPlateMatch.Contains), Kind.NewestReadyRun),
        new("Q09 contains KA0, page 2", new("KA0", TrackPlateMatch.Contains), Kind.Continuation, PageNumber: 2),
        new("Q10 contains KA0, page 5", new("KA0", TrackPlateMatch.Contains), Kind.Continuation, PageNumber: 5),
        new("Q11 contains MH12 (rare where the page starts)", new("MH12", TrackPlateMatch.Contains), Kind.FirstPage),
        new("Q12 contains KA01 + one-day window", new("KA01", TrackPlateMatch.Contains), Kind.NewestDay),
        new("Q13 contains KA01, NotConfigured", new("KA01", TrackPlateMatch.Contains), Kind.NotConfigured),
        new("Q14 contains KA01, no run Ready", new("KA01", TrackPlateMatch.Contains), Kind.NoRunReady),
        new("S1 prefix XQ0 (stress: dense only in the oldest 2 %)", new("XQ0", TrackPlateMatch.Prefix), Kind.FirstPage, Stress: true),
    ];

    /// <summary>The frozen query set v2 (<see cref="QuerySetV2Id"/>). Run 21, the oldest with <c>KA</c> texts, starts at day 0.6.</summary>
    private static readonly Frozen[] FrozenQueriesV2 =
    [
        new("V01 contains KA0, toUtc day 1 (historical: the oldest 3 %)", new("KA0", TrackPlateMatch.Contains), Kind.Filtered, Filter: new(ToDays: 1)),
        new("V02 contains KA0, toUtc day 15 (historical: the older half)", new("KA0", TrackPlateMatch.Contains), Kind.Filtered, Filter: new(ToDays: 15)),
        new("V03 contains KA01, toUtc day 1 (historical, selective)", new("KA01", TrackPlateMatch.Contains), Kind.Filtered, Filter: new(ToDays: 1)),
        new("V04 contains KA0, minimumConfidence 0.95 (rejects every Track)", new("KA0", TrackPlateMatch.Contains), Kind.Filtered, Filter: new(MinimumConfidence: 0.95)),
        new("V05 contains KA0, minimumConfidence 0.8 (inclusive boundary, admits every Track)", new("KA0", TrackPlateMatch.Contains), Kind.Filtered, Filter: new(MinimumConfidence: 0.8)),
        new("V06 contains KA0, minimumDurationMs 4001 (rejects every Track)", new("KA0", TrackPlateMatch.Contains), Kind.Filtered, Filter: new(MinimumDurationMs: 4001)),
        new("V07 contains KA0, objectSubclass car (rejects every Track)", new("KA0", TrackPlateMatch.Contains), Kind.Filtered, Filter: new(Subclass: "car")),
        new("V08 contains KA0, fromUtc day 29 (lower bound only)", new("KA0", TrackPlateMatch.Contains), Kind.Filtered, Filter: new(FromDays: 29)),
        new("V09 contains KA0, toUtc day 15, page 2", new("KA0", TrackPlateMatch.Contains), Kind.FilteredContinuation, PageNumber: 2, Filter: new(ToDays: 15)),
        new("V10 contains KA0 + camera 1 + loitering (camera never configured)", new("KA0", TrackPlateMatch.Contains), Kind.AnalyticsUnconfiguredCamera, Filter: new()),
    ];

    /// <summary>A query set's canonical text, one line per query, hashed to pin it (invariant culture).</summary>
    private static string Canonical(Frozen[] set) => string.Join("\n", set.Select(item => string.Create(CultureInfo.InvariantCulture,
        $"{item.Name}|{item.Plate.Text}|{item.Plate.Match}|{item.Kind}|{item.PageNumber}|{item.Stress}|{item.Filter?.Canonical()}")));

    private static string Sha256(string text) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));

    /// <summary>The queries whose real statements are EXPLAINed and whose plan shape is asserted.</summary>
    private static readonly string[] ExplainedQueries = ["Q01", "Q02", "Q07", "Q08", "Q11", "Q12"];

    /// <summary>The v2 queries EXPLAINed under the same shape assertions: every v2 first page.</summary>
    private static readonly string[] ExplainedQueriesV2 = ["V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V10"];

    /// <summary>Relations of 10^6 rows that no warm statement may scan sequentially.</summary>
    private static readonly string[] LargeRelations = ["tracks", "plate_track_texts", "plate_track_outcomes", "plate_observations", "observations"];

    private sealed record Result(
        string QuerySet,
        string Name,
        bool Stress,
        int Rows,
        int Statements,
        double P50,
        double P95,
        double Max,
        TrackPlateCoverage Coverage);

    /// <summary>
    /// The frozen query sets cannot drift silently: v1 is pinned unchanged, and v2 as it was frozen before it was
    /// measured. Runs everywhere (no database), unlike the measurement itself.
    /// </summary>
    [Fact]
    public void TheFrozenQuerySetsArePinned()
    {
        Assert.Equal(QuerySetSha256, Sha256(Canonical(FrozenQueries)));
        Assert.Equal(QuerySetV2Sha256, Sha256(Canonical(FrozenQueriesV2)));
        Assert.Equal(15, FrozenQueries.Length);
        Assert.Equal(10, FrozenQueriesV2.Length);
        Assert.DoesNotContain(FrozenQueriesV2, item => item.Stress);
    }

    [PlateSearchScaleFact]
    public async Task PlateSearchAtTheFrozenSkewedScaleIsMeasured()
    {
        var connectionString = Environment.GetEnvironmentVariable(PlateSearchScaleFactAttribute.Variable)!;
        var mode = Environment.GetEnvironmentVariable(ModeVariable) is { Length: > 0 } configured ? configured : "development";
        Assert.True(mode is "development" or "ci", $"{ModeVariable} must be 'development' or 'ci', not '{mode}'");
        var bound = mode == "ci" ? CatastrophicMilliseconds : BudgetMilliseconds;

        var migration = Stopwatch.StartNew();
        await using (var db = CreateContext(connectionString, null))
            await db.Database.MigrateAsync();
        migration.Stop();
        output.WriteLine($"migrate: {migration.Elapsed.TotalSeconds:F1} s (includes any pending migration's backfill)");
        await SeedAsync(connectionString);

        // ADR-018: the denormalised Track start equals the authoritative one for every text of the corpus.
        var drift = Convert.ToInt64(await ScalarAsync(connectionString, """
            SELECT count(*) FROM plate_track_texts x JOIN tracks t ON t.id = x.track_id
            WHERE x.track_start_timestamp_utc IS DISTINCT FROM t.start_timestamp_utc
            """), CultureInfo.InvariantCulture);
        output.WriteLine($"track_start drift rows: {drift}");
        Assert.Equal(0, drift);

        var newestText = (string)(await ScalarAsync(connectionString, $"""
            SELECT x.normalised_text FROM plate_track_texts x
            JOIN plate_analyses a ON a.id = x.analysis_id AND a.identity_fingerprint = '{Fingerprint}'
            JOIN tracks t ON t.id = x.track_id
            ORDER BY t.start_timestamp_utc DESC, t.id DESC LIMIT 1
            """))!;
        var newestReadyRun = (Guid)(await ScalarAsync(connectionString, "SELECT md5('run-999')::uuid"))!;

        // Both query sets are pinned before anything is measured: v1 unchanged, v2 as frozen.
        var v1Sha256 = Sha256(Canonical(FrozenQueries));
        var v2Sha256 = Sha256(Canonical(FrozenQueriesV2));
        output.WriteLine($"{QuerySetId} sha256 {v1Sha256}; {QuerySetV2Id} sha256 {v2Sha256}");
        Assert.Equal(QuerySetSha256, v1Sha256);
        Assert.Equal(QuerySetV2Sha256, v2Sha256);
        var firstCamera = (Guid)(await ScalarAsync(connectionString, "SELECT md5('camera-1')::uuid"))!;

        var results = new List<Result>();
        double? coldFirstCall = null;
        foreach (var (querySet, frozen) in FrozenQueries.Select(item => (QuerySetId, item)).Concat(FrozenQueriesV2.Select(item => (QuerySetV2Id, item))))
        {
            var plate = frozen.Plate.Text == "<newest>" ? frozen.Plate with { Text = newestText } : frozen.Plate;
            var search = SearchFor(frozen, plate, newestReadyRun, firstCamera);
            var fingerprint = PreferredFingerprint(frozen.Kind);
            var cursor = frozen.Kind is Kind.Continuation or Kind.FilteredContinuation
                ? await CursorForPageAsync(connectionString, search, frozen.PageNumber)
                : null;

            var samples = new List<double>();
            TrackPlateSearchRepositoryPage? page = null;
            var (warmUps, count) = frozen.Stress ? (StressWarmUps, StressSamples) : (WarmUps, Samples);
            for (var index = 0; index < warmUps + count; index++)
            {
                await using var db = CreateContext(connectionString, null);
                var repository = new TrackSearchRepository(db, TimeProvider.System);
                var stopwatch = Stopwatch.StartNew();
                page = (await repository.SearchPlatesAsync(search, fingerprint, cursor, PageSize + 1, default)).Page!;
                stopwatch.Stop();
                coldFirstCall ??= stopwatch.Elapsed.TotalMilliseconds;
                if (index >= warmUps) samples.Add(stopwatch.Elapsed.TotalMilliseconds);
            }

            var capture = new SqlCapture();
            await using (var db = CreateContext(connectionString, capture))
                await new TrackSearchRepository(db, TimeProvider.System).SearchPlatesAsync(search, fingerprint, cursor, PageSize + 1, default);

            samples.Sort();
            results.Add(new Result(querySet, frozen.Name, frozen.Stress, page!.Items.Count, capture.Statements.Count,
                Percentile(samples, 0.50), Percentile(samples, 0.95), samples[^1], page.PlateCoverage));
        }

        // The real statements of a warm call, replayed under EXPLAIN (ANALYZE, BUFFERS).
        var plans = new StringBuilder();
        var shapeFailures = new List<string>();
        var explained = ExplainedQueries.Select(prefix => FrozenQueries.Single(item => item.Name.StartsWith(prefix + " ", StringComparison.Ordinal)))
            .Concat(ExplainedQueriesV2.Select(prefix => FrozenQueriesV2.Single(item => item.Name.StartsWith(prefix + " ", StringComparison.Ordinal))));
        foreach (var frozen in explained)
        {
            var search = SearchFor(frozen, frozen.Plate, newestReadyRun, firstCamera);
            var capture = new SqlCapture();
            await using (var db = CreateContext(connectionString, capture))
                await new TrackSearchRepository(db, TimeProvider.System).SearchPlatesAsync(search, PreferredFingerprint(frozen.Kind), null, PageSize + 1, default);

            var queryPlans = new List<string>();
            foreach (var statement in capture.Statements)
            {
                // Replayed with the search's own transaction setting (ADR-019), so the plan is the one it runs.
                var plan = await SqlCapture.ExplainAsync(connectionString, statement, sessionSetting: TrackSearchRepository.NoParallelWorkers);
                queryPlans.Add(plan);
                plans.AppendLine(CultureInfo.InvariantCulture, $"===== {frozen.Name}");
                plans.AppendLine(statement.Sql);
                plans.AppendLine("-----");
                plans.AppendLine(plan);
                foreach (var relation in LargeRelations)
                {
                    if (plan.Contains($"Seq Scan on public.{relation} ", StringComparison.Ordinal))
                        shapeFailures.Add($"{frozen.Name}: a statement scans {relation} sequentially");
                }
            }

            // A contains search reads its candidates through the trigram index (ADR-018's candidate statement).
            if (frozen.Name.StartsWith("Q07 ", StringComparison.Ordinal) || frozen.Name.StartsWith("Q11 ", StringComparison.Ordinal))
            {
                if (!queryPlans.Any(plan => plan.Contains("ix_plate_track_texts_normalised_text_trgm", StringComparison.Ordinal)))
                    shapeFailures.Add($"{frozen.Name}: no statement reads ix_plate_track_texts_normalised_text_trgm");
            }
        }

        var report = new StringBuilder();
        report.AppendLine(mode == "ci"
            ? string.Create(CultureInfo.InvariantCulture, $"mode: ci (INFORMATIONAL CI DIAGNOSTIC; qualificationEvidence: false; not the Development budget); corpus {CorpusId}; " +
              $"query sets {QuerySetId} ({v1Sha256}) and {QuerySetV2Id} ({v2Sha256}); catastrophic bound p95 ≤ {CatastrophicMilliseconds} ms (stress probe reported only)")
            : string.Create(CultureInfo.InvariantCulture, $"mode: development; corpus {CorpusId}; query sets {QuerySetId} ({v1Sha256}) and {QuerySetV2Id} ({v2Sha256}); " +
              $"budget p95 ≤ {BudgetMilliseconds} ms (stress probe reported only)"));
        report.AppendLine(CultureInfo.InvariantCulture, $"cold first call (process caches empty): {coldFirstCall:F1} ms");
        report.AppendLine("query set | query | rows | statements | p50 ms | p95 ms | max ms | coverage (ready/pending/failed/stale/notConfigured of inScope)");
        foreach (var result in results)
        {
            var coverage = result.Coverage;
            report.AppendLine(CultureInfo.InvariantCulture,
                $"{result.QuerySet} | {result.Name} | {result.Rows} | {result.Statements} | {result.P50:F1} | {result.P95:F1} | {result.Max:F1} | " +
                $"{coverage.Ready}/{coverage.Pending}/{coverage.Failed}/{coverage.Stale}/{coverage.NotConfigured} of {coverage.VehicleTracksInScope}");
        }

        output.WriteLine(report.ToString());
        output.WriteLine(plans.ToString());
        await WriteOutputsAsync(mode, v1Sha256, v2Sha256, coldFirstCall!.Value, results, report.ToString(), plans.ToString(), shapeFailures);

        var failures = results
            .Where(result => !result.Stress && result.P95 > bound)
            .Select(result => $"{result.Name}: p95 {result.P95:F1} ms exceeds {bound} ms")
            .Concat(shapeFailures)
            .ToList();
        Assert.True(failures.Count == 0, string.Join(Environment.NewLine, failures));
    }

    private static TrackSearchQuery SearchFor(Frozen frozen, TrackPlateQuery plate, Guid newestReadyRun, Guid firstCamera)
    {
        var search = new TrackSearchQuery(null, null, null, ObjectClass.Vehicle, null, null, null, null, null, PageSize, Plate: plate);
        search = frozen.Kind switch
        {
            Kind.NewestReadyRun => search with { ProcessingRunId = newestReadyRun },
            Kind.NewestDay => search with { FromUtc = Epoch.AddDays(29), ToUtc = Epoch.AddDays(31) },
            Kind.AnalyticsUnconfiguredCamera => search with { CameraId = firstCamera, Analytics = TrackAnalyticsQuery.Empty with { Loitering = true } },
            _ => search,
        };
        if (frozen.Filter is { } filter)
        {
            search = search with
            {
                FromUtc = filter.FromDays is { } from ? Epoch.AddDays(from) : search.FromUtc,
                ToUtc = filter.ToDays is { } to ? Epoch.AddDays(to) : search.ToUtc,
                MinimumConfidence = filter.MinimumConfidence ?? search.MinimumConfidence,
                MinimumDurationMs = filter.MinimumDurationMs ?? search.MinimumDurationMs,
                ObjectSubclass = filter.Subclass ?? search.ObjectSubclass,
            };
        }

        return search;
    }

    private static string? PreferredFingerprint(Kind kind) => kind switch
    {
        Kind.NotConfigured => null,
        Kind.NoRunReady => UnpublishedFingerprint,
        _ => Fingerprint,
    };

    /// <summary>The cursor of page <paramref name="pageNumber"/>, minted from the pages before it (untimed).</summary>
    private static async Task<TrackPlateCursorPosition> CursorForPageAsync(string connectionString, TrackSearchQuery search, int pageNumber)
    {
        TrackPlateCursorPosition? cursor = null;
        for (var page = 1; page < pageNumber; page++)
        {
            await using var db = CreateContext(connectionString, null);
            var result = (await new TrackSearchRepository(db, TimeProvider.System)
                .SearchPlatesAsync(search, cursor?.PlateIdentityFingerprint ?? Fingerprint, cursor, PageSize + 1, default)).Page!;
            Assert.Equal(PageSize + 1, result.Items.Count);
            var last = result.Items[PageSize - 1];
            cursor = new TrackPlateCursorPosition(
                new TrackCursorPosition(result.SnapshotUtc, result.SnapshotVisibilitySequence, last.StartTimestampUtc, last.Id, new string('a', 64)),
                cursor?.PlateIdentityFingerprint ?? Fingerprint,
                cursor?.PlateCoverage ?? result.PlateCoverage);
        }

        return cursor!;
    }

    /// <summary>
    /// The Development measurement (with the 300 ms budget) or the informational CI diagnostic (with the
    /// catastrophic bound only, its own file names, and <c>qualificationEvidence = false</c>): never both in one file.
    /// </summary>
    private async Task WriteOutputsAsync(
        string mode, string v1Sha256, string v2Sha256, double coldFirstCall, List<Result> results, string report, string plans, List<string> shapeFailures)
    {
        if (Environment.GetEnvironmentVariable(OutputVariable) is not { Length: > 0 } directory)
            return;
        Directory.CreateDirectory(directory);
        var querySets = new[] { (Id: QuerySetId, Sha256: v1Sha256), (Id: QuerySetV2Id, Sha256: v2Sha256) }.Select(set => new
        {
            id = set.Id,
            sha256 = set.Sha256,
            results = results.Where(result => result.QuerySet == set.Id).Select(result => new
            {
                name = result.Name,
                stress = result.Stress,
                rows = result.Rows,
                statements = result.Statements,
                p50 = result.P50,
                p95 = result.P95,
                max = result.Max,
                coverage = result.Coverage,
            }),
        });

        string json, prefix;
        if (mode == "ci")
        {
            prefix = "plate-search-scale-ci-diagnostic";
            json = JsonSerializer.Serialize(new
            {
                kind = "informational CI diagnostic (plate-search-scale-informational.yml); not a merge gate",
                qualificationEvidence = false,
                developmentEvidence = false,
                corpus = CorpusId,
                mode,
                catastrophicBoundMilliseconds = CatastrophicMilliseconds,
                coldFirstCallMilliseconds = coldFirstCall,
                querySets,
                shapeFailures,
            }, Indented);
        }
        else
        {
            prefix = "plate-search-scale";
            json = JsonSerializer.Serialize(new
            {
                kind = "Development-host measurement (plan §2.8 budget)",
                corpus = CorpusId,
                mode,
                budgetMilliseconds = BudgetMilliseconds,
                coldFirstCallMilliseconds = coldFirstCall,
                querySets,
                shapeFailures,
            }, Indented);
        }

        await File.WriteAllTextAsync(Path.Combine(directory, prefix + ".json"), json);
        await File.WriteAllTextAsync(Path.Combine(directory, prefix + "-plans.txt"), report + Environment.NewLine + plans);
        output.WriteLine($"wrote the measurement to {directory}");
    }

    private static double Percentile(List<double> sorted, double quantile) =>
        sorted[Math.Clamp((int)Math.Ceiling(quantile * sorted.Count) - 1, 0, sorted.Count - 1)];

    private static MaviDbContext CreateContext(string connectionString, SqlCapture? capture)
    {
        var builder = new DbContextOptionsBuilder<MaviDbContext>().UseNpgsql(connectionString, npgsql => npgsql.UseVector());
        if (capture is not null) builder.AddInterceptors(capture);
        return new MaviDbContext(builder.Options);
    }

    private static async Task<object?> ScalarAsync(string connectionString, string sql)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection) { CommandTimeout = 0 };
        return await command.ExecuteScalarAsync();
    }

    /// <summary>Seeds the frozen corpus once into an empty scratch database, then vacuums and analyses.</summary>
    private async Task SeedAsync(string connectionString)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync();
        await using (var marker = new NpgsqlCommand("CREATE TABLE IF NOT EXISTS mavi_scale_corpus (id text PRIMARY KEY)", connection))
            await marker.ExecuteNonQueryAsync();
        await using (var read = new NpgsqlCommand("SELECT string_agg(id, ',') FROM mavi_scale_corpus", connection))
        {
            if (await read.ExecuteScalarAsync() is string seeded)
            {
                Assert.True(seeded == CorpusId, $"the scratch database holds corpus '{seeded}', not {CorpusId}; use an empty database");
                return;
            }
        }

        await using (var tracks = new NpgsqlCommand("SELECT count(*) FROM tracks", connection))
            Assert.True(Convert.ToInt64(await tracks.ExecuteScalarAsync(), CultureInfo.InvariantCulture) == 0,
                "the scratch database already holds Tracks of another corpus; use an empty database");

        var stopwatch = Stopwatch.StartNew();
        foreach (var step in SeedSteps())
        {
            await using var command = new NpgsqlCommand(step, connection) { CommandTimeout = 0 };
            await command.ExecuteNonQueryAsync();
        }

        await using (var vacuum = new NpgsqlCommand("VACUUM ANALYZE", connection) { CommandTimeout = 0 })
            await vacuum.ExecuteNonQueryAsync();
        await using (var mark = new NpgsqlCommand($"INSERT INTO mavi_scale_corpus (id) VALUES ('{CorpusId}')", connection))
            await mark.ExecuteNonQueryAsync();
        output.WriteLine($"seeded {CorpusId} in {stopwatch.Elapsed.TotalSeconds:F0} s");
    }

    /// <summary>The frozen corpus, <see cref="CorpusId"/>.</summary>
    private static string[] SeedSteps() =>
    [
        // Parents: cameras, source artefacts, videos (1 h each), runs, prediction artefacts.
        """
        INSERT INTO cameras (id, code, name, time_zone_id, is_active, created_at_utc, updated_at_utc)
        SELECT md5('camera-' || c)::uuid, 'CAM-SCALE-' || c, 'Scale camera ' || c, 'UTC', true, now(), now()
        FROM generate_series(1, 10) AS c;
        """,
        $$"""
        INSERT INTO artifacts (id, artifact_type, storage_key, mime_type, size_bytes, sha256, created_at_utc)
        SELECT md5('source-' || v)::uuid, 'SourceVideo', 'source/scale/' || v || '.mp4', 'video/mp4', 1, md5('source-' || v) || md5('source-sha-' || v), now()
        FROM generate_series(1, {{Runs}}) AS v;
        """,
        $$"""
        INSERT INTO video_assets (id, camera_id, source_artifact_id, original_file_name, source_type, recording_start_utc, recording_end_utc,
            duration_ms, frame_rate_numerator, frame_rate_denominator, width, height, codec, timestamp_source, timestamp_confidence,
            processing_status, imported_at_utc, recording_time_zone_id, recording_utc_offset_minutes)
        SELECT md5('video-' || v)::uuid, md5('camera-' || (1 + v % 10))::uuid, md5('source-' || v)::uuid, 'scale-' || v || '.mp4', 'UploadedFile',
            timestamptz '2026-09-01 00:00:00+00' + (v - 1) * interval '43 minutes',
            timestamptz '2026-09-01 00:00:00+00' + (v - 1) * interval '43 minutes' + interval '1 hour',
            3600000, 25, 1, 1920, 1080, 'h264', 'Manual', 1.0, 'Processed', now(), 'UTC', 0
        FROM generate_series(1, {{Runs}}) AS v;
        """,
        $$"""
        INSERT INTO processing_runs (id, video_asset_id, status, pipeline_version, configuration_json, queued_at_utc, started_at_utc, completed_at_utc,
            frames_processed, tracks_created, processing_duration_ms, visibility_sequence)
        SELECT md5('run-' || v)::uuid, md5('video-' || v)::uuid, 'Completed', 'phase1-v1', '{}', now(), now(), now(), 90000, {{TracksPerRun}}, 1000,
            nextval('processing_visibility_sequence')
        FROM generate_series(1, {{Runs}}) AS v ORDER BY v;
        """,
        $$"""
        INSERT INTO artifacts (id, artifact_type, storage_key, mime_type, size_bytes, sha256, created_at_utc)
        SELECT md5('predictions-' || v)::uuid, 'PlatePredictions', 'evidence/plates/scale-' || v || '.json', 'application/json', 1,
            md5('predictions-' || v) || md5('predictions-sha-' || v), now()
        FROM generate_series(1, {{Runs}}) AS v;
        """,
        // 10^6 Vehicle Tracks, 2.592 s apart across the 30 days (run v holds Tracks (v-1)·1000+1 … v·1000, so
        // newer runs hold newer Tracks), and one Representative Observation each.
        $$"""
        INSERT INTO tracks (id, processing_run_id, video_asset_id, local_track_number, object_class, start_offset_ms, end_offset_ms,
            start_timestamp_utc, end_timestamp_utc, duration_ms, detection_count, mean_confidence, max_confidence, review_status, created_at_utc)
        SELECT uuidv7(), md5('run-' || (1 + (i - 1) / {{TracksPerRun}}))::uuid, md5('video-' || (1 + (i - 1) / {{TracksPerRun}}))::uuid,
            1 + (i - 1) % {{TracksPerRun}}, 'Vehicle', 0, 4000,
            timestamptz '2026-09-01 00:00:00+00' + i * interval '2592 milliseconds',
            timestamptz '2026-09-01 00:00:04+00' + i * interval '2592 milliseconds',
            4000, 40, 0.8, 0.9, 'Unreviewed', now()
        FROM generate_series(1, {{Runs * TracksPerRun}}) AS i;
        """,
        """
        INSERT INTO observations (id, track_id, observation_type, source_frame_number, video_offset_ms, timestamp_utc, bounding_box_x, bounding_box_y,
            bounding_box_width, bounding_box_height, confidence, quality_score, created_at_utc, evidence_rank, selection_score)
        SELECT uuidv7(), t.id, 'Representative', 10, 400, t.start_timestamp_utc, 0.1, 0.1, 0.2, 0.2, 0.8, 0.7, now(), 0, 0.7
        FROM tracks t;
        """,
        "UPDATE tracks t SET representative_observation_id = o.id FROM observations o WHERE o.track_id = t.id;",
        // One completed analysis per run: of the measured identity, except every tenth run, whose only
        // analysis is of an older identity (not Ready for the measured one). Then one Read plate and one
        // Track text per Track.
        $$"""
        INSERT INTO plate_analyses (id, processing_run_id, identity_fingerprint, pipeline_id, pipeline_version, predictions_schema_version,
            normalisation_id, normalisation_sha256, summary_policy_id, summary_policy_version, summary_policy_sha256, capabilities_canonical,
            parameters_sha256, status, attempt_count, queued_at_utc, first_claimed_at_utc, completed_at_utc, completion_digest,
            prediction_artifact_id, provenance_json, tracks_analysed, tracks_unavailable, plate_observations_read, plate_observations_unreadable,
            visibility_sequence)
        SELECT md5('analysis-' || v)::uuid, md5('run-' || v)::uuid,
            CASE WHEN v % 10 = 0 THEN '{{OlderFingerprint}}' ELSE '{{Fingerprint}}' END,
            'plates-fixture', '1.0.0', 'mavi-plate-predictions-v1',
            'mavi-plate-normalisation-v1', '6e505158a735a1c4c5d96ad33d08e4ddb0b98d456f0dd532a6af25de120bf935', 'plate-track-text-rank0', '1.0.0',
            '1fb72dd2ce254a2190cd19290bc7304342d16bdacc417a03e7589cd202eecd1f',
            '[{"capabilityId":"ocr","modelPackId":"mavi-model-v2-{{new string('3', 64)}}"},{"capabilityId":"plate-detector","modelPackId":"mavi-model-v2-{{new string('4', 64)}}"}]',
            'd19bf0705c880fdf49895f99ba95e5bda61843222d1111764173e877b0128e02', 'Completed', 1, now(), now(), now(), md5('digest-' || v) || md5('d2-' || v),
            md5('predictions-' || v)::uuid, '{}', {{TracksPerRun}}, 0, {{TracksPerRun}}, 0, nextval('processing_visibility_sequence')
        FROM generate_series(1, {{Runs}}) AS v ORDER BY v;
        """,
        """
        INSERT INTO plate_track_outcomes (analysis_id, track_id, outcome, plate_observation_count, distinct_text_count)
        SELECT a.id, t.id, 'Analysed', 1, 1 FROM tracks t JOIN plate_analyses a ON a.processing_run_id = t.processing_run_id;
        """,
        """
        INSERT INTO plate_observations (id, analysis_id, track_id, source_observation_id, plate_index, box_x, box_y, box_width, box_height,
            crop_width, crop_height, detector_confidence, outcome)
        SELECT uuidv7(), a.id, t.id, t.representative_observation_id, 0, 150, 240, 118, 30, 412, 330, 0.95, 'Read'
        FROM tracks t JOIN plate_analyses a ON a.processing_run_id = t.processing_run_id;
        """,
        // The skewed texts: runs 1–20 (the oldest 2 %) are all XQ0d; elsewhere KA 70 %, MH 10 %, 34 other
        // codes 20 %; district, series and number hash-uniform.
        """
        INSERT INTO plate_track_texts (analysis_id, track_id, normalised_text, support_count, max_confidence, best_plate_observation_id)
        SELECT p.analysis_id, p.track_id,
            CASE WHEN r.v <= 20 THEN 'XQ0' || (h.h1 % 10)::text
                 ELSE CASE WHEN h.h1 % 100 < 70 THEN 'KA'
                           WHEN h.h1 % 100 < 80 THEN 'MH'
                           ELSE (ARRAY['DL','TN','AP','TS','GJ','RJ','UP','MP','WB','KL','PB','HR','BR','OD','CG','JH','UK','HP','JK','GA','AS',
                                       'TR','ML','MN','MZ','NL','AR','SK','CH','PY','AN','DN','LD','LA'])[1 + (h.h1 / 100 % 34)::int] END
                      || lpad((h.h1 / 3400 % 100)::text, 2, '0') END
            || chr(65 + (h.h2 % 26)::int) || chr(65 + (h.h2 / 26 % 26)::int) || lpad((h.h2 / 676 % 10000)::text, 4, '0'),
            1, 0.9, p.id
        FROM plate_observations p
        JOIN tracks t ON t.id = p.track_id
        JOIN video_assets va ON va.id = t.video_asset_id
        CROSS JOIN LATERAL (SELECT 1 + (extract(epoch FROM va.recording_start_utc - timestamptz '2026-09-01 00:00:00+00') / 2580)::int AS v) AS r
        CROSS JOIN LATERAL (SELECT ('x' || substr(md5(p.track_id::text), 1, 8))::bit(32)::bigint AS h1,
                                   ('x' || substr(md5(p.track_id::text), 9, 8))::bit(32)::bigint AS h2) AS h;
        """,
    ];
}
