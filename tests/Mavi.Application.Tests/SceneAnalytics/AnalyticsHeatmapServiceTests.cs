using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Microsoft.Extensions.Logging.Abstractions;

namespace Mavi.Application.Tests.SceneAnalytics;

/// <summary>
/// Heatmap evidence semantics: which samples contribute, and what happens when
/// evidence an analysed unit promised cannot be read (plan §5.1).
/// </summary>
public sealed class AnalyticsHeatmapServiceTests
{
    private static readonly Guid Camera = Guid.Parse("55555555-5555-4555-8555-555555555555");
    private static readonly DateTimeOffset From = new(2026, 9, 22, 9, 0, 0, TimeSpan.Zero);
    private static readonly DateTimeOffset To = From.AddMinutes(10);

    /// <summary>The recording started five minutes before the window opens.</summary>
    private static readonly DateTimeOffset RecordingStart = From.AddMinutes(-5);

    private static AnalyticsHeatmapQuery Query(int gridWidth = 16) =>
        new(Camera, From, To, null, gridWidth, null);

    private sealed class StubRepository(IReadOnlyList<HeatmapCandidateTrack> candidates) : IAnalyticsAggregateRepository
    {
        public Task<AnalyticsAggregateResult> AggregateAsync(
            AnalyticsAggregateQuery query,
            CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task<AnalyticsHeatmapScope> ResolveHeatmapScopeAsync(
            AnalyticsHeatmapQuery query,
            CancellationToken cancellationToken) =>
            Task.FromResult(new AnalyticsHeatmapScope(
                AnalyticsFailure.None,
                new AnalyticsResolvedIdentity(Camera, Guid.NewGuid(), 4, "scene-analytics-v1", 7),
                new TrackAnalyticsCoverage(Guid.NewGuid(), "scene-analytics-v1", 1, 0, 0, 0, 0, 0, candidates.Count, 0),
                1,
                candidates.Count));

        public Task<IReadOnlyList<HeatmapCandidateTrack>> ListHeatmapCandidatesAsync(
            AnalyticsHeatmapQuery query,
            AnalyticsResolvedIdentity identity,
            CancellationToken cancellationToken) => Task.FromResult(candidates);
    }

    private sealed class StubEvidence(Dictionary<string, byte[]?> payloads) : IHeatmapEvidenceReader
    {
        public List<string> Opened { get; } = [];

        public Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken)
        {
            Opened.Add(storageKey);
            return Task.FromResult(payloads.TryGetValue(storageKey, out var payload) ? payload : null);
        }
    }

    private static AnalyticsAggregateService Build(
        IReadOnlyList<HeatmapCandidateTrack> candidates,
        Dictionary<string, byte[]?> payloads,
        out StubEvidence evidence)
    {
        evidence = new StubEvidence(payloads);
        return new AnalyticsAggregateService(
            new StubRepository(candidates),
            evidence,
            NullLogger<AnalyticsAggregateService>.Instance);
    }

    private static HeatmapCandidateTrack Candidate(string key) =>
        new(Guid.NewGuid(), RecordingStart, key);

