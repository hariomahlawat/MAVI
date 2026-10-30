using Mavi.Application.Modules.Query;
using Mavi.Contracts.Api.Query;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests.Query;

/// <summary>
/// The pure evaluator (ADR-024 §4) and the service's coverage gate (§6), without a database: the arithmetic every
/// envelope rests on, and the rule that incomplete coverage never reaches the caller as a figure.
/// </summary>
public sealed class StructuredQueryEvaluatorTests
{
    private static readonly DateTimeOffset From = new(2026, 9, 21, 8, 0, 0, TimeSpan.Zero);
    private static readonly QueryWindow Window = new(From, From.AddHours(6));
    private static readonly Guid CameraA = Guid.Parse("00000000-0000-4000-8000-00000000000a");
    private static readonly Guid CameraB = Guid.Parse("00000000-0000-4000-8000-00000000000b");

    [Fact]
    public void TimeBucketsPartitionTheCountAndAnchorAnEarlierStartAtTheWindowOpening()
    {
        var records = new[]
        {
            Track(1, CameraA, From.AddMinutes(-20)), // began before the window: anchored at 08:00
            Track(2, CameraA, From.AddMinutes(59)),
            Track(3, CameraB, From.AddMinutes(60)), // exactly on a boundary: the later bucket
            Track(4, CameraB, From.AddHours(5).AddMinutes(59)),
        };

        var buckets = StructuredQueryEvaluator.EvaluateTracks(new QueryOperation(QueryOperationKind.TimeBucket, BucketSeconds: 3600), Window, records);
        var count = StructuredQueryEvaluator.EvaluateTracks(new QueryOperation(QueryOperationKind.Count), Window, records);

        Assert.Equal("buckets", buckets.Kind);
        Assert.Equal([2L, 1, 0, 0, 0, 1], buckets.Buckets!.Select(bucket => bucket.Count));
        Assert.Equal(count.Value, buckets.Buckets!.Sum(bucket => bucket.Count));
        Assert.Equal(From, buckets.Buckets![0].StartUtc);
        Assert.Equal(Window.ToUtc, buckets.Buckets[^1].EndUtc);
    }

    [Fact]
    public void AWindowThatIsNotAWholeNumberOfBucketsEndsInOneShortBucket()
    {
        var window = new QueryWindow(From, From.AddMinutes(150));
        var result = StructuredQueryEvaluator.EvaluateTracks(
            new QueryOperation(QueryOperationKind.TimeBucket, BucketSeconds: 3600), window, [Track(1, CameraA, From.AddMinutes(149))]);
        Assert.Equal(3, result.Buckets!.Count);
        Assert.Equal((From.AddHours(2), From.AddMinutes(150), 1L), (result.Buckets[2].StartUtc, result.Buckets[2].EndUtc, result.Buckets[2].Count));
    }

    [Fact]
    public void TopBreaksTiesByKeyAndGroupByOrdersByKey()
    {
        var records = new[] { Track(1, CameraB, From), Track(2, CameraA, From), Track(3, CameraB, From), Track(4, CameraA, From) };
        var top = StructuredQueryEvaluator.EvaluateTracks(new QueryOperation(QueryOperationKind.Top, By: "camera", K: 1), Window, records);
        var groups = StructuredQueryEvaluator.EvaluateTracks(new QueryOperation(QueryOperationKind.GroupBy, By: "camera"), Window, records.Reverse().ToArray());

        Assert.Equal(CameraA.ToString("D"), Assert.Single(top.Groups!).Key);
        Assert.Equal([CameraA.ToString("D"), CameraB.ToString("D")], groups.Groups!.Select(group => group.Key));
        Assert.Equal([2L, 2], groups.Groups!.Select(group => group.Count));
    }

    [Fact]
    public void FindIsOrderedTotallyAndDisclosesTruncationWithTheFullTotal()
    {
        var records = new[] { Track(1, CameraA, From), Track(2, CameraA, From), Track(3, CameraA, From.AddMinutes(1)) };
        var newest = StructuredQueryEvaluator.EvaluateTracks(new QueryOperation(QueryOperationKind.Find, Limit: 2, Order: QueryOrder.Newest), Window, records);
        var oldest = StructuredQueryEvaluator.EvaluateTracks(new QueryOperation(QueryOperationKind.Find, Limit: 2, Order: QueryOrder.Oldest), Window, records.Reverse().ToArray());

        Assert.Equal([Id(3), Id(2)], newest.Tracks!.Select(row => row.TrackId));
        Assert.Equal([Id(1), Id(2)], oldest.Tracks!.Select(row => row.TrackId));
        Assert.Equal(new QueryTruncationResponse(true, 2, 3, 2), newest.Truncation);
    }

    [Fact]
    public void CountDistinctIgnoresRecordsWithoutTheField()
    {
        var events = new[]
        {
            Event(1, "line-crossing", Id(10)),
            Event(2, "zone-dwell", Id(10)),
            Event(3, "co-occurrence", null),
        };
        var result = StructuredQueryEvaluator.EvaluateEvents(new QueryOperation(QueryOperationKind.CountDistinct, Field: "track"), Window, events);
        Assert.Equal((1L, "track"), (result.Value!.Value, result.Dimension));
    }

    [Fact]
    public void CompareReportsBothCountsAndTheirDifference()
    {
        var result = StructuredQueryEvaluator.EvaluateTracks(
            new QueryOperation(QueryOperationKind.Compare, Baseline: new QueryWindow(From.AddDays(-1), From.AddDays(-1).AddHours(6))),
            Window,
            [Track(1, CameraA, From)],
            [Track(2, CameraA, From.AddDays(-1)), Track(3, CameraA, From.AddDays(-1))]);
        Assert.Equal(new QueryComparisonResponse(1, 2, -1), result.Comparison);
    }

