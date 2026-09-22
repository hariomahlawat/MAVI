using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.IntegrationTests.Qualification;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests;

/// <summary>
/// The shape of the analytical read path: how many database round trips it takes,
/// and whether that number depends on the scene.
/// </summary>
/// <remarks>
/// Stage-1 exit requires that no N+1 database path remains. A latency number
/// cannot show that — a slow query and a query issued once per zone look alike on
/// a small corpus — so the property is asserted directly: the count must not move
/// when the geometry does. This runs in the ordinary suite because a query count
/// is a property of the code, not of the database version or the hardware, so it
/// is worth protecting on every commit rather than only during qualification.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class AnalyticsQueryShapeTests(PostgresFixture fixture)
{
    private async Task<(int Queries, int Zones, int Lines)> MeasureAsync(int zoneCount, int lineCount)
    {
        var corpus = new QualificationCorpus(fixture);
        var manifest = await corpus.BuildAsync(
            seed: 4242,
            videoCount: 2,
            tracksPerRun: 4,
            zoneCount: zoneCount,
            lineCount: lineCount,
            visitsPerTrack: 2,
            crossingsPerTrack: 1);

        var capture = new SqlCapture();
        var options = new DbContextOptionsBuilder<MaviDbContext>()
            .UseNpgsql(fixture.ConnectionString, npgsql => npgsql.UseVector())
            .AddInterceptors(capture)
            .Options;

        await using var db = new MaviDbContext(options);
        var repository = new AnalyticsAggregateRepository(db);

        var result = await repository.AggregateAsync(
            new AnalyticsAggregateQuery(
                manifest.CameraId, manifest.WindowFromUtc, manifest.WindowToUtc, 3_600, null),
            default);

        Assert.True(result.IsSuccess);
        return (capture.Statements.Count, result.Facts!.Zones.Count, result.Facts.Lines.Count);
    }

    [Fact]
    public async Task TheAggregateCostsTheSameNumberOfQueriesHoweverMuchGeometryTheSceneHas()
    {
        // Four zones and two lines against twelve zones and six lines. If any part
        // of the read were per-zone or per-line — a summary fetched inside a loop,
        // a series resolved one geometry at a time — the second number would be
        // larger, and the aggregate would degrade as operators draw more geometry.
        var small = await MeasureAsync(zoneCount: 4, lineCount: 2);
        var large = await MeasureAsync(zoneCount: 12, lineCount: 6);

        Assert.Equal(4, small.Zones);
        Assert.Equal(12, large.Zones);
        Assert.Equal(2, small.Lines);
        Assert.Equal(6, large.Lines);

        Assert.Equal(small.Queries, large.Queries);
    }
}
