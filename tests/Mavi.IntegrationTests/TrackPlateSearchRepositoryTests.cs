using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Plates;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Plates;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Configurations;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.IntegrationTests.Qualification;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// The plate search at the repository over a real database (Stage 4 PR-4, plan §2.8): the AND with
/// analytic predicates under the single-camera analytics scope, the bounded statement count, the
/// additive migration and the access paths the predicates can use.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class TrackPlateSearchRepositoryTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 10, 13, 6, 0, 0, TimeSpan.Zero);
    private const string PrecedingMigration = "20261013022604_AddPlateAnalysisLifecycle";
    private const string SearchMigration = "20261013120000_AddPlateSearchIndexes";

    /// <summary>
    /// The 200 000-row probe's insert and VACUUM take ~10 s alone and over Npgsql's 30 s default on a
    /// PostgreSQL server shared with other concurrent runs (observed: two timeouts in five repeats). The bound
    /// is generous, not infinite, so a hung server still fails the test.
    /// </summary>
    private const int ProbeSetupTimeoutSeconds = 300;

    private static readonly PlateIdentityFields Identity = new(
        "521d596506f98622a5d4e49e8b8a6f7d51c0ec7d8199f257ef097e4db723eb25",
        "plates-fixture", "1.0.0", "mavi-plate-predictions-v1", "mavi-plate-normalisation-v1",
        "6e505158a735a1c4c5d96ad33d08e4ddb0b98d456f0dd532a6af25de120bf935",
        "plate-track-text-rank0", "1.0.0", "1fb72dd2ce254a2190cd19290bc7304342d16bdacc417a03e7589cd202eecd1f",
        "[{\"capabilityId\":\"ocr\",\"modelPackId\":\"mavi-model-v2-" + new string('3', 64) + "\"},{\"capabilityId\":\"plate-detector\",\"modelPackId\":\"mavi-model-v2-" + new string('4', 64) + "\"}]",
        "d19bf0705c880fdf49895f99ba95e5bda61843222d1111764173e877b0128e02");

    private static TrackSearchQuery PlateQuery(string text, TrackPlateMatch match = TrackPlateMatch.Contains) =>
        new(null, null, null, ObjectClass.Vehicle, null, null, null, null, null, 50, Plate: new TrackPlateQuery(text, match));

    // --- Combination with analytics --------------------------------------------------------------

    /// <summary>
    /// The analytic world's single Track made a Vehicle, with analytics facts (one zone visit of 4 000 ms,
    /// loitering) and a plate text. Each predicate narrows independently, so only both together match.
    /// </summary>
    [Fact]
    public async Task APlatePredicateIsAndedWithAnalyticPredicatesInsideTheAnalyticsScope()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using (var db = fixture.CreateDbContext())
            await db.Database.ExecuteSqlInterpolatedAsync($"UPDATE tracks SET object_class = 'Vehicle' WHERE id = {world.TrackId}");
        await CommitAnalyticsFactsAsync(world);
        var observation = await AddObservationAsync(world);
        await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, world.RunId, Identity,
            [SeedPlateTrack.Analysed(world.TrackId, new SeedPlate(observation, 0.9, ("KA01AB1234", 0.9)))]);
        var repository = new TrackSearchRepository(fixture.CreateDbContext(), world.Clock);

        async Task<TrackPlateSearchRepositoryPage> Search(TrackSearchQuery query) =>
            (await repository.SearchPlatesAsync(query, Identity.Fingerprint, null, 51, default)).Page!;

        var zone = TrackAnalyticsQuery.Empty with { ZoneId = world.ZoneId };
        var both = await Search(PlateQuery("KA01") with { CameraId = world.CameraId, Analytics = zone });
        Assert.Equal(world.TrackId, Assert.Single(both.Items).Id);
        Assert.Equal("KA01AB1234", both.ItemPlates[world.TrackId].MatchedText);
        Assert.Single(both.ItemAnalytics!);
        Assert.Equal(new TrackAnalyticsPinnedIdentity(world.CameraId, world.RevisionId, SceneAnalyticsWorld.AlgorithmVersion), both.AnalyticsIdentity);
        Assert.Equal(1, both.AnalyticsCoverage!.EvaluatedRuns);
        Assert.Equal(1, both.PlateCoverage.Ready);

        // Either predicate alone failing empties the page; the coverage blocks stay.
        var wrongPlate = await Search(PlateQuery("MH12") with { CameraId = world.CameraId, Analytics = zone });
        Assert.Empty(wrongPlate.Items);
        Assert.Equal(1, wrongPlate.PlateCoverage.VehicleTracksInScope);
        Assert.Empty((await Search(PlateQuery("KA01") with { CameraId = world.CameraId, Analytics = zone with { MinDwellMs = 4_001 } })).Items);

        // The analytics single-camera scope stays authoritative: without a camera scope it is refused.
        Assert.False((await repository.SearchPlatesAsync(PlateQuery("KA01") with { Analytics = zone }, Identity.Fingerprint, null, 51, default)).IsValid);
        // A plate-only search spans cameras.
        Assert.Single((await Search(PlateQuery("KA01"))).Items);
    }

    [Fact]
    public async Task ACombinedContinuationIsPinnedToBothIdentities()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await using (var db = fixture.CreateDbContext())
            await db.Database.ExecuteSqlInterpolatedAsync($"UPDATE tracks SET object_class = 'Vehicle' WHERE id = {world.TrackId}");
        await CommitAnalyticsFactsAsync(world);
        var observation = await AddObservationAsync(world);
        await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, world.RunId, Identity,
            [SeedPlateTrack.Analysed(world.TrackId, new SeedPlate(observation, 0.9, ("KA01AB1234", 0.9)))]);
        var repository = new TrackSearchRepository(fixture.CreateDbContext(), world.Clock);
        var query = PlateQuery("KA01") with { CameraId = world.CameraId, Analytics = TrackAnalyticsQuery.Empty with { ZoneId = world.ZoneId } };
        var first = (await repository.SearchPlatesAsync(query, Identity.Fingerprint, null, 51, default)).Page!;

        // A new active revision after the first page: the continuation stays on the pinned revision.
        await world.ActivateNewRevisionAsync(Now.AddMinutes(1));
        var cursor = new TrackPlateCursorPosition(
            new TrackCursorPosition(first.SnapshotUtc, first.SnapshotVisibilitySequence, Now.AddHours(1), Guid.CreateVersion7(), new string('a', 64)),
            Identity.Fingerprint, first.PlateCoverage, first.AnalyticsIdentity, first.AnalyticsCoverage);
        var next = (await repository.SearchPlatesAsync(query, null, cursor, 51, default)).Page!;

        Assert.Equal(world.TrackId, Assert.Single(next.Items).Id);
        Assert.Equal(first.AnalyticsIdentity, next.AnalyticsIdentity);
        Assert.Equal(first.PlateCoverage, next.PlateCoverage);
        // A camera scope that no longer resolves to the pinned camera is refused.
        Assert.False((await repository.SearchPlatesAsync(query with { CameraId = Guid.CreateVersion7() }, null, cursor, 51, default)).IsValid);
    }

    // --- Page strategies ---------------------------------------------------------------------------

    /// <summary>
    /// The walk, the sparse path and the sparse path's overflow back into the walk all return exactly the
    /// plate predicate's rows in page order, across every page (cold review P1-1). The batch and cap sizes are
    /// shrunk so a 24-Track corpus drives every path: a text matching most Tracks (walk), a text matching two
    /// old Tracks (sparse path within the cap) and one matching five Tracks spread out (sparse path over the
    /// cap of three, so the walk resumes).
    /// </summary>
    [Theory]
    [InlineData("AAA", TrackPlateMatch.Contains)]
    [InlineData("ZZZ", TrackPlateMatch.Contains)]
    [InlineData("MID", TrackPlateMatch.Contains)]
    [InlineData("MID", TrackPlateMatch.Prefix)]
    [InlineData("QQQ", TrackPlateMatch.Contains)]
    [InlineData("AAA0001", TrackPlateMatch.Exact)]
    public async Task EveryPageStrategyReturnsExactlyThePredicateInPageOrder(string text, TrackPlateMatch match)
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var stored = new Dictionary<Guid, string>();
        var position = 0;
        for (var runIndex = 0; runIndex < 3; runIndex++)
        {
            var run = await world.SeedRunAsync(persons: 1, vehicles: 8);
            var seeds = new List<SeedPlateTrack>();
            foreach (var track in run.Tracks.Where(track => track.ObjectClass == ObjectClass.Vehicle))
            {
                position++;
                var value = position switch
                {
                    3 or 4 => $"ZZZ{position:0000}",
                    6 or 10 or 14 or 18 or 22 => $"MID{position:0000}",
                    _ => $"AAA{position:0000}",
                };
                stored[track.TrackId] = value;
                seeds.Add(SeedPlateTrack.Analysed(track.TrackId, new SeedPlate(track.Observations[0].ObservationId, 0.9, (value, 0.9))));
            }

            await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, run.RunId, Identity, seeds);
        }

        long snapshot;
        await using (var db = fixture.CreateDbContext())
            snapshot = await TrackPlateSearchWorld.NextSequenceAsync(db);

        var plate = new TrackPlateQuery(text, match);
        var everyRow = await (from track in fixture.CreateDbContext().Tracks.AsNoTracking()
                              where track.ObjectClass == ObjectClass.Vehicle
                              orderby track.StartTimestampUtc descending, track.Id descending
                              select track.Id).ToListAsync();
        var expected = everyRow.Where(id => TrackPlateQueryRules.Matches(plate, stored[id])).ToList();

        foreach (var limit in new[] { 1, 2, 5, 50 })
        {
            var seen = new List<Guid>();
            TrackCursorPosition? keyset = null;
            while (true)
            {
                var repository = new TrackSearchRepository(fixture.CreateDbContext(), world.Clock)
                {
                    FirstWalkBatch = 2,
                    MaximumWalkBatch = 4,
                    MaximumScopedMatchIds = 3,
                };
                var cursor = keyset is null
                    ? null
                    : new TrackPlateCursorPosition(keyset, Identity.Fingerprint, TrackPlateCoverage.Empty(Identity.Fingerprint));
                var page = (await repository.SearchPlatesAsync(PlateQuery(text, match), Identity.Fingerprint, cursor, limit + 1, default)).Page!;
                var rows = page.Items.Take(limit).ToList();
                seen.AddRange(rows.Select(row => row.Id));
                Assert.Equal(rows.Count, rows.Count(row => page.ItemPlates.ContainsKey(row.Id)));
                if (page.Items.Count <= limit) break;
                keyset = new TrackCursorPosition(Now, snapshot, rows[^1].StartTimestampUtc, rows[^1].Id, new string('a', 64));
            }

            Assert.True(expected.SequenceEqual(seen), $"{text} {match} limit {limit}: expected {expected.Count}, got {seen.Count}");
        }
    }

    // --- Query shape -----------------------------------------------------------------------------

    /// <summary>
    /// A first page and its continuation each cost a fixed number of SELECTs whatever the page size: one
    /// read of the runs in scope, one of their plate analyses (every run is Ready, so no Track count), one
    /// walk batch of the scope's Track ids, their plate check, the page restricted to the matches, and one
    /// explanation keyed on the page's Tracks.
    /// </summary>
    [Fact]
    public async Task APageCostsTheSameStatementsForTwoRowsOrTwenty()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var runs = new List<SeededRun>();
        for (var index = 0; index < 4; index++)
        {
            var run = await world.SeedRunAsync(persons: 0, vehicles: 6);
            runs.Add(run);
            await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, run.RunId, Identity,
            [
                .. run.Tracks.Select((track, position) => SeedPlateTrack.Analysed(track.TrackId,
                    new SeedPlate(track.Observations[0].ObservationId, 0.9, ($"KA{index:00}AB{position:0000}", 0.9)))),
            ]);
        }

        async Task<(int Statements, int Rows)> Measure(int take)
        {
            var capture = new SqlCapture();
            await using var db = new MaviDbContext(new DbContextOptionsBuilder<MaviDbContext>()
                .UseNpgsql(fixture.ConnectionString, npgsql => npgsql.UseVector())
                .AddInterceptors(capture)
                .Options);
            var page = (await new TrackSearchRepository(db, world.Clock).SearchPlatesAsync(PlateQuery("AB0"), Identity.Fingerprint, null, take, default)).Page!;
            Assert.Equal(take, page.ItemPlates.Count);
            return (capture.Statements.Count, page.Items.Count);
        }

        var small = await Measure(2);
        var large = await Measure(20);

        Assert.Equal(2, small.Rows);
        Assert.Equal(20, large.Rows);
        Assert.Equal(small.Statements, large.Statements);
        Assert.Equal(6, small.Statements);
    }

    /// <summary>A Track's plate facts cost the same five statements for one plate observation or four.</summary>
    [Fact]
    public async Task TheDetailFactsCostTheSameStatementsForOnePlateOrFour()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await world.SeedRunAsync(persons: 0, vehicles: 2, observationsPerTrack: 4);
        var (one, four) = (run.Track(0), run.Track(1));
        var analysisId = await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, run.RunId, Identity,
        [
            SeedPlateTrack.Analysed(one.TrackId, new SeedPlate(one.Observations[0].ObservationId, 0.9, ("KA01AB1234", 0.9))),
            SeedPlateTrack.Analysed(four.TrackId,
            [
                .. four.Observations.Select((observation, index) =>
                    new SeedPlate(observation.ObservationId, 0.9, ($"KA01AB123{index}", 0.9), ($"KA01AB128{index}", 0.5))),
            ]),
        ]);

        async Task<(int Statements, TrackPlateFacts Facts)> Measure(Guid trackId)
        {
            var capture = new SqlCapture();
            await using var db = new MaviDbContext(new DbContextOptionsBuilder<MaviDbContext>()
                .UseNpgsql(fixture.ConnectionString, npgsql => npgsql.UseVector())
                .AddInterceptors(capture)
                .Options);
            var facts = await new TrackSearchRepository(db, world.Clock).GetTrackPlateFactsAsync(trackId, analysisId, default);
            return (capture.Statements.Count, facts!);
        }

        var small = await Measure(one.TrackId);
        var large = await Measure(four.TrackId);

        Assert.Single(small.Facts.Observations);
        Assert.Equal(4, large.Facts.Observations.Count);
        Assert.All(large.Facts.Observations, observation => Assert.Equal(2, observation.Readings.Count));
        Assert.Equal(["Representative", "NearView", "EarlyDiverse", "LateDiverse"],
            large.Facts.Observations.Select(observation => observation.Role.ToString()));
        Assert.Equal(5, small.Statements);
        Assert.Equal(small.Statements, large.Statements);
    }

    /// <summary>
    /// The coverage denominator is the base candidate chain decomposed for speed; for every ordinary filter
    /// it must count exactly the Vehicle Tracks the chain itself admits, per run.
    /// </summary>
    [Fact]
    public async Task TheCoverageCountEqualsTheBaseChainForEveryFilter()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var first = await world.SeedRunAsync(persons: 2, vehicles: 3);
        var second = await world.SeedRunAsync(persons: 1, vehicles: 2);
        var hidden = await world.SeedRunAsync(persons: 0, vehicles: 4, visible: false);
        await using (var db = fixture.CreateDbContext())
        {
            // A newer visible run of the first run's video supersedes it in the latest-run scope.
            var video = await db.ProcessingRuns.Where(run => run.Id == first.RunId).Select(run => run.VideoAssetId).SingleAsync();
            await db.Database.ExecuteSqlInterpolatedAsync($"UPDATE processing_runs SET video_asset_id = {video} WHERE id = {second.RunId}");
            await db.Database.ExecuteSqlInterpolatedAsync($"UPDATE tracks SET video_asset_id = {video}, mean_confidence = 0.5, duration_ms = 1000, end_offset_ms = 1000 WHERE id = {second.Track(1).TrackId}");
        }

        long snapshot;
        await using (var db = fixture.CreateDbContext())
            snapshot = await TrackPlateSearchWorld.NextSequenceAsync(db);

        var baseQuery = PlateQuery("KA01");
        TrackSearchQuery[] scopes =
        [
            baseQuery,
            baseQuery with { ProcessingRunId = first.RunId },
            baseQuery with { ProcessingRunId = hidden.RunId },
            baseQuery with { CameraId = world.CameraId },
            baseQuery with { CameraId = Guid.CreateVersion7() },
            baseQuery with { MinimumConfidence = 0.7 },
            baseQuery with { MinimumDurationMs = 2_000 },
            baseQuery with { FromUtc = Now.AddDays(1) },
            baseQuery with { ToUtc = Now.AddDays(-1) },
            baseQuery with { ObjectSubclass = "car" },
        ];

        await using var context = fixture.CreateDbContext();
        var repository = new TrackSearchRepository(context, world.Clock);
        foreach (var scope in scopes)
        {
            var expected = (await AnalyticsScopeQuery.BaseCandidates(context, AnalyticsScopeRequest.From(scope), snapshot)
                    .Where(x => x.track.ObjectClass == ObjectClass.Vehicle)
                    .Select(x => x.run.Id)
                    .ToListAsync())
                .GroupBy(id => id)
                .ToDictionary(group => group.Key, group => group.Count());
            var actual = (await repository.VehicleTracksByRunAsync(scope, snapshot))
                .ToDictionary(row => row.RunId, row => row.Tracks);
            Assert.Equal(expected.OrderBy(pair => pair.Key), actual.OrderBy(pair => pair.Key));
        }

        // The control: the filters above are not all vacuous.
        Assert.Equal(2, (await repository.VehicleTracksByRunAsync(baseQuery, snapshot)).Single().Tracks);
    }

    // --- Migration and access paths ----------------------------------------------------------------

    [Fact]
    public async Task TheSearchMigrationIsAdditiveAndRoundTrips()
    {
        await fixture.ResetDatabaseAsync();
        await using var db = fixture.CreateDbContext();
        await db.GetService<IMigrator>().MigrateAsync(PrecedingMigration);
        var before = await IndexesAsync();
        Assert.DoesNotContain(PlateSearchIndexConfiguration.TrigramIndexName, before.Keys);

        await db.Database.MigrateAsync();
        Assert.Contains(SearchMigration, await db.Database.GetAppliedMigrationsAsync());
        var after = await IndexesAsync();
        Assert.Contains("gin_trgm_ops", after[PlateSearchIndexConfiguration.TrigramIndexName], StringComparison.Ordinal);
        Assert.Contains("USING gin", after[PlateSearchIndexConfiguration.TrigramIndexName], StringComparison.Ordinal);
        Assert.Contains("text_pattern_ops", after[PlateSearchIndexConfiguration.PatternIndexName], StringComparison.Ordinal);
        Assert.Contains("USING btree", after[PlateSearchIndexConfiguration.PatternIndexName], StringComparison.Ordinal);
        Assert.NotNull(await ScalarAsync("SELECT extversion FROM pg_extension WHERE extname = 'pg_trgm'"));
        // Additive: every index that existed before is unchanged, and exactly the two search indexes are new.
        Assert.All(before, index => Assert.Equal(index.Value, after[index.Key]));
        Assert.Equal(
            new[] { PlateSearchIndexConfiguration.PatternIndexName, PlateSearchIndexConfiguration.TrigramIndexName }.Order(),
            after.Keys.Except(before.Keys).Order());

        await db.GetService<IMigrator>().MigrateAsync(PrecedingMigration);
        Assert.Equal(before, await IndexesAsync());
        await db.Database.MigrateAsync();
        Assert.Equal(after, await IndexesAsync());
    }

    /// <summary>
    /// The planner, at default settings, serves each predicate shape the repository issues from its index:
    /// contains from the trigram GIN index, prefix and exact from the pattern b-tree. Planned over a
    /// temporary copy of <c>plate_track_texts</c> with the migration's own index definitions
    /// (<c>LIKE … INCLUDING INDEXES</c>) and 200 000 analysed rows of Indian-format texts, because on a
    /// small table a sequential scan is genuinely cheaper and the planner rightly takes it. The latency
    /// budget at 10^6 rows is the measurement's question (docs/qualification/stage4), not this test's.
    /// </summary>
    [Theory]
    [InlineData("normalised_text LIKE '%KA01%'", "gin")]
    [InlineData("normalised_text LIKE 'KA01%'", "text_pattern_ops")]
    [InlineData("normalised_text = 'KA01AB1234'", "text_pattern_ops")]
    public async Task EachPredicateShapeIsServedByItsIndex(string predicate, string indexMarker)
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        // A deterministic, well-spread in-standard corpus: two letters, two digits, two letters, four digits.
        await using (var setup = new NpgsqlCommand(
            """
            CREATE TEMP TABLE plate_text_probe (LIKE plate_track_texts INCLUDING INDEXES);
            INSERT INTO plate_text_probe (analysis_id, track_id, normalised_text, support_count, max_confidence, best_plate_observation_id)
            SELECT gen_random_uuid(), gen_random_uuid(),
                   chr(65 + (i * 7) % 26) || chr(65 + (i / 26 * 11) % 26) || lpad(((i * 13) % 100)::text, 2, '0') ||
                   chr(65 + (i / 7 * 17) % 26) || chr(65 + (i / 3 * 19) % 26) || lpad(((i * 31) % 10000)::text, 4, '0'),
                   1, 0.9, gen_random_uuid()
            FROM generate_series(1, 200000) AS i;
            """, connection) { CommandTimeout = ProbeSetupTimeoutSeconds })
            await setup.ExecuteNonQueryAsync();
        // VACUUM (its own statement) flushes the GIN pending list the bulk insert filled, so the planner
        // costs the index as a steady-state index rather than as a pending-list scan, and ANALYZE gives it
        // the statistics. Without it the plan flips between runs.
        await using (var vacuum = new NpgsqlCommand("VACUUM ANALYZE plate_text_probe", connection) { CommandTimeout = ProbeSetupTimeoutSeconds })
            await vacuum.ExecuteNonQueryAsync();

        var indexes = new Dictionary<string, string>(StringComparer.Ordinal);
        await using (var list = new NpgsqlCommand("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'plate_text_probe'", connection))
        await using (var reader = await list.ExecuteReaderAsync())
        {
            while (await reader.ReadAsync()) indexes[reader.GetString(0)] = reader.GetString(1);
        }

        var expected = Assert.Single(indexes, index => index.Value.Contains(indexMarker, StringComparison.Ordinal)).Key;
        await using var explain = new NpgsqlCommand($"EXPLAIN SELECT analysis_id, track_id FROM plate_text_probe WHERE {predicate}", connection);
        var plan = string.Join("\n", await ReadAllAsync(explain));

        Assert.True(plan.Contains(expected, StringComparison.Ordinal), plan);
        Assert.DoesNotContain("Seq Scan", plan, StringComparison.Ordinal);
    }

    // --- Helpers -----------------------------------------------------------------------------------

    private static async Task CommitAnalyticsFactsAsync(SceneAnalyticsWorld world)
    {
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await lifecycle.QueueEligibleUnitsAsync(SceneAnalyticsWorld.AlgorithmVersion, SceneAnalyticsWorld.ParametersSha256, null, Now.AddDays(-1), 50, default);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity,
            new SceneAnalysisLeasePolicy(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3), default);
        Assert.True((await lifecycle.CommitFactsAsync(claim!, world.Facts(claim!.AnalysisId), default)).IsSuccess);
    }

    /// <summary>The analytic world's Track has no Observation; a plate needs a source crop.</summary>
    private async Task<Guid> AddObservationAsync(SceneAnalyticsWorld world)
    {
        await using var db = fixture.CreateDbContext();
        var observation = Observation.Create(world.TrackId, ObservationType.Representative, 0, 0, Now.AddMinutes(-30),
            0.1f, 0.1f, 0.2f, 0.2f, 0.8, 0.7, 0, 0.7);
        db.Add(observation);
        await db.SaveChangesAsync();
        return observation.Id;
    }

    private async Task<Dictionary<string, string>> IndexesAsync()
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'", connection);
        await using var reader = await command.ExecuteReaderAsync();
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        while (await reader.ReadAsync()) result[reader.GetString(0)] = reader.GetString(1);
        return result;
    }

    private async Task<object?> ScalarAsync(string sql)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        return await command.ExecuteScalarAsync();
    }

    private static async Task<List<string>> ReadAllAsync(NpgsqlCommand command)
    {
        await using var reader = await command.ExecuteReaderAsync();
        var lines = new List<string>();
        while (await reader.ReadAsync()) lines.Add(reader.GetString(0));
        return lines;
    }
}