    [Fact]
    public async Task OnlySamplesInsideTheWindowContributeEvenWhenTheTrackOverlapsIt()
    {
        // The Track straddles the window. Offsets are media-relative: the recording
        // started five minutes early, so offset 300000 is exactly fromUtc.
        var payload = MsgPackWriter.Trajectory(
            (0, 0.1, 0.1),               // 08:55 — before the window
            (299_999, 0.2, 0.2),         // one millisecond before fromUtc
            (300_000, 0.5, 0.5),         // exactly fromUtc — inside
            (600_000, 0.6, 0.6),         // 09:05 — inside
            (900_000, 0.9, 0.9),         // exactly toUtc — outside, half-open
            (960_000, 0.95, 0.95));      // after the window

        var candidate = Candidate("a");
        var service = Build([candidate], new Dictionary<string, byte[]?> { ["a"] = payload }, out _);

        var result = await service.HeatmapAsync(Query(), CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(2, result.Grid!.SampleCount);
        Assert.Equal(1, result.TrackCount);
    }

    [Fact]
    public async Task ATrackWhoseSamplesAllFallOutsideTheWindowContributesNothing()
    {
        var payload = MsgPackWriter.Trajectory((0, 0.1, 0.1), (1_000, 0.2, 0.2));
        var service = Build([Candidate("a")], new Dictionary<string, byte[]?> { ["a"] = payload }, out _);

        var result = await service.HeatmapAsync(Query(), CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(0, result.Grid!.SampleCount);
        // It is not a contributing Track: it contributed no samples.
        Assert.Equal(0, result.TrackCount);
        Assert.Equal(0, result.Grid.MaxCellValue);
    }

    [Fact]
    public async Task MissingEvidenceForAnAnalysedTrackFailsRatherThanThinningTheMap()
    {
        var good = MsgPackWriter.Trajectory((300_000, 0.5, 0.5), (360_000, 0.5, 0.5));
        var service = Build(
            [Candidate("a"), Candidate("missing")],
            new Dictionary<string, byte[]?> { ["a"] = good },
            out _);

        var result = await service.HeatmapAsync(Query(), CancellationToken.None);

        Assert.Equal(AnalyticsFailure.EvidenceUnreadable, result.Failure);
        Assert.Null(result.Grid);
    }

    [Fact]
    public async Task CorruptEvidenceForAnAnalysedTrackFailsRatherThanBeingSkipped()
    {
        var service = Build(
            [Candidate("bad")],
            new Dictionary<string, byte[]?> { ["bad"] = [0x01, 0x02, 0x03] },
            out _);

        var result = await service.HeatmapAsync(Query(), CancellationToken.None);

        Assert.Equal(AnalyticsFailure.EvidenceUnreadable, result.Failure);
    }

    [Fact]
    public async Task EachArtefactIsOpenedExactlyOnce()
    {
        // Sequential and bounded: no candidate is read twice, and nothing fans out.
        var payload = MsgPackWriter.Trajectory((300_000, 0.5, 0.5), (360_000, 0.5, 0.5));
        var service = Build(
            [Candidate("a"), Candidate("b"), Candidate("c")],
            new Dictionary<string, byte[]?> { ["a"] = payload, ["b"] = payload, ["c"] = payload },
            out var evidence);

        await service.HeatmapAsync(Query(), CancellationToken.None);

        Assert.Equal(["a", "b", "c"], evidence.Opened);
    }

    [Fact]
    public async Task TheSameEvidenceAlwaysProducesTheSameMatrix()
    {
        var payload = MsgPackWriter.Trajectory(
            (300_000, 0.1, 0.2), (360_000, 0.4, 0.5), (420_000, 0.9, 0.95));

        async Task<IReadOnlyList<int>> RunAsync()
        {
            var service = Build([Candidate("a")], new Dictionary<string, byte[]?> { ["a"] = payload }, out _);
            var result = await service.HeatmapAsync(Query(32), CancellationToken.None);
            return result.Grid!.Values;
        }

        Assert.Equal(await RunAsync(), await RunAsync());
    }

    [Fact]
    public async Task TheResponseCarriesTheResolvedIdentityAndGridShape()
    {
        var payload = MsgPackWriter.Trajectory((300_000, 0.5, 0.5), (360_000, 0.5, 0.5));
        var service = Build([Candidate("a")], new Dictionary<string, byte[]?> { ["a"] = payload }, out _);

        var query = Query(128);
        var result = await service.HeatmapAsync(query, CancellationToken.None);
        var response = AnalyticsAggregateService.ToResponse(query, result);

        Assert.Equal(7, response.SnapshotVisibilitySequence);
        Assert.Equal(128, response.GridWidth);
        Assert.Equal(72, response.GridHeight);
        Assert.Equal(128 * 72, response.Values.Count);
        Assert.Equal(response.SampleCount, response.Values.Sum());
        Assert.Equal(From, response.FromUtc);
        Assert.Equal(To, response.ToUtc);
    }
}
