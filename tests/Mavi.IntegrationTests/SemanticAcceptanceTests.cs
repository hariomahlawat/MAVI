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
    private static byte[] AuthoredPath()
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

        return TrajectoryPayload.Encode(points);
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
    /// The §S predicates select on those derived facts, and reject their complements.
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

        // Both directions happened, so both must match; a direction filter that was
        // ignored would also pass these, which is why the class filter below differs.
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

        // The identity the facts were derived under selects them; another does not.
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
