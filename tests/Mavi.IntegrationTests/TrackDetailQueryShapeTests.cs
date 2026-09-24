using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;
using Mavi.Infrastructure.Persistence;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.IntegrationTests.Qualification;
using Microsoft.EntityFrameworkCore;
using static Mavi.IntegrationTests.Task14TestData;

namespace Mavi.IntegrationTests;

/// <summary>
/// The shape of the Track-detail raw-evidence read (S1.3 plan §5.1, §14): exactly two
/// bounded statements, a scalar Track read and one Evidence Set read, whatever the size
/// of the Evidence Set.
/// </summary>
/// <remarks>
/// <para>
/// <see cref="SqlCapture"/> records reader SELECTs, which is how EF Core issues every
/// query, including lazy loads and split queries. A future hand-written scalar or
/// non-query command would not be counted, so a change of that kind needs its own
/// assertion.
/// </para>
/// Like <see cref="AnalyticsQueryShapeTests"/>, this counts the statements the
/// repository really issues. A per-Observation read, a lazily loaded crop or a join that
/// multiplies the Track row would change the count or the SQL, and a latency number would
/// not show it on a small corpus.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class TrackDetailQueryShapeTests
{
    private static readonly DateTimeOffset CompletedAt = new(2026, 9, 24, 8, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task TheRawEvidenceReadIsTwoStatementsWhetherTheSetHoldsOneObservationOrFour()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        var single = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt.AddMinutes(-5),
            [(ObservationType.Representative, 0)],
            new RepresentativePointer.RankZero(), localTrackNumber: 1);
        var full = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt,
            [(ObservationType.Representative, 0), (ObservationType.NearView, 1),
             (ObservationType.EarlyDiverse, 2), (ObservationType.LateDiverse, 3)],
            new RepresentativePointer.RankZero(), localTrackNumber: 2);

        var one = await MeasureRawEvidenceReadAsync(factory, single.TrackId);
        var four = await MeasureRawEvidenceReadAsync(factory, full.TrackId);

        // A constant count over an empty read would be worthless, so both reads must
        // have returned their whole set.
        Assert.Equal(1, one.Observations);
        Assert.Equal(4, four.Observations);

        Assert.Equal(2, one.Statements.Count);
        Assert.Equal(2, four.Statements.Count);

        // The scalar read no longer joins Observations: the removed Representative join
        // would be one Representative projection too many (S1.3 plan §5.1).
        Assert.DoesNotContain("observations", four.Statements[0].Sql, StringComparison.OrdinalIgnoreCase);
        // The Evidence Set read is the single Observations statement, ordered by rank and
        // bounded to one more than a full set.
        Assert.Contains("observations", four.Statements[1].Sql, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("evidence_rank", four.Statements[1].Sql, StringComparison.Ordinal);
        Assert.Contains("LIMIT", four.Statements[1].Sql, StringComparison.OrdinalIgnoreCase);
        Assert.Contains(
            four.Statements[1].Parameters,
            parameter => parameter.Value is int limit && limit == TrackEvidenceSet.MaximumCount + 1);
    }

    [Fact]
    public async Task TheWholeTrackDetailCostsTheSameNumberOfStatementsForOneObservationOrFour()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        var single = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt.AddMinutes(-5),
            [(ObservationType.Representative, 0)],
            new RepresentativePointer.RankZero(), localTrackNumber: 1);
        var full = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt,
            [(ObservationType.Representative, 0), (ObservationType.NearView, 1),
             (ObservationType.EarlyDiverse, 2), (ObservationType.LateDiverse, 3)],
            new RepresentativePointer.RankZero(), localTrackNumber: 2);

        // End to end through the service, analytics included: nothing downstream of the
        // Evidence Set read (mapping, analytics) may add a statement per Observation.
        var one = await MeasureServiceReadAsync(factory, single.TrackId);
        var four = await MeasureServiceReadAsync(factory, full.TrackId);

        Assert.Equal(1, one.Observations);
        Assert.Equal(4, four.Observations);
        Assert.Equal(one.Statements.Count, four.Statements.Count);
        // And the Evidence Set is read exactly once: an equal count could otherwise hide
        // the set being read twice in both cases.
        Assert.Single(four.Statements, statement => ReadsObservations(statement.Sql));
        Assert.Single(one.Statements, statement => ReadsObservations(statement.Sql));
    }

    private static async Task<(int Observations, IReadOnlyList<CapturedStatement> Statements)> MeasureRawEvidenceReadAsync(
        ApiTestFactory factory,
        Guid trackId)
    {
        var capture = new SqlCapture();
        await using var db = CreateContext(factory, capture);
        var repository = new TrackSearchRepository(db, TimeProvider.System);

        var row = await repository.GetDetailAsync(trackId, default);
        Assert.NotNull(row);
        var observations = await repository.GetEvidenceSetAsync(trackId, default);
        _ = TrackEvidenceSet.FromPersisted(row.RepresentativeObservationId, observations);

        return (observations.Count, capture.Statements.ToArray());
    }

    private static async Task<(int Observations, IReadOnlyList<CapturedStatement> Statements)> MeasureServiceReadAsync(
        ApiTestFactory factory,
        Guid trackId)
    {
        var capture = new SqlCapture();
        await using var db = CreateContext(factory, capture);
        var service = new TrackSearchService(
            new TrackSearchRepository(db, TimeProvider.System),
            TimeProvider.System,
            TrackCursorSigningKey.CreateEphemeral());

        var result = await service.GetDetailAsync(trackId, TrackAnalyticsDetailRequest.Current, default);
        Assert.True(result.IsSuccess);
        Assert.NotNull(result.EvidenceSet);

        return (result.EvidenceSet.Observations.Count, capture.Statements.ToArray());
    }

    private static bool ReadsObservations(string sql) =>
        System.Text.RegularExpressions.Regex.IsMatch(sql, @"\bobservations\b", System.Text.RegularExpressions.RegexOptions.IgnoreCase);

    private static MaviDbContext CreateContext(ApiTestFactory factory, SqlCapture capture) =>
        new(new DbContextOptionsBuilder<MaviDbContext>()
            .UseNpgsql(factory.ConnectionString, npgsql => npgsql.UseVector())
            .AddInterceptors(capture)
            .Options);
}
