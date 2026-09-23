using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.Intelligence;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>
/// Slice 7 corpus C1: one hand-authored trajectory whose expected answer is written
/// out by a human from the frozen rules, traced across every layer that claims to
/// carry it — sealed artefact bytes, the real decoder, the real engine, the fenced
/// commit, the §S analytic search and the §T aggregate.
/// </summary>
/// <remarks>
/// <para>
/// This is the trace Stage 1 did not have. The executor tests prove the pipeline
/// derives <em>something</em> from real bytes; the §S and §T tests prove the read
/// side answers correctly over facts a test <em>wrote by hand</em>. Nothing joined
/// the two, so a divergence between what the engine derives and what the read side
/// counts would have passed both suites.
/// </para>
/// <para>
/// Every expectation below is derived from the frozen rules before the test was run,
/// not read off an observed result. Where a value depends on an interpolation policy
/// the plan does not freeze — the exact millisecond a boundary is deemed crossed —
/// the assertion is the bracket the samples themselves imply, stated with its
/// arithmetic, rather than a tolerance chosen to fit.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SemanticAcceptanceTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalyticsOptions Options = new()
    {
        LeaseSeconds = 900,
        MaxUnitDurationSeconds = 300,
        ReclaimGraceSeconds = 60,
        MaximumAttempts = 3,
    };

    /*
     * The scene, as the fixture draws it:
     *
     *   zone "Gate"  — the square x in [0.1, 0.4], y in [0.1, 0.4], loitering at 45 s
     *   line "Kerb"  — A (0.1, 0.5) to B (0.9, 0.5), directed, left to right
     *
     * The authored path, at 200 ms per sample (5 Hz), inside the Track's 0–8000 ms span:
     *
     *   t =    0 .. 2000   (0.25, 0.80) -> (0.25, 0.36)   approach, moving up the frame
     *   t = 2200 .. 5800   (0.25, 0.36) -> (0.28, 0.30)   drift, wholly inside the Gate
     *   t = 6000 .. 8000   (0.28, 0.30) -> (0.60, 0.78)   departure, down and to the right
     *
     * What the frozen rules say about it, worked out by hand:
     *
     *   Line. Cross(A, B, p) = 0.8 * (p.y - 0.5), and the on-line band is
     *   epsilon * |AB| = 0.005 * 0.8, so a sample counts as on a side once
     *   |p.y - 0.5| >= 0.005. The approach passes y = 0.5 between t = 1200
     *   (y = 0.536) and t = 1400 (y = 0.492) — both clear of the band — moving
     *   UP the frame, which the frozen direction convention names AToB. The
     *   departure passes it between t = 6800 (y = 0.492) and t = 7000
     *   (y = 0.540) moving DOWN, which is BToA. Exactly two crossings, one each
     *   way, 5.4 s apart and opposite, so repeat suppression (1 s) cannot merge
     *   them.
     *
     *   Zone. Containment is y <= 0.4 along x = 0.25. Entry falls between
     *   t = 1800 (y = 0.404, outside) and t = 2000 (y = 0.36, inside). Exit
     *   needs the epsilon margin, y > 0.405, which falls between t = 6400
     *   (y = 0.396) and t = 6600 (y = 0.444). One entry, one exit, and a dwell
     *   the samples bracket to [6400 - 2000, 6600 - 1800] = [4400, 4800] ms.
     *   4.8 s is far below the zone's 45 s loitering threshold, so this Track
     *   does not loiter.
     *
     *   Heading. First sample (0.25, 0.80) to last (0.60, 0.78): dx = +0.35,
     *   dy = -0.02, displacement 0.351 >= the 0.02 minimum. atan2(dx, -dy) is
     *   86.7 degrees, which lands in the East sector (67.5 to 112.5).
     */
    private const long ZoneEntryLowerMs = 1_800;
    private const long ZoneEntryUpperMs = 2_000;
    private const long ZoneExitLowerMs = 6_400;
    private const long ZoneExitUpperMs = 6_600;

    /// <summary>The authored path, piecewise linear at 200 ms per sample.</summary>
    private static byte[] AuthoredPath() => TrajectoryPayload.Encode(AuthoredPoints());

    private static List<(long OffsetMs, double X, double Y)> AuthoredPoints()
    {
        var points = new List<(long, double, double)>(41);
        for (long t = 0; t <= 8_000; t += 200)
        {
            var (x, y) = t switch
            {
                <= 2_000 => (0.25, Lerp(0.80, 0.36, t, 0, 2_000)),
                <= 5_800 => (Lerp(0.25, 0.28, t, 2_000, 5_800), Lerp(0.36, 0.30, t, 2_000, 5_800)),
                _ => (Lerp(0.28, 0.60, t, 6_000, 8_000), Lerp(0.30, 0.78, t, 6_000, 8_000)),
            };
            points.Add((t, Math.Round(x, 6), Math.Round(y, 6)));
        }

        return points;
    }

    private static double Lerp(double from, double to, long at, long start, long end) =>
        from + ((to - from) * (at - start) / (double)(end - start));

    /// <summary>
    /// The facts the engine derives from the authored path are exactly the ones a
    /// human reading the frozen rules predicts.
    /// </summary>
    [Fact]
    public async Task TheEngineDerivesTheFactsTheFrozenRulesPredict()
    {
        var world = await AnalysedWorldAsync();

        await using var reader = world.Read();

        var outcome = await reader.TrackAnalysisOutcomes.AsNoTracking().SingleAsync();
        Assert.Equal(TrackAnalysisOutcomeKind.Analysed, outcome.Outcome);
        Assert.Equal(41, outcome.SampleCount);

        // One visit, entered and left once, with the dwell the samples bracket.
        var visit = await reader.TrackZoneVisits.AsNoTracking().SingleAsync();
        Assert.Equal(world.ZoneId, visit.ZoneId);
        Assert.InRange(visit.EntryOffsetMs, ZoneEntryLowerMs, ZoneEntryUpperMs);
        Assert.InRange(visit.ExitOffsetMs, ZoneExitLowerMs, ZoneExitUpperMs);
        Assert.InRange(visit.DwellMs, ZoneExitLowerMs - ZoneEntryUpperMs, ZoneExitUpperMs - ZoneEntryLowerMs);
        Assert.False(visit.BeganInside);
        Assert.False(visit.EndedInside);

        var summary = await reader.TrackZoneSummaries.AsNoTracking().SingleAsync();
        Assert.Equal(1, summary.VisitCount);
        Assert.Equal(visit.DwellMs, summary.TotalDwellMs);
        // 4.8 s against a 45 s threshold: not loitering, and the threshold is recorded.
        Assert.False(summary.Loitering);
        Assert.Equal(45, summary.LoiteringThresholdSeconds);

        // Exactly two crossings of the one line, one each way, in time order.
        var crossings = await reader.TrackLineCrossings.AsNoTracking()
            .OrderBy(crossing => crossing.OffsetMs).ToListAsync();
        Assert.Equal(2, crossings.Count);
        Assert.All(crossings, crossing => Assert.Equal(world.LineId, crossing.LineId));
        Assert.Equal("AToB", crossings[0].Direction);
        Assert.Equal("BToA", crossings[1].Direction);
        Assert.InRange(crossings[0].OffsetMs, 1_200, 1_400);
        Assert.InRange(crossings[1].OffsetMs, 6_800, 7_000);

        var motion = await reader.TrackMotionSummaries.AsNoTracking().SingleAsync();
        Assert.Equal("E", motion.Heading);
        // The path never stands still for the 5 s a person must, so there is no
        // stationary interval to find. Asserting the absence keeps a detector that
        // fires on any slow stretch from passing.
        Assert.Equal(0, motion.TotalStationaryMs);
        Assert.Empty(motion.StationaryIntervals);
    }

    /// <summary>
    /// The §S predicates select on those derived facts. Where C1's single Track has a
    /// complement — dwell above the derived dwell, the seven other headings, stationary,
    /// loitering — it is rejected. C1 crosses both ways and has one identity, so the
    /// direction, zone-relation and identity complements are held by
    /// <c>TrackSearchAnalyticsRepositoryTests.EveryPredicateTranslatesAndMatchesTheFixtureFacts</c>
    /// and its stale-identity cases, not here.
    /// </summary>
    /// <remarks>
    /// The negative half is the point. A predicate that matched everything would pass
    /// every positive assertion here.
    /// </remarks>
    [Fact]
    public async Task TheSearchPredicatesSelectOnWhatTheEngineDerived()
    {
        var world = await AnalysedWorldAsync();

        await AssertMatchesAsync(world, TrackAnalyticsQuery.Empty with
        {
            ZoneId = world.ZoneId,
            ZoneRelation = TrackZoneRelation.Entered,
        }, true);
        await AssertMatchesAsync(world, TrackAnalyticsQuery.Empty with
        {
            ZoneId = world.ZoneId,
            ZoneRelation = TrackZoneRelation.Exited,
        }, true);

        // Dwell straddles the derived value: 4.4 s of dwell is there, 6 s is not.
        await AssertMatchesAsync(world, TrackAnalyticsQuery.Empty with
        {
            ZoneId = world.ZoneId,
            ZoneRelation = TrackZoneRelation.Dwelled,
            MinDwellMs = ZoneExitLowerMs - ZoneEntryUpperMs,
        }, true);
        await AssertMatchesAsync(world, TrackAnalyticsQuery.Empty with
        {
            ZoneId = world.ZoneId,
            ZoneRelation = TrackZoneRelation.Dwelled,
            MinDwellMs = 6_000,
        }, false);

        // Both directions happened, so both must match. An ignored direction filter
        // would also pass these; the complement (a direction that did not happen) is
        // held by TrackSearchAnalyticsRepositoryTests, whose fixture crosses one way.
        await AssertMatchesAsync(world, TrackAnalyticsQuery.Empty with
        {
            LineId = world.LineId,
            CrossingDirection = TrackCrossingDirection.AToB,
        }, true);
        await AssertMatchesAsync(world, TrackAnalyticsQuery.Empty with
        {
            LineId = world.LineId,
            CrossingDirection = TrackCrossingDirection.BToA,
        }, true);

        // Heading is a single value, so seven of the eight must reject it.
        await AssertMatchesAsync(world, TrackAnalyticsQuery.Empty with { MotionDirection = "E" }, true);
        foreach (var heading in new[] { "N", "NE", "SE", "S", "SW", "W", "NW" })
        {
            await AssertMatchesAsync(world, TrackAnalyticsQuery.Empty with { MotionDirection = heading }, false);
        }

        // Derived: no stationary run at all, and no loitering.
        await AssertMatchesAsync(world, TrackAnalyticsQuery.Empty with { MinStationaryMs = 1 }, false);
        await AssertMatchesAsync(world, TrackAnalyticsQuery.Empty with { Loitering = true }, false);

        // The identity the facts were derived under selects them. A foreign identity is
        // refused or classified stale, not matched — held by TrackSearchAnalyticsRepositoryTests.
        await AssertMatchesAsync(world, TrackAnalyticsQuery.Empty with
        {
            SceneRevisionId = world.RevisionId,
            AnalyticsAlgorithmVersion = SceneAnalyticsWorld.AlgorithmVersion,
            ZoneId = world.ZoneId,
        }, true);
    }

    /// <summary>
    /// The §T aggregate counts the same facts, and counts them once.
    /// </summary>
    [Fact]
    public async Task TheAggregateCountsWhatTheEngineDerived()
    {
        var world = await AnalysedWorldAsync();

        await using var db = fixture.CreateDbContext();
        var result = await new AnalyticsAggregateRepository(db).AggregateAsync(
            new AnalyticsAggregateQuery(world.CameraId, Now.AddHours(-2), Now.AddHours(1), 3_600, null),
            default);

        Assert.True(result.IsSuccess);
        Assert.True(result.Coverage!.Complete);
        Assert.Equal(1, result.Coverage.AnalysedTracks);

        var series = AnalyticsAggregator.Compute(result.Facts!, Now.AddHours(-2), Now.AddHours(1), 3_600);

        var zone = Assert.Single(series.Zones);
        Assert.Equal(world.ZoneId, zone.ZoneId);
        Assert.Equal(1, zone.WindowEntryCount);
        Assert.Equal(1, zone.WindowExitCount);
        Assert.Equal(1, zone.WindowUniqueTrackCount);
        // One visit is not a repeat visit, however long it lasted.
        Assert.Equal(0, zone.RepeatedVisitTrackCount);
        // Occupancy is sampled at each bucket's start instant, not integrated over the
        // bucket (plan §4.2). The visit lasts under five seconds inside an hour-wide
        // bucket whose start instant it does not span, so the sampled occupancy is
        // zero — and reporting one here would be the aggregate claiming a measurement
        // it never took. I expected one before running this, and the rule is right.
        Assert.Equal(0, zone.PeakOccupancy);
        Assert.Null(zone.PeakOccupancyAtUtc);

        // The complement, so "zero" above cannot be an occupancy series that never
        // counts anything: resolved to one-second buckets over the recording itself,
        // the same visit is sampled, and the peak instant falls inside it.
        var fine = AnalyticsAggregator.Compute(
            result.Facts!, world.RecordingStartUtc, world.RecordingStartUtc.AddSeconds(10), 1);
        var fineZone = Assert.Single(fine.Zones);
        Assert.Equal(1, fineZone.PeakOccupancy);
        var visit = await FirstVisitAsync();
        Assert.NotNull(fineZone.PeakOccupancyAtUtc);
        Assert.InRange(
            fineZone.PeakOccupancyAtUtc!.Value,
            world.RecordingStartUtc.AddMilliseconds(visit.EntryOffsetMs),
            world.RecordingStartUtc.AddMilliseconds(visit.ExitOffsetMs));

        var line = Assert.Single(series.Lines);
        Assert.Equal(world.LineId, line.LineId);
        Assert.Equal(1, line.WindowAToBCount);
        Assert.Equal(1, line.WindowBToACount);

        // Every class is present whether or not it was seen, so an operator reading a
        // zero is reading a measured absence rather than a missing row.
        Assert.Equal(
            new[] { (ObjectClass.Person, 1), (ObjectClass.Vehicle, 0) },
            series.Classes.Select(entry => (entry.ObjectClass, entry.WindowDistinctTrackCount)).ToArray());
    }

    /// <summary>
    /// The explanation, the heatmap and the operator-facing contract carry the same
    /// answer — read through the real HTTP API, which is what the UI consumes.
    /// </summary>
    /// <remarks>
    /// <para>
    /// This closes the three layers the C1 trace stopped short of (plan §7). The
    /// track detail is what Evidence Review's explanation is built from; the scene
    /// revision is what names the geometry in it; the heatmap is the Analytics
    /// Workbench's second mode. Each is asserted against the hand-derived answer
    /// above, not against itself.
    /// </para>
    /// <para>
    /// The three responses are then normalised — server-issued ids become ordinal
    /// tokens, the snapshot sequence becomes zero — and compared byte for byte with
    /// the committed <c>c1-operator-contract.json</c>. The frontend suite reads that
    /// same file and drives the real explanation and heatmap components with it, so
    /// the UI leg is asserted over bytes this test has proved the server produces.
    /// A change on either side fails one of the two suites. Regenerate deliberately
    /// with <c>MAVI_UPDATE_GOLDEN=1</c>.
    /// </para>
    /// </remarks>
    [Fact]
    public async Task TheExplanationHeatmapAndOperatorContractCarryTheSameAnswer()
    {
        var world = await AnalysedWorldAsync();
        await using var factory = new ApiTestFactory
        {
            Clock = world.Clock,
            EnableSceneAnalyticsHost = false,
            MediaRootOverride = world.MediaRoot,
            EvidenceRootOverride = world.EvidenceRoot,
        };
        using var client = factory.CreateClient();

        var windowFrom = world.RecordingStartUtc;
        var windowTo = world.RecordingStartUtc.AddHours(1);
        var detailJson = await client.GetStringAsync($"/api/tracks/{world.TrackId}");
        var revisionJson = await client.GetStringAsync($"/api/cameras/{world.CameraId}/scene/revisions/1");
        var heatmapJson = await client.GetStringAsync(
            $"/api/cameras/{world.CameraId}/analytics/heatmap?fromUtc={Iso(windowFrom)}&toUtc={Iso(windowTo)}&gridWidth={C1GridWidth}");

        // --- Explanation: the detail the Evidence Review explanation is built from.
        using (var detail = JsonDocument.Parse(detailJson))
        {
            var analytics = detail.RootElement.GetProperty("analytics");
            Assert.Equal("Analysed", analytics.GetProperty("status").GetString());
            Assert.Equal(world.RevisionId, analytics.GetProperty("sceneRevisionId").GetGuid());
            Assert.Equal(1, analytics.GetProperty("sceneRevisionNumber").GetInt32());
            Assert.Equal(SceneAnalyticsWorld.AlgorithmVersion, analytics.GetProperty("algorithmVersion").GetString());
            Assert.Equal(41, analytics.GetProperty("sampleCount").GetInt32());

            var visit = Assert.Single(analytics.GetProperty("zoneVisits").EnumerateArray().ToList());
            Assert.Equal(world.ZoneId, visit.GetProperty("zoneId").GetGuid());
            Assert.InRange(visit.GetProperty("entryOffsetMs").GetInt64(), ZoneEntryLowerMs, ZoneEntryUpperMs);
            Assert.InRange(visit.GetProperty("exitOffsetMs").GetInt64(), ZoneExitLowerMs, ZoneExitUpperMs);

            var summary = Assert.Single(analytics.GetProperty("zoneSummaries").EnumerateArray().ToList());
            Assert.Equal(1, summary.GetProperty("visitCount").GetInt32());
            Assert.False(summary.GetProperty("loitering").GetBoolean());

            var crossings = analytics.GetProperty("lineCrossings").EnumerateArray().ToList();
            // The wire vocabulary is camel-cased (`aToB`), the persisted one is not
            // (`AToB`); the browser's `CROSSING_DIRECTIONS` is the wire spelling.
            Assert.Equal(["aToB", "bToA"], crossings.Select(crossing => crossing.GetProperty("direction").GetString()));
            Assert.InRange(crossings[0].GetProperty("offsetMs").GetInt64(), 1_200, 1_400);
            Assert.InRange(crossings[1].GetProperty("offsetMs").GetInt64(), 6_800, 7_000);

            var motion = analytics.GetProperty("motion");
            Assert.Equal("E", motion.GetProperty("heading").GetString());
            Assert.Equal(0, motion.GetProperty("totalStationaryMs").GetInt64());
            Assert.Empty(motion.GetProperty("stationaryIntervals").EnumerateArray());
        }

        // --- The geometry names the explanation uses come from the pinned revision.
        using (var revision = JsonDocument.Parse(revisionJson))
        {
            Assert.Equal(world.RevisionId, revision.RootElement.GetProperty("revisionId").GetGuid());
            Assert.Equal("Gate", Assert.Single(revision.RootElement.GetProperty("zones").EnumerateArray().ToList()).GetProperty("name").GetString());
            Assert.Equal("Kerb", Assert.Single(revision.RootElement.GetProperty("tripLines").EnumerateArray().ToList()).GetProperty("name").GetString());
        }

        // --- Heatmap: every authored sample lies inside the window, so all 41 count,
        // each in the cell the frozen binning rule assigns it.
        using (var heatmap = JsonDocument.Parse(heatmapJson))
        {
            var root = heatmap.RootElement;
            Assert.Equal(world.RevisionId, root.GetProperty("sceneRevisionId").GetGuid());
            Assert.Equal(C1GridWidth, root.GetProperty("gridWidth").GetInt32());
            Assert.Equal(C1GridHeight, root.GetProperty("gridHeight").GetInt32());
            Assert.Equal(41, root.GetProperty("sampleCount").GetInt64());
            Assert.Equal(1, root.GetProperty("trackCount").GetInt32());
            Assert.True(root.GetProperty("coverage").GetProperty("evaluatedRuns").GetInt32() == 1);

            var expected = ExpectedC1Heatmap();
            Assert.Equal(expected, root.GetProperty("values").EnumerateArray().Select(value => value.GetInt32()).ToArray());
            Assert.Equal(expected.Max(), root.GetProperty("maxCellValue").GetInt32());
        }

        var golden = OperatorContract(detailJson, revisionJson, heatmapJson);
        var path = C1GoldenPath();
        if (Environment.GetEnvironmentVariable("MAVI_UPDATE_GOLDEN") == "1")
        {
            await File.WriteAllTextAsync(path, golden);
        }

        Assert.Equal(await File.ReadAllTextAsync(path), golden);
    }

    private const int C1GridWidth = 16;
    private const int C1GridHeight = 9;

    /// <summary>
    /// The authored samples binned by the frozen rule, restated here independently of
    /// <c>HeatmapGrid</c>: column <c>floor(x · width)</c>, row <c>floor(y · height)</c>,
    /// the closed right and bottom edges clamped into the last cell, row-major.
    /// </summary>
    private static int[] ExpectedC1Heatmap()
    {
        var cells = new int[C1GridWidth * C1GridHeight];
        foreach (var (_, x, y) in AuthoredPoints())
        {
            var column = Math.Min((int)(x * C1GridWidth), C1GridWidth - 1);
            var row = Math.Min((int)(y * C1GridHeight), C1GridHeight - 1);
            cells[(row * C1GridWidth) + column]++;
        }

        return cells;
    }

    /// <summary>
    /// The three responses with server-issued ids replaced by ordinal tokens, in order
    /// of first appearance, and the database-allocated snapshot sequence zeroed.
    /// </summary>
    private static string OperatorContract(string detailJson, string revisionJson, string heatmapJson)
    {
        var tokens = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var document = new System.Text.Json.Nodes.JsonObject
        {
            ["trackDetail"] = Normalise(System.Text.Json.Nodes.JsonNode.Parse(detailJson), tokens),
            ["sceneRevision"] = Normalise(System.Text.Json.Nodes.JsonNode.Parse(revisionJson), tokens),
            ["heatmap"] = Normalise(System.Text.Json.Nodes.JsonNode.Parse(heatmapJson), tokens),
        };
        return document.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n";
    }

    private static System.Text.Json.Nodes.JsonNode? Normalise(
        System.Text.Json.Nodes.JsonNode? node,
        Dictionary<string, string> tokens)
    {
        switch (node)
        {
            case System.Text.Json.Nodes.JsonObject value:
                foreach (var property in value.ToList())
                {
                    value[property.Key] = property.Key == "snapshotVisibilitySequence"
                        ? 0
                        : Normalise(property.Value?.DeepClone(), tokens);
                }

                return value;
            case System.Text.Json.Nodes.JsonArray array:
                for (var index = 0; index < array.Count; index++)
                {
                    array[index] = Normalise(array[index]?.DeepClone(), tokens);
                }

                return array;
            case System.Text.Json.Nodes.JsonValue scalar when scalar.TryGetValue<string>(out var text):
                // Every id, including ids embedded in a route such as a content URL.
                return System.Text.RegularExpressions.Regex.Replace(
                    text,
                    "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                    match =>
                    {
                        if (!tokens.TryGetValue(match.Value, out var token))
                        {
                            token = $"00000000-0000-4000-8000-{tokens.Count + 1:D12}";
                            tokens[match.Value] = token;
                        }

                        return token;
                    });
            default:
                return node;
        }
    }

    private static string C1GoldenPath()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var fixtures = Path.Combine(directory.FullName, "tests", "fixtures", "scene-analytics");
            if (Directory.Exists(fixtures)) return Path.Combine(fixtures, "c1-operator-contract.json");
            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("tests/fixtures/scene-analytics was not found above the test assembly.");
    }

    private static string Iso(DateTimeOffset value) =>
        Uri.EscapeDataString(value.ToString("yyyy-MM-ddTHH:mm:ssZ", System.Globalization.CultureInfo.InvariantCulture));

    private async Task<TrackZoneVisit> FirstVisitAsync()
    {
        await using var db = fixture.CreateDbContext();
        return await db.TrackZoneVisits.AsNoTracking().SingleAsync();
    }

    private async Task<SceneAnalyticsWorld> AnalysedWorldAsync()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await world.AttachTrajectoryAsync(AuthoredPath());
        var (executor, lifecycle, db) = world.Executor();
        await using var _ = db;

        await lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            sourceCommit: null,
            Now.AddDays(-1),
            50,
            default);
        var claim = await lifecycle.ClaimNextAsync(
            SceneAnalyticsWorld.ExecutionIdentity, Options.ToLeasePolicy(), default)
            ?? throw new InvalidOperationException("No unit was claimable.");

        var result = await executor.ExecuteAsync(claim, SceneAnalyticsWorld.ExecutionIdentity, Options, default);
        Assert.True(result.IsSuccess);
        Assert.Equal(1, result.AnalysedTrackCount);
        return world;
    }

    private async Task AssertMatchesAsync(SceneAnalyticsWorld world, TrackAnalyticsQuery analytics, bool expected)
    {
        await using var db = fixture.CreateDbContext();
        var repository = new TrackSearchRepository(db, world.Clock);
        var result = await repository.SearchAnalyticsAsync(
            new TrackSearchQuery(world.CameraId, null, null, null, null, null, null, null, null, 50, analytics),
            null,
            51,
            default);

        Assert.True(result.IsValid);
        var page = Assert.IsType<TrackAnalyticsSearchRepositoryPage>(result.Page);
        Assert.Equal(expected, page.Items.Any(item => item.Id == world.TrackId));
    }
}