    [Theory]
    [InlineData("{\"op\":\"count\"}", "withheld")]
    [InlineData("{\"op\":\"first\"}", "withheld")]
    [InlineData("{\"op\":\"top\",\"by\":\"camera\"}", "withheld")]
    [InlineData("{\"op\":\"find\"}", "rows")]
    public async Task IncompleteCoverageWithholdsEveryWholeScopeAnswerButKeepsRealRows(string operation, string kind)
    {
        var repository = new FakeRepository(complete: false);
        var outcome = await new StructuredQueryService(repository, TimeProvider.System).EvaluateAsync(Query(operation), default);

        Assert.Equal(200, outcome.StatusCode);
        Assert.Equal(kind, outcome.Envelope!.Result.Kind);
        Assert.False(outcome.Envelope.Coverage.Complete);
        if (kind == "withheld")
        {
            Assert.Null(outcome.Envelope.Result.Value);
            Assert.Equal(StructuredQueryService.CoverageIncompleteReason, outcome.Envelope.Result.Reason);
        }
        else
        {
            Assert.Single(outcome.Envelope.Result.Tracks!);
        }
    }

    [Fact]
    public async Task RequiredCompleteCoverageTurnsAnIncompleteAnswerIntoATypedRefusal()
    {
        var query = StructuredQueryParser.Parse(QueryText("{\"op\":\"find\"}", requireComplete: true)).Query!;
        var outcome = await new StructuredQueryService(new FakeRepository(complete: false), TimeProvider.System).EvaluateAsync(query, default);
        Assert.Equal((409, QueryRefusalCodes.CoverageIncomplete), (outcome.StatusCode, outcome.Refusal!.Code));
    }

    [Fact]
    public async Task TheEntityUnitIsEmptyWithItsReasonAndReadsNothing()
    {
        var repository = new FakeRepository(complete: true);
        var query = StructuredQueryParser.Parse("""
            {"contractVersion":"mavi-query-v1","unit":"entity",
             "where":{"timeWindow":{"fromUtc":"2026-09-21T08:00:00Z","toUtc":"2026-09-21T14:00:00Z"}},"operation":{"op":"count"}}
            """).Query!;
        var outcome = await new StructuredQueryService(repository, TimeProvider.System).EvaluateAsync(query, default);

        Assert.Equal(("empty", StructuredQueryService.EntityUnavailableReason), (outcome.Envelope!.Result.Kind, outcome.Envelope.Result.Reason));
        Assert.Null(outcome.Envelope.Result.Value);
        Assert.False(outcome.Envelope.Coverage.Complete);
        Assert.Equal(0, repository.Reads);
    }

    [Fact]
    public async Task ScopeTooLargeIsRefusedWithItsOwnStatus()
    {
        var repository = new FakeRepository(complete: true)
        {
            Refusal = new QueryRefusal(QueryRefusalCodes.QueryScopeTooLarge, "/where", "too many"),
        };
        var outcome = await new StructuredQueryService(repository, TimeProvider.System).EvaluateAsync(Query("{\"op\":\"count\"}"), default);
        Assert.Equal((422, QueryRefusalCodes.QueryScopeTooLarge), (outcome.StatusCode, outcome.Refusal!.Code));
    }

    private static StructuredQuery Query(string operation) => StructuredQueryParser.Parse(QueryText(operation)).Query!;

    private static string QueryText(string operation, bool requireComplete = false) =>
        "{\"contractVersion\":\"mavi-query-v1\",\"unit\":\"track\"," +
        "\"where\":{\"timeWindow\":{\"fromUtc\":\"2026-09-21T08:00:00Z\",\"toUtc\":\"2026-09-21T14:00:00Z\"}}," +
        "\"operation\":" + operation + ",\"requireCompleteCoverage\":" + (requireComplete ? "true" : "false") + "}";

    private static Guid Id(int value) => Guid.Parse($"00000000-0000-4000-8000-{value:D12}");

    private static QueryTrackRecord Track(int id, Guid cameraId, DateTimeOffset start) => new(
        Id(id), cameraId, cameraId == CameraA ? "A" : "B", "Camera", Id(900), Id(901), ObjectClass.Person, null,
        start, start.AddSeconds(10), 0, 10_000, 0.8, null);

    private static QueryEventRecord Event(int id, string rule, Guid? track) => new(
        Id(id), rule, 1, CameraA, "A", "Camera", Id(900), track, "Person", null, null, null, null, null, From, From, 0);

    private sealed class FakeRepository(bool complete) : IStructuredQueryRepository
    {
        public int Reads { get; private set; }

        public QueryRefusal? Refusal { get; init; }

        public Task<QueryRead<QueryTrackRecord>> ReadTracksAsync(
            QueryPredicates where, IReadOnlyList<QueryReadWindow> windows, QueryCapabilityIdentities identities, CancellationToken cancellationToken)
        {
            Reads++;
            if (Refusal is not null)
                return Task.FromResult(QueryRead.Refused<QueryTrackRecord>(Refusal));
            var coverage = new QueryCoverageComponentResponse("sceneAnalytics", "query", complete, CameraA);
            return Task.FromResult(new QueryRead<QueryTrackRecord>(
                null, 7, [], [.. windows.Select(_ => new QueryWindowRead<QueryTrackRecord>([Track(1, CameraA, From)], [coverage]))]));
        }

        public Task<QueryRead<QueryEventRecord>> ReadEventsAsync(
            QueryPredicates where, IReadOnlyList<QueryReadWindow> windows, CancellationToken cancellationToken)
        {
            Reads++;
            throw new NotSupportedException();
        }
    }
}
