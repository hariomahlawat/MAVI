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
    private const string EndTimestampIndexMigration = "20261015120100_AddTrackVehicleEndTimestampIndex";

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

    /// <summary>
    /// The coverage block itself, against the authoritative base chain (cold review P2-1): Ready, Pending,
    /// Failed and Stale runs mixed, with and without a Track-level filter, and a Ready analysis whose header
    /// under-counts its run (an outcome missing). Every bucket must equal the base chain's Vehicle Tracks of
    /// runs in that state, and the fault is reported, never silently under-counted.
    /// </summary>
    [Fact]
    public async Task CoverageEqualsTheBaseChainForMixedReadinessAndFailsSafeOnAHeaderFault()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var ready = await world.SeedRunAsync(persons: 1, vehicles: 3);
        var faulty = await world.SeedRunAsync(persons: 0, vehicles: 4);
        var pending = await world.SeedRunAsync(persons: 0, vehicles: 2);
        var failed = await world.SeedRunAsync(persons: 1, vehicles: 1);
        var stale = await world.SeedRunAsync(persons: 0, vehicles: 2);
        await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, ready.RunId, Identity,
            [.. ready.Tracks.Where(track => track.ObjectClass == ObjectClass.Vehicle).Select(track => SeedPlateTrack.Analysed(track.TrackId))]);
        // The fault: published with outcomes for 2 of its 4 Vehicle Tracks, so its header says 2.
        var faultyAnalysis = await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, faulty.RunId, Identity,
            [SeedPlateTrack.Analysed(faulty.Track(0).TrackId), SeedPlateTrack.Analysed(faulty.Track(1).TrackId)]);
        await TrackPlateSearchWorld.QueueAsync(fixture.CreateDbContext, Now, failed.RunId, Identity, failed: true);
        await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, stale.RunId, TrackPlateSearchWorld.Obsolete(Identity),
            [.. stale.Tracks.Select(track => SeedPlateTrack.Analysed(track.TrackId))], preferred: false);
        var state = new Dictionary<Guid, string>
        {
            [ready.RunId] = "ready", [faulty.RunId] = "ready", [pending.RunId] = "pending", [failed.RunId] = "failed", [stale.RunId] = "stale",
        };

        foreach (var query in new[] { PlateQuery("KA01"), PlateQuery("KA01") with { FromUtc = Now.AddDays(-1) }, PlateQuery("KA01") with { ToUtc = Now.AddDays(-1) } })
        {
            var page = (await new TrackSearchRepository(fixture.CreateDbContext(), world.Clock)
                .SearchPlatesAsync(query, Identity.Fingerprint, null, 51, default)).Page!;

            long snapshot = page.SnapshotVisibilitySequence;
            await using var db = fixture.CreateDbContext();
            var authoritative = (await AnalyticsScopeQuery.BaseCandidates(db, AnalyticsScopeRequest.From(query), snapshot)
                    .Where(x => x.track.ObjectClass == ObjectClass.Vehicle)
                    .Select(x => x.run.Id)
                    .ToListAsync())
                .GroupBy(id => state[id])
                .ToDictionary(group => group.Key, group => group.Count());
            var coverage = page.PlateCoverage;
            Assert.Equal(authoritative.GetValueOrDefault("ready"), coverage.Ready);
            Assert.Equal(authoritative.GetValueOrDefault("pending"), coverage.Pending);
            Assert.Equal(authoritative.GetValueOrDefault("failed"), coverage.Failed);
            Assert.Equal(authoritative.GetValueOrDefault("stale"), coverage.Stale);
            Assert.Equal(0, coverage.NotConfigured);
            Assert.Equal(authoritative.Values.Sum(), coverage.VehicleTracksInScope);

            if (query.ToUtc is null && query.FromUtc is null)
            {
                Assert.Equal(7, coverage.Ready);
                var fault = Assert.Single(page.IntegrityFaults!);
                Assert.Equal(new PlateCoverageIntegrityFault(faultyAnalysis, faulty.RunId, 2, 4), fault);
            }
        }

        // Not configured: every Vehicle Track of the scope, by the same authoritative count.
        var unconfigured = (await new TrackSearchRepository(fixture.CreateDbContext(), world.Clock)
            .SearchPlatesAsync(PlateQuery("KA01"), null, null, 51, default)).Page!.PlateCoverage;
        Assert.Equal(12, unconfigured.NotConfigured);
        Assert.Equal(12, unconfigured.VehicleTracksInScope);
    }

    // --- Page strategies ---------------------------------------------------------------------------

    /// <summary>
    /// The candidate read (ADR-018) returns exactly the plate predicate's rows in page order, across every
    /// page (cold review P1-1). The batch sizes are shrunk to 2 and 4 so a 24-Track corpus, whose Tracks all
    /// start at the same instant (ordered by id alone), drives one page across several candidate batches: a text
    /// matching most Tracks, one matching two old Tracks, one matching five Tracks spread out, prefix, exact and
    /// no match. (Before ADR-018 the same cases drove the walk, the sparse path and its overflow.)
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
                    FirstCandidateBatch = 2,
                    MaximumCandidateBatch = 4,
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

    /// <summary>
    /// The candidate read (ADR-018) against the pre-optimisation semantics, verbatim: the plan §2.8 correlated
    /// EXISTS over <c>plate_track_texts</c> for a visible analysis of the pinned identity of the Track's own run,
    /// ANDed with the base chain and ordered <c>StartTimestampUtc DESC, Id DESC</c>, evaluated as LINQ at the
    /// first page's snapshot. Every page of every page size must concatenate to exactly that sequence, for
    /// contains, prefix and exact, under ordinary filters (confidence, a window on either bound, a run, a camera)
    /// and with: Tracks holding two matching texts; a superseded analysis (still fact-bearing for its pinned
    /// identity); a run analysed only under another identity; a hidden run; equal start times (ordered by id);
    /// start times changed after publication (carried by the trigger); and an analysis published after the
    /// first page's snapshot, which no continuation of that result set may admit. Batches are shrunk to 2 and 4
    /// so a page spans several candidate batches.
    /// </summary>
    [Theory]
    [InlineData("AB0", TrackPlateMatch.Contains)]
    [InlineData("KA01", TrackPlateMatch.Prefix)]
    [InlineData("MH12", TrackPlateMatch.Contains)]
    [InlineData("KA02AB0008", TrackPlateMatch.Exact)]
    [InlineData("ZZZ", TrackPlateMatch.Contains)]
    public async Task TheCandidateReadEqualsThePreOptimisationPredicate(string text, TrackPlateMatch match)
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var older = Identity with { Fingerprint = new string('c', 64) };
        var current = await world.SeedRunAsync(persons: 1, vehicles: 6);
        var superseded = await world.SeedRunAsync(persons: 0, vehicles: 5);
        var otherIdentity = await world.SeedRunAsync(persons: 0, vehicles: 4);
        var hidden = await world.SeedRunAsync(persons: 0, vehicles: 3, visible: false);
        var late = await world.SeedRunAsync(persons: 0, vehicles: 4);

        var position = 0;
        SeedPlateTrack[] Texts(SeededRun run) =>
        [
            .. run.Tracks.Where(track => track.ObjectClass == ObjectClass.Vehicle).Select(track =>
            {
                position++;
                var first = $"KA{position % 3:00}AB{position:0000}";
                // Every third Track has a second distinct text, so it is a candidate twice.
                return position % 3 == 0
                    ? SeedPlateTrack.Analysed(track.TrackId,
                        new SeedPlate(track.Observations[0].ObservationId, 0.9, (first, 0.9)),
                        new SeedPlate(track.Observations[0].ObservationId, 0.8, ($"MH12ZZ{position:0000}", 0.8)))
                    : SeedPlateTrack.Analysed(track.TrackId, new SeedPlate(track.Observations[0].ObservationId, 0.9, (first, 0.9)));
            }),
        ];

        await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, current.RunId, Identity, Texts(current));
        var supersededAnalysis = await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, superseded.RunId, Identity, Texts(superseded));
        await TrackPlateSearchWorld.SupersedeAsync(fixture.CreateDbContext, supersededAnalysis);
        await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, otherIdentity.RunId, older, Texts(otherIdentity));
        await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, hidden.RunId, Identity, Texts(hidden));
        var lateTexts = Texts(late);

        // Distinct start (and end) times across runs and Tracks, with deliberate ties, set after publication so
        // the trigger on tracks must carry them; confidence, duration and subclass varied for their filters (the
        // subclass with the approved source, with another detector's source, or none).
        var vehicles = new[] { current, superseded, otherIdentity, hidden, late }
            .SelectMany(run => run.Tracks.Where(track => track.ObjectClass == ObjectClass.Vehicle))
            .ToList();
        DateTimeOffset StartOf(int index) => Now.AddHours(-10).AddMinutes(17 * ((index * 7) % vehicles.Count / 2));
        long DurationOf(int index) => index % 3 == 0 ? 2_000 : 4_000;
        await using (var db = fixture.CreateDbContext())
        {
            for (var index = 0; index < vehicles.Count; index++)
            {
                var start = StartOf(index);
                var duration = DurationOf(index);
                var confidence = index % 4 == 0 ? 0.5 : 0.8;
                var (subclass, vocabulary, source) = (index % 5) switch
                {
                    0 => ("car", "mavi-vehicle-subclass-v1", VehicleSubclassExposurePolicy.ApprovedSource),
                    1 => ("car", "mavi-vehicle-subclass-v1", VehicleSubclass.DetectorNativeSourcePrefix + new string('e', 64)),
                    _ => ((string?)null, (string?)null, (string?)null),
                };
                await db.Database.ExecuteSqlInterpolatedAsync(
                    $"""
                    UPDATE tracks SET start_timestamp_utc = {start}, end_timestamp_utc = {start.AddMilliseconds(duration)},
                        start_offset_ms = 0, end_offset_ms = {duration}, duration_ms = {duration}, mean_confidence = {confidence},
                        object_subclass = {subclass}, object_subclass_vocabulary = {vocabulary}, object_subclass_source = {source}
                    WHERE id = {vehicles[index].TrackId}
                    """);
            }
        }

        Assert.Equal(0, await TrackStartDriftAsync());

        // Boundary values taken from the corpus itself: a Track's exact start (an exclusive upper bound must drop
        // it and its ties), a Track's exact end (an inclusive lower bound must keep it), the exact confidence and
        // duration two classes of Tracks hold (inclusive), and thresholds that reject every Track (cold review
        // P1-2: these predicates are now also pushed into the candidate statement and must stay exact).
        var boundaryStart = StartOf(5);
        var boundaryEnd = StartOf(7).AddMilliseconds(DurationOf(7));
        var baseQuery = PlateQuery(text, match);
        TrackSearchQuery[] queries =
        [
            baseQuery,
            baseQuery with { MinimumConfidence = 0.7 },
            baseQuery with { MinimumConfidence = 0.8 },
            baseQuery with { MinimumConfidence = 0.95 },
            baseQuery with { FromUtc = Now.AddHours(-9) },
            baseQuery with { FromUtc = boundaryEnd },
            baseQuery with { ToUtc = Now.AddHours(-8) },
            baseQuery with { ToUtc = boundaryStart },
            baseQuery with { FromUtc = boundaryEnd, ToUtc = boundaryStart.AddHours(2) },
            baseQuery with { MinimumDurationMs = 4_000 },
            baseQuery with { MinimumDurationMs = 2_001 },
            baseQuery with { MinimumDurationMs = 4_001 },
            baseQuery with { ObjectSubclass = "car" },
            baseQuery with { ToUtc = boundaryStart, MinimumConfidence = 0.7, MinimumDurationMs = 4_000 },
            baseQuery with { ProcessingRunId = superseded.RunId },
            baseQuery with { CameraId = world.CameraId },
        ];

        var lateAnalysis = (Guid?)null;
        var everNonEmpty = false;
        var unfiltered = 0;
        var narrowedButNotEmpty = false;
        foreach (var query in queries)
        {
            foreach (var limit in new[] { 1, 3, 50 })
            {
                var seen = new List<Guid>();
                TrackPlateSearchRepositoryPage? first = null;
                TrackCursorPosition? keyset = null;
                while (true)
                {
                    var repository = new TrackSearchRepository(fixture.CreateDbContext(), world.Clock)
                    {
                        FirstCandidateBatch = 2,
                        MaximumCandidateBatch = 4,
                    };
                    var cursor = keyset is null
                        ? null
                        : new TrackPlateCursorPosition(keyset, Identity.Fingerprint, first!.PlateCoverage);
                    var page = (await repository.SearchPlatesAsync(query, Identity.Fingerprint, cursor, limit + 1, default)).Page!;
                    first ??= page;
                    var rows = page.Items.Take(limit).ToList();
                    seen.AddRange(rows.Select(row => row.Id));
                    Assert.Equal(rows.Count, rows.Count(row => page.ItemPlates.ContainsKey(row.Id)));

                    // Published after the first page's snapshot: the continuation must not admit it.
                    lateAnalysis ??= await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, late.RunId, Identity, lateTexts);

                    if (page.Items.Count <= limit) break;
                    keyset = new TrackCursorPosition(first.SnapshotUtc, first.SnapshotVisibilitySequence,
                        rows[^1].StartTimestampUtc, rows[^1].Id, new string('a', 64));
                }

                await using var oracle = fixture.CreateDbContext();
                var expected = await PreOptimisationOrderAsync(oracle, query, Identity.Fingerprint, first!.SnapshotVisibilitySequence);
                everNonEmpty |= expected.Count > 0;
                if (text != "ZZZ" && query == baseQuery)
                    unfiltered = expected.Count;
                if (text != "ZZZ" && query != baseQuery && query.ProcessingRunId is null && query.CameraId is null &&
                    query.MinimumConfidence is not 0.95 && query.MinimumDurationMs is not 4_001)
                    narrowedButNotEmpty |= expected.Count > 0 && expected.Count < unfiltered;
                Assert.True(expected.SequenceEqual(seen),
                    $"{text} {match} limit {limit} {QueryLabel(query)}: expected [{string.Join(",", expected)}], got [{string.Join(",", seen)}]");
            }
        }

        // The control: the corpus is not vacuous for the texts that should match, and the Track filters both keep
        // and drop matches on it (so a filter applied too strictly, or not at all, would be seen).
        Assert.Equal(text != "ZZZ", everNonEmpty);
        Assert.Equal(text != "ZZZ" && text != "KA02AB0008", narrowedButNotEmpty);
        Assert.Equal(0, await TrackStartDriftAsync());
    }

    /// <summary>
    /// Cold review P1-2, regression: a historical upper time bound, or a Track filter that rejects nearly every
    /// match, no longer spends candidate batches on Tracks the base chain certainly rejects. Twelve matching Tracks
    /// an hour apart, batches shrunk to 2: before the predicates were pushed into the candidate statement, reaching
    /// the oldest Track took six batches; now one candidate statement returns exactly the Tracks the base chain
    /// keeps, and the page is the same.
    /// </summary>
    [Fact]
    public async Task AHistoricalWindowOrARejectingFilterReadsOneCandidateBatch()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await world.SeedRunAsync(persons: 0, vehicles: 12);
        await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, run.RunId, Identity,
        [
            .. run.Tracks.Select((track, position) => SeedPlateTrack.Analysed(track.TrackId,
                new SeedPlate(track.Observations[0].ObservationId, 0.9, ($"KA01AB{position:0000}", 0.9)))),
        ]);
        for (var index = 0; index < run.Tracks.Count; index++)
        {
            // Track 0 is the newest; Track 11, the oldest, alone has a high mean confidence.
            await ExecuteAsync(
                "UPDATE tracks SET start_timestamp_utc = $1, end_timestamp_utc = $2, mean_confidence = $3 WHERE id = $4",
                Now.AddHours(-index), Now.AddHours(-index).AddSeconds(4), index == 11 ? 0.97 : 0.8, run.Track(index).TrackId);
        }

        async Task<(List<Guid> Rows, int CandidateStatements)> Search(TrackSearchQuery query)
        {
            var capture = new SqlCapture();
            await using var db = new MaviDbContext(new DbContextOptionsBuilder<MaviDbContext>()
                .UseNpgsql(fixture.ConnectionString, npgsql => npgsql.UseVector())
                .AddInterceptors(capture)
                .Options);
            var repository = new TrackSearchRepository(db, world.Clock) { FirstCandidateBatch = 2, MaximumCandidateBatch = 2 };
            var page = (await repository.SearchPlatesAsync(query, Identity.Fingerprint, null, 51, default)).Page!;
            return ([.. page.Items.Select(row => row.Id)], CandidateStatements(capture));
        }

        var oldest = run.Track(11).TrackId;
        var historical = await Search(PlateQuery("KA01") with { ToUtc = Now.AddHours(-10.5) });
        Assert.Equal([oldest], historical.Rows);
        Assert.Equal(1, historical.CandidateStatements);

        var selective = await Search(PlateQuery("KA01") with { MinimumConfidence = 0.95 });
        Assert.Equal([oldest], selective.Rows);
        Assert.Equal(1, selective.CandidateStatements);

        var rejectAll = await Search(PlateQuery("KA01") with { MinimumConfidence = 0.99 });
        Assert.Empty(rejectAll.Rows);
        Assert.Equal(1, rejectAll.CandidateStatements);

        // The control: unfiltered, the same corpus needs every batch (12 matches, batches of 2, then the empty one).
        var unfiltered = await Search(PlateQuery("KA01"));
        Assert.Equal(12, unfiltered.Rows.Count);
        Assert.Equal(7, unfiltered.CandidateStatements);
    }

    /// <summary>
    /// Cold review P2-1: when the pinned analytic half provably matches nothing — no fact-bearing unit for the
    /// pinned identity (zero evaluated runs), analytics disabled on the revision, or a camera never configured —
    /// the combined search returns the empty page with both coverage blocks and reads no plate candidate batch,
    /// on the first page and on a continuation. The control (facts committed) reads a batch and matches.
    /// </summary>
    [Fact]
    public async Task ACombinedSearchWhoseAnalyticHalfCannotMatchReadsNoPlateCandidate()
    {
        async Task<SceneAnalyticsWorld> World(bool analyticsEnabled, bool commitFacts)
        {
            var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now, analyticsEnabled);
            await using (var db = fixture.CreateDbContext())
                await db.Database.ExecuteSqlInterpolatedAsync($"UPDATE tracks SET object_class = 'Vehicle' WHERE id = {world.TrackId}");
            if (commitFacts)
                await CommitAnalyticsFactsAsync(world);
            var observation = await AddObservationAsync(world);
            await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, world.RunId, Identity,
                [SeedPlateTrack.Analysed(world.TrackId, new SeedPlate(observation, 0.9, ("KA01AB1234", 0.9)))]);
            return world;
        }

        async Task<(TrackPlateSearchRepositoryPage Page, int CandidateStatements)> Search(
            MutableTimeProvider clock, TrackSearchQuery query, TrackPlateCursorPosition? cursor = null)
        {
            var capture = new SqlCapture();
            await using var db = new MaviDbContext(new DbContextOptionsBuilder<MaviDbContext>()
                .UseNpgsql(fixture.ConnectionString, npgsql => npgsql.UseVector())
                .AddInterceptors(capture)
                .Options);
            var page = (await new TrackSearchRepository(db, clock)
                .SearchPlatesAsync(query, cursor is null ? Identity.Fingerprint : null, cursor, 51, default)).Page!;
            return (page, CandidateStatements(capture));
        }

        // The control: facts committed, so both halves can match.
        var control = await World(analyticsEnabled: true, commitFacts: true);
        var zone = TrackAnalyticsQuery.Empty with { ZoneId = control.ZoneId };
        var matched = await Search(control.Clock, PlateQuery("KA01") with { CameraId = control.CameraId, Analytics = zone });
        Assert.Equal(control.TrackId, Assert.Single(matched.Page.Items).Id);
        Assert.Equal(1, matched.CandidateStatements);

        // Zero evaluated runs: the run's unit was never computed for the pinned identity.
        var unevaluated = await World(analyticsEnabled: true, commitFacts: false);
        var pendingQuery = PlateQuery("KA01") with { CameraId = unevaluated.CameraId, Analytics = zone with { ZoneId = unevaluated.ZoneId } };
        var pending = await Search(unevaluated.Clock, pendingQuery);
        Assert.Empty(pending.Page.Items);
        Assert.Equal(0, pending.CandidateStatements);
        Assert.Equal(0, pending.Page.AnalyticsCoverage!.EvaluatedRuns);
        Assert.Equal(1, pending.Page.AnalyticsCoverage.PendingRuns);
        Assert.Equal(1, pending.Page.PlateCoverage.Ready);
        Assert.NotNull(pending.Page.AnalyticsIdentity);
        var continuation = await Search(unevaluated.Clock, pendingQuery, new TrackPlateCursorPosition(
            new TrackCursorPosition(pending.Page.SnapshotUtc, pending.Page.SnapshotVisibilitySequence, Now.AddHours(1), Guid.CreateVersion7(), new string('a', 64)),
            Identity.Fingerprint, pending.Page.PlateCoverage, pending.Page.AnalyticsIdentity, pending.Page.AnalyticsCoverage));
        Assert.Empty(continuation.Page.Items);
        Assert.Equal(0, continuation.CandidateStatements);
        Assert.Equal(pending.Page.AnalyticsCoverage, continuation.Page.AnalyticsCoverage);

        // Analytics disabled on the resolved revision.
        var disabled = await World(analyticsEnabled: false, commitFacts: false);
        var off = await Search(disabled.Clock, PlateQuery("KA01") with { CameraId = disabled.CameraId, Analytics = TrackAnalyticsQuery.Empty with { Loitering = true } });
        Assert.Empty(off.Page.Items);
        Assert.Equal(0, off.CandidateStatements);
        Assert.Equal(1, off.Page.AnalyticsCoverage!.DisabledRuns);
        Assert.Equal(1, off.Page.PlateCoverage.Ready);

        // A camera that was never configured: no revision to evaluate against.
        using var unconfigured = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await unconfigured.SeedRunAsync(persons: 0, vehicles: 1);
        await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, run.RunId, Identity,
            [SeedPlateTrack.Analysed(run.Track(0).TrackId, new SeedPlate(run.Track(0).Observations[0].ObservationId, 0.9, ("KA01AB1234", 0.9)))]);
        var none = await Search(unconfigured.Clock, PlateQuery("KA01") with { CameraId = unconfigured.CameraId, Analytics = TrackAnalyticsQuery.Empty with { Loitering = true } });
        Assert.Empty(none.Page.Items);
        Assert.Equal(0, none.CandidateStatements);
        Assert.Equal(1, none.Page.AnalyticsCoverage!.NotConfiguredRuns);
        Assert.Equal(1, none.Page.PlateCoverage.Ready);
        // Without the analytic predicate the same plate query matches: the plate half was never the reason.
        Assert.Single((await Search(unconfigured.Clock, PlateQuery("KA01") with { CameraId = unconfigured.CameraId })).Page.Items);
    }

    /// <summary>
    /// ADR-018 hardening (cold review P3; migration <c>LockTrackForPlateTextTrackStart</c>): the derivation of a text's
    /// Track start cannot race a concurrent change of that start. Two connections, explicit ordering, both orders:
    /// a text inserted while an uncommitted Track update holds the row waits for it and derives the new start; a Track
    /// update issued while an uncommitted text insert holds the row waits for it, and its carry trigger then updates
    /// the committed text. Without the <c>FOR SHARE</c> lock neither wait happens and the first order commits drift.
    /// </summary>
    [Fact]
    public async Task TheTrackStartDerivationCannotRaceAConcurrentTrackStartChange()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await world.SeedRunAsync(persons: 0, vehicles: 3);
        var analysisId = await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, run.RunId, Identity,
            [SeedPlateTrack.Analysed(run.Track(0).TrackId, new SeedPlate(run.Track(0).Observations[0].ObservationId, 0.9, ("KA01AB1234", 0.9)))]);
        var plateId = await ScalarAsync($"SELECT best_plate_observation_id FROM plate_track_texts WHERE analysis_id = '{analysisId}' LIMIT 1");
        Assert.Contains(" FOR SHARE", (string)(await ScalarAsync("SELECT prosrc FROM pg_proc WHERE proname = 'plate_track_texts_derive_track_start'"))!,
            StringComparison.Ordinal);

        async Task<NpgsqlConnection> Open()
        {
            var connection = new NpgsqlConnection(fixture.ConnectionString);
            await connection.OpenAsync();
            return connection;
        }

        static async Task Run(NpgsqlConnection connection, string sql, params object[] parameters)
        {
            await using var command = new NpgsqlCommand(sql, connection);
            foreach (var parameter in parameters) command.Parameters.AddWithValue(parameter);
            await command.ExecuteNonQueryAsync();
        }

        static async Task<int> Pid(NpgsqlConnection connection)
        {
            await using var command = new NpgsqlCommand("SELECT pg_backend_pid()", connection);
            return (int)(await command.ExecuteScalarAsync())!;
        }

        // Deterministic: the other backend is observed waiting on a lock, not merely assumed slow.
        async Task AwaitLockWait(int pid, Task statement)
        {
            var deadline = DateTime.UtcNow.AddSeconds(20);
            while (true)
            {
                Assert.False(statement.IsCompleted, "the statement did not wait for the Track row lock");
                if (await CountAsync("SELECT count(*) FROM pg_stat_activity WHERE pid = $1 AND wait_event_type = 'Lock'", pid) == 1)
                    return;
                Assert.True(DateTime.UtcNow < deadline, "the statement never waited on a lock");
                await Task.Delay(25);
            }
        }

        const string InsertOutcome =
            "INSERT INTO plate_track_outcomes (analysis_id, track_id, outcome, reason, plate_observation_count, distinct_text_count) VALUES ($1, $2, 'Analysed', NULL, 0, 0)";
        const string InsertText =
            "INSERT INTO plate_track_texts (analysis_id, track_id, normalised_text, support_count, max_confidence, best_plate_observation_id) VALUES ($1, $2, $3, 1, 0.9, $4)";

        // Order 1: the Track update holds the row first; the text insert must wait and derive the new start.
        var first = run.Track(1).TrackId;
        var movedFirst = Now.AddDays(-5);
        await using (var updater = await Open())
        await using (var inserter = await Open())
        {
            var inserterPid = await Pid(inserter);
            var update = await updater.BeginTransactionAsync();
            Task? pending = null;
            try
            {
                await Run(updater, "UPDATE tracks SET start_timestamp_utc = $1 WHERE id = $2", movedFirst, first);
                await using var insert = await inserter.BeginTransactionAsync();
                await Run(inserter, InsertOutcome, analysisId, first);
                pending = Run(inserter, InsertText, analysisId, first, "KA01ZZ0001", plateId!);
                await AwaitLockWait(inserterPid, pending);
                await update.CommitAsync();
                await pending;
                await insert.CommitAsync();
            }
            finally
            {
                // On a failure, release the lock holder first so the waiting connection can be disposed.
                await update.DisposeAsync();
                if (pending is not null) await Task.WhenAny(pending, Task.Delay(TimeSpan.FromSeconds(30)));
            }
        }

        Assert.Equal(1L, await CountAsync(
            "SELECT count(*) FROM plate_track_texts WHERE track_id = $1 AND track_start_timestamp_utc = $2", first, movedFirst));
        Assert.Equal(0, await TrackStartDriftAsync());

        // Order 2: the text insert holds the row first; the Track update must wait, then carry its start to the
        // now-committed text.
        var second = run.Track(2).TrackId;
        var movedSecond = Now.AddDays(-6);
        await using (var inserter = await Open())
        await using (var updater = await Open())
        {
            var updaterPid = await Pid(updater);
            var insert = await inserter.BeginTransactionAsync();
            Task? pending = null;
            try
            {
                await Run(inserter, InsertOutcome, analysisId, second);
                await Run(inserter, InsertText, analysisId, second, "KA01ZZ0002", plateId!);
                await using var update = await updater.BeginTransactionAsync();
                pending = Run(updater, "UPDATE tracks SET start_timestamp_utc = $1 WHERE id = $2", movedSecond, second);
                await AwaitLockWait(updaterPid, pending);
                await insert.CommitAsync();
                await pending;
                await update.CommitAsync();
            }
            finally
            {
                await insert.DisposeAsync();
                if (pending is not null) await Task.WhenAny(pending, Task.Delay(TimeSpan.FromSeconds(30)));
            }
        }

        Assert.Equal(1L, await CountAsync(
            "SELECT count(*) FROM plate_track_texts WHERE track_id = $1 AND track_start_timestamp_utc = $2", second, movedSecond));
        Assert.Equal(0, await TrackStartDriftAsync());
    }

    /// <summary>
    /// The lock migration only replaces the derivation function: Down restores the 2026-10-15 body (no lock), Up
    /// puts the lock back, and the column, its values and both triggers are untouched either way.
    /// </summary>
    [Fact]
    public async Task TheTrackRowLockMigrationOnlyReplacesTheDerivationFunction()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await world.SeedRunAsync(persons: 0, vehicles: 2);
        await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, run.RunId, Identity,
        [
            .. run.Tracks.Select((track, position) => SeedPlateTrack.Analysed(track.TrackId,
                new SeedPlate(track.Observations[0].ObservationId, 0.9, ($"KA01AB{position:0000}", 0.9)))),
        ]);
        const string Body = "SELECT prosrc FROM pg_proc WHERE proname = 'plate_track_texts_derive_track_start'";
        const string Triggers = "SELECT count(*) FROM pg_trigger WHERE tgname IN ('tr_plate_track_texts_track_start', 'tr_tracks_plate_text_track_start')";
        var texts = await CountAsync("SELECT count(*) FROM plate_track_texts");

        await using var db = fixture.CreateDbContext();
        Assert.False(db.Database.HasPendingModelChanges(), "the model snapshot does not match the model");
        var migrator = db.GetService<IMigrator>();
        Assert.Contains(" FOR SHARE", (string)(await ScalarAsync(Body))!, StringComparison.Ordinal);

        await migrator.MigrateAsync(EndTimestampIndexMigration);
        Assert.DoesNotContain("FOR SHARE", (string)(await ScalarAsync(Body))!, StringComparison.Ordinal);
        Assert.Equal(2L, await CountAsync(Triggers));
        Assert.Equal(texts, await CountAsync("SELECT count(*) FROM plate_track_texts"));
        Assert.Equal(0, await TrackStartDriftAsync());

        await migrator.MigrateAsync();
        Assert.Contains(" FOR SHARE", (string)(await ScalarAsync(Body))!, StringComparison.Ordinal);
        Assert.Equal(2L, await CountAsync(Triggers));
        Assert.Equal(texts, await CountAsync("SELECT count(*) FROM plate_track_texts"));
        Assert.Equal(0, await TrackStartDriftAsync());
    }

    /// <summary>
    /// The denormalised Track start (ADR-018) is the database's, never the application's: derived on insert
    /// (here, EF's insert; PR-3's COPY publication is checked by <c>PlateCompletionTimingTests</c>), re-derived
    /// when a text is updated whatever value is supplied, carried to the texts when the Track's start changes,
    /// and a text whose Track is not of its analysis's run is refused.
    /// </summary>
    [Fact]
    public async Task TheTrackStartIsDerivedAndCarriedByTheDatabase()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var run = await world.SeedRunAsync(persons: 0, vehicles: 2);
        var other = await world.SeedRunAsync(persons: 0, vehicles: 1);
        var analysisId = await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, run.RunId, Identity,
        [
            SeedPlateTrack.Analysed(run.Track(0).TrackId,
                new SeedPlate(run.Track(0).Observations[0].ObservationId, 0.9, ("KA01AB1234", 0.9)),
                new SeedPlate(run.Track(0).Observations[0].ObservationId, 0.8, ("KA01AB1284", 0.8))),
            SeedPlateTrack.Analysed(run.Track(1).TrackId, new SeedPlate(run.Track(1).Observations[0].ObservationId, 0.9, ("MH12DE4321", 0.9))),
        ]);

        // Derived on insert: the same instant as the Track's own start, for every text.
        await using (var db = fixture.CreateDbContext())
        {
            var texts = await db.PlateTrackTexts.AsNoTracking()
                .Where(text => text.AnalysisId == analysisId)
                .Select(text => new { text.TrackId, Start = EF.Property<DateTimeOffset>(text, PlateSearchIndexConfiguration.TrackStartProperty) })
                .ToListAsync();
            Assert.Equal(3, texts.Count);
            var starts = await db.Tracks.AsNoTracking().Where(track => track.ProcessingRunId == run.RunId)
                .ToDictionaryAsync(track => track.Id, track => track.StartTimestampUtc);
            Assert.All(texts, text => Assert.Equal(starts[text.TrackId], text.Start));
        }

        Assert.Equal(0, await TrackStartDriftAsync());

        // A supplied value never survives: the trigger re-derives it.
        await ExecuteAsync("UPDATE plate_track_texts SET track_start_timestamp_utc = '2000-01-01T00:00:00Z' WHERE analysis_id = $1", analysisId);
        Assert.Equal(0, await TrackStartDriftAsync());

        // A changed Track start is carried to that Track's texts (and only to them) in the same statement.
        var moved = Now.AddDays(-3);
        await ExecuteAsync("UPDATE tracks SET start_timestamp_utc = $1 WHERE id = $2", moved, run.Track(0).TrackId);
        Assert.Equal(0, await TrackStartDriftAsync());
        Assert.Equal(2L, await CountAsync(
            "SELECT count(*) FROM plate_track_texts WHERE track_id = $1 AND track_start_timestamp_utc = $2", run.Track(0).TrackId, moved));
        Assert.Equal(0L, await CountAsync(
            "SELECT count(*) FROM plate_track_texts WHERE track_id = $1 AND track_start_timestamp_utc = $2", run.Track(1).TrackId, moved));

        // A text naming a Track of another run than its analysis's is refused (the candidate read relies on it).
        var plateId = await ScalarAsync($"SELECT best_plate_observation_id FROM plate_track_texts WHERE analysis_id = '{analysisId}' LIMIT 1");
        await ExecuteAsync(
            "INSERT INTO plate_track_outcomes (analysis_id, track_id, outcome, reason, plate_observation_count, distinct_text_count) VALUES ($1, $2, 'Analysed', NULL, 0, 0)",
            analysisId, other.Track(0).TrackId);
        var refused = await Assert.ThrowsAsync<PostgresException>(() => ExecuteAsync(
            "INSERT INTO plate_track_texts (analysis_id, track_id, normalised_text, support_count, max_confidence, best_plate_observation_id) VALUES ($1, $2, 'KA01ZZ0001', 1, 0.9, $3)",
            analysisId, other.Track(0).TrackId, plateId!));
        Assert.Equal(PostgresErrorCodes.CheckViolation, refused.SqlState);
        Assert.Equal("tr_plate_track_texts_track_start", refused.ConstraintName);
    }

    /// <summary>
    /// The sort-key migration over an existing populated database (ADR-018): Down to the search indexes removes
    /// the column, triggers and functions and keeps every fact row; a corrupt text (a Track of another run) makes
    /// Up fail atomically; Up then backfills every text from <c>tracks</c>, NOT NULL, with both triggers and the
    /// (b) index (ADR-019) in place, and the model snapshot matches the model.
    /// </summary>
    [Fact]
    public async Task TheTrackStartMigrationBackfillsAPopulatedDatabaseAndRoundTrips()
    {
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var runs = new List<SeededRun>();
        for (var index = 0; index < 3; index++)
        {
            var run = await world.SeedRunAsync(persons: 1, vehicles: 4);
            runs.Add(run);
            await TrackPlateSearchWorld.PublishAsync(fixture.CreateDbContext, Now, run.RunId, Identity,
            [
                .. run.Tracks.Where(track => track.ObjectClass == ObjectClass.Vehicle).Select((track, position) => SeedPlateTrack.Analysed(track.TrackId,
                    new SeedPlate(track.Observations[0].ObservationId, 0.9, ($"KA{index:00}AB{position:0000}", 0.9)))),
            ]);
            await ExecuteAsync("UPDATE tracks SET start_timestamp_utc = start_timestamp_utc - make_interval(mins => $1) WHERE processing_run_id = $2",
                index * 37, run.RunId);
        }

        const string Keys = "SELECT count(*) FROM plate_track_texts";
        var texts = await CountAsync(Keys);
        Assert.Equal(12L, texts);

        await using var db = fixture.CreateDbContext();
        Assert.False(db.Database.HasPendingModelChanges(), "the model snapshot does not match the model");
        var migrator = db.GetService<IMigrator>();
        await migrator.MigrateAsync(SearchMigration);
        Assert.Equal(0L, await CountAsync(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'plate_track_texts' AND column_name = 'track_start_timestamp_utc'"));
        Assert.Equal(0L, await CountAsync(
            "SELECT count(*) FROM pg_trigger WHERE tgname IN ('tr_plate_track_texts_track_start', 'tr_tracks_plate_text_track_start')"));
        Assert.Equal(0L, await CountAsync(
            "SELECT count(*) FROM pg_proc WHERE proname IN ('plate_track_texts_derive_track_start', 'tracks_carry_plate_text_track_start')"));
        Assert.DoesNotContain(TrackConfiguration.EndTimestampIndexName, (await IndexesAsync()).Keys);
        Assert.Equal(texts, await CountAsync(Keys));

        // A text whose Track is of another run than its analysis's: Up refuses the database, atomically.
        var analysis = (Guid)(await ScalarAsync($"SELECT id FROM plate_analyses WHERE processing_run_id = '{runs[0].RunId}'"))!;
        var foreign = runs[1].Tracks.First(track => track.ObjectClass == ObjectClass.Vehicle).TrackId;
        var plate = (Guid)(await ScalarAsync($"SELECT best_plate_observation_id FROM plate_track_texts WHERE analysis_id = '{analysis}' LIMIT 1"))!;
        await ExecuteAsync(
            "INSERT INTO plate_track_outcomes (analysis_id, track_id, outcome, reason, plate_observation_count, distinct_text_count) VALUES ($1, $2, 'Analysed', NULL, 0, 0)",
            analysis, foreign);
        await ExecuteAsync(
            "INSERT INTO plate_track_texts (analysis_id, track_id, normalised_text, support_count, max_confidence, best_plate_observation_id) VALUES ($1, $2, 'KA99ZZ0001', 1, 0.9, $3)",
            analysis, foreign, plate);
        var refused = await Assert.ThrowsAsync<PostgresException>(() => migrator.MigrateAsync());
        Assert.Contains("another run", refused.MessageText, StringComparison.Ordinal);
        Assert.Equal(0L, await CountAsync(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'plate_track_texts' AND column_name = 'track_start_timestamp_utc'"));
        await ExecuteAsync("DELETE FROM plate_track_texts WHERE analysis_id = $1 AND track_id = $2", analysis, foreign);
        await ExecuteAsync("DELETE FROM plate_track_outcomes WHERE analysis_id = $1 AND track_id = $2", analysis, foreign);

        await migrator.MigrateAsync();
        Assert.Equal(texts, await CountAsync(Keys));
        Assert.Equal(0, await TrackStartDriftAsync());
        Assert.Equal("NO", await ScalarAsync(
            "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'plate_track_texts' AND column_name = 'track_start_timestamp_utc'"));
        Assert.Equal(2L, await CountAsync(
            "SELECT count(*) FROM pg_trigger WHERE tgname IN ('tr_plate_track_texts_track_start', 'tr_tracks_plate_text_track_start')"));
        Assert.Contains("USING btree (object_class, end_timestamp_utc)", (await IndexesAsync())[TrackConfiguration.EndTimestampIndexName],
            StringComparison.Ordinal);

        // The run starts were moved before the migration: the backfill took each Track's own start.
        Assert.Equal(3L, await CountAsync("SELECT count(DISTINCT track_start_timestamp_utc) FROM plate_track_texts"));
    }

    // --- Query shape -----------------------------------------------------------------------------

    /// <summary>
    /// A first page costs a fixed number of queries whatever the page size: one read of the runs in scope,
    /// one of their plate analyses (every run is Ready, so no Track count), one of the eligible runs, one
    /// candidate batch (a WITH statement, captured since ADR-018), the page restricted to the candidates, and
    /// one explanation keyed on the page's Tracks.
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

        // The first search reads the runs' Vehicle Track counts once (one more statement); they are immutable
        // and cached, so later first pages do not repeat it.
        var cold = await Measure(2);
        var small = await Measure(2);
        var large = await Measure(20);

        Assert.Equal(7, cold.Statements);
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

        await db.GetService<IMigrator>().MigrateAsync(SearchMigration);
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
        await db.GetService<IMigrator>().MigrateAsync(SearchMigration);
        Assert.Equal(after, await IndexesAsync());
        await db.Database.MigrateAsync();
    }

    /// <summary>
    /// The planner, at default settings, serves each predicate shape the repository issues from its index:
    /// contains from the trigram GIN index, prefix and exact from the pattern b-tree. Planned over a
    /// temporary copy of <c>plate_track_texts</c> with the migration's own index definitions
    /// (<c>LIKE … INCLUDING INDEXES</c>) and 200 000 analysed rows of Indian-format texts, because on a
    /// small table a sequential scan is genuinely cheaper and the planner rightly takes it. The latency
    /// budget at 10^6 rows is the measurement's question (docs/qualification/stage4), not this test's.
    /// <para>
    /// <b>Limit (cold review P3-5).</b> This EXPLAINs literal predicates of the repository's shapes on a
    /// temporary table, not the repository's own parameterised statements. Those are EXPLAINed (ANALYZE,
    /// BUFFERS), as the repository issues them with their real parameters, by
    /// <c>PlateSearchScaleMeasurementTests</c> on the 10^6 corpus, where the planner's choice is meaningful; on
    /// the small integration corpus the planner rightly prefers primary-key or sequential access, so a
    /// real-statement EXPLAIN there would pin nothing about the indexes.
    /// </para>
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
            INSERT INTO plate_text_probe (analysis_id, track_id, normalised_text, support_count, max_confidence, best_plate_observation_id,
                track_start_timestamp_utc)
            SELECT gen_random_uuid(), gen_random_uuid(),
                   chr(65 + (i * 7) % 26) || chr(65 + (i / 26 * 11) % 26) || lpad(((i * 13) % 100)::text, 2, '0') ||
                   chr(65 + (i / 7 * 17) % 26) || chr(65 + (i / 3 * 19) % 26) || lpad(((i * 31) % 10000)::text, 4, '0'),
                   1, 0.9, gen_random_uuid(), timestamptz '2026-09-01 00:00:00+00' + i * interval '13 seconds'
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

    /// <summary>
    /// The pre-optimisation semantics, verbatim (plan §2.8): the base chain with a correlated EXISTS over the
    /// texts of a visible analysis of the pinned identity of the Track's own run, in page order.
    /// </summary>
    private static async Task<List<Guid>> PreOptimisationOrderAsync(MaviDbContext db, TrackSearchQuery query, string fingerprint, long snapshot)
    {
        var plate = query.Plate!;
        var value = plate.Text;
        var texts = db.PlateTrackTexts.AsNoTracking();
        if (plate.Match == TrackPlateMatch.Exact)
        {
            texts = texts.Where(text => text.NormalisedText == value);
        }
        else
        {
            var pattern = TrackPlateQueryRules.LikePattern(plate);
            texts = texts.Where(text => EF.Functions.Like(text.NormalisedText, pattern));
        }

        var analyses = db.PlateAnalyses.AsNoTracking().Where(analysis =>
            analysis.IdentityFingerprint == fingerprint
            && (analysis.Status == PlateAnalysisStatus.Completed || analysis.Status == PlateAnalysisStatus.Superseded)
            && analysis.VisibilitySequence != null
            && analysis.VisibilitySequence <= snapshot);
        return await AnalyticsScopeQuery.BaseCandidates(db, AnalyticsScopeRequest.From(query), snapshot)
            .Where(x => analyses.Any(analysis => analysis.ProcessingRunId == x.track.ProcessingRunId
                && texts.Any(text => text.AnalysisId == analysis.Id && text.TrackId == x.track.Id)))
            .OrderByDescending(x => x.track.StartTimestampUtc)
            .ThenByDescending(x => x.track.Id)
            .Select(x => x.track.Id)
            .ToListAsync();
    }

    private static string QueryLabel(TrackSearchQuery query) =>
        $"confidence={query.MinimumConfidence} from={query.FromUtc:O} to={query.ToUtc:O} duration={query.MinimumDurationMs} subclass={query.ObjectSubclass} run={query.ProcessingRunId} camera={query.CameraId}";

    /// <summary>The candidate statements (ADR-018) a search issued.</summary>
    private static int CandidateStatements(SqlCapture capture) =>
        capture.Statements.Count(statement => statement.Sql.Contains("WITH matched AS MATERIALIZED", StringComparison.Ordinal));

    /// <summary>Texts whose denormalised Track start differs from the Track's own (ADR-018: always zero).</summary>
    private Task<long> TrackStartDriftAsync() => CountAsync(
        "SELECT count(*) FROM plate_track_texts x JOIN tracks t ON t.id = x.track_id " +
        "WHERE x.track_start_timestamp_utc IS DISTINCT FROM t.start_timestamp_utc");

    private async Task<long> CountAsync(string sql, params object[] parameters)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        foreach (var parameter in parameters) command.Parameters.AddWithValue(parameter);
        return Convert.ToInt64(await command.ExecuteScalarAsync(), System.Globalization.CultureInfo.InvariantCulture);
    }

    private async Task ExecuteAsync(string sql, params object[] parameters)
    {
        await using var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        foreach (var parameter in parameters) command.Parameters.AddWithValue(parameter);
        await command.ExecuteNonQueryAsync();
    }

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
