using Mavi.Application.Modules.Intelligence;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.EntityFrameworkCore;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// The §S qualification harness must call the analytic search, because the plain
/// one silently discards every §S predicate.
/// </summary>
/// <remarks>
/// <para>
/// This is the regression test for the worst defect found in the Slice-7 harness.
/// <c>TrackSearchRepository.SearchAsync</c> applies only the non-analytic base
/// candidate set — camera, window, class — and drops the analytics query entirely.
/// The plan harness called it for all 23 §S predicate families, so every
/// measurement planned and timed the same plain Track search while the evidence
/// named a different predicate each time. Nothing failed: the rows came back, the
/// plans were real plans, the file was written.
/// </para>
/// <para>
/// It runs in the ordinary suite rather than behind the qualification gate,
/// because the property it pins is about the repository's two entry points and
/// costs one small corpus to establish.
/// </para>
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SearchEntryPointTests(PostgresFixture fixture)
{
    private static readonly string[] AnalyticsFactTables =
    [
        "track_zone_visits", "track_zone_summaries", "track_line_crossings",
        "track_motion_summaries", "scene_analyses",
    ];

    [Fact]
    public async Task OnlyTheAnalyticSearchAppliesAnAnalyticPredicate()
    {
        var manifest = await new QualificationCorpus(fixture).BuildAsync(
            seed: 20260922,
            videoCount: 1,
            tracksPerRun: 24,
            zoneCount: 2,
            lineCount: 1,
            visitsPerTrack: 1,
            crossingsPerTrack: 1);

        var capture = new SqlCapture();
        var options = new DbContextOptionsBuilder<MaviDbContext>()
            .UseNpgsql(fixture.ConnectionString, npgsql => npgsql.UseVector())
            .AddInterceptors(capture)
            .Options;

        // One heading, which a real predicate must narrow the population down to.
        var analytics = TrackAnalyticsQuery.Empty with { MotionDirection = "NE" };
        var query = new TrackSearchQuery(
            manifest.CameraId, null, null, null,
            manifest.WindowFromUtc, manifest.WindowToUtc, null, null, null, 50, analytics);

        await using var db = new MaviDbContext(options);
        var repository = new TrackSearchRepository(db, TimeProvider.System);

        capture.Clear();
        var plain = await repository.SearchAsync(query, cursor: null, take: 50, cancellationToken: default);
        var plainSql = string.Concat(capture.Statements.Select(statement => statement.Sql));

        capture.Clear();
        var analytic = await repository.SearchAnalyticsAsync(query, cursor: null, take: 51, cancellationToken: default);
        var analyticSql = string.Concat(capture.Statements.Select(statement => statement.Sql));

        // The plain search never reaches an analytics table, so the predicate cannot
        // have been applied — and it returns the whole population to prove it.
        Assert.DoesNotContain(AnalyticsFactTables, table => plainSql.Contains(table, StringComparison.Ordinal));
        Assert.Equal(manifest.TrackCount, plain.Items.Count);

        // The analytic search reaches the motion table and returns a strict subset.
        Assert.Contains("track_motion_summaries", analyticSql, StringComparison.Ordinal);
        var page = Assert.IsType<TrackAnalyticsSearchRepositoryPage>(analytic.Page);
        Assert.True(analytic.IsValid);
        Assert.InRange(page.Items.Count, 1, manifest.TrackCount - 1);
    }
}
