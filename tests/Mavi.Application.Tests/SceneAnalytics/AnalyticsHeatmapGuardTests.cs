using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Contracts.Api.Analytics;
using Microsoft.Extensions.Logging.Abstractions;

namespace Mavi.Application.Tests.SceneAnalytics;

/// <summary>
/// The heatmap work bounds must be refusals to start work, not conclusions drawn
/// from work already done (plan §5.5).
/// </summary>
/// <remarks>
/// These tests assert <b>call ordering</b>, not status codes. The evidence reader and
/// the candidate listing both throw if they are reached at all, so a guard that ran
/// after the fan-out would fail here even though it returned the right problem.
/// </remarks>
public sealed class AnalyticsHeatmapGuardTests
{
    private static readonly Guid Camera = Guid.Parse("44444444-4444-4444-8444-444444444444");
    private static readonly DateTimeOffset From = new(2026, 9, 22, 9, 0, 0, TimeSpan.Zero);

    private static AnalyticsHeatmapQuery Query() =>
        new(Camera, From, From.AddHours(1), null, 64, null);

    private static AnalyticsResolvedIdentity Identity() =>
        new(Camera, Guid.NewGuid(), 4, "scene-analytics-v1", 42);

    private static TrackAnalyticsCoverage Coverage() =>
        new(Guid.NewGuid(), "scene-analytics-v1", 1, 0, 0, 0, 0, 0, 0, 0);

    /// <summary>A reader that fails the test simply by being called.</summary>
    private sealed class ForbiddenEvidenceReader : IHeatmapEvidenceReader
    {
        public int Opens { get; private set; }

        public Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken)
        {
            Opens++;
            throw new InvalidOperationException(
                "Trajectory evidence was opened although the scope should have been refused first.");
        }
    }

    private sealed class ScopeRepository(AnalyticsHeatmapScope scope) : IAnalyticsAggregateRepository
    {
        public int CandidateListings { get; private set; }

        public Task<AnalyticsAggregateResult> AggregateAsync(
            AnalyticsAggregateQuery query,
            CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<AnalyticsHeatmapScope> ResolveHeatmapScopeAsync(
            AnalyticsHeatmapQuery query,
            CancellationToken cancellationToken) => Task.FromResult(scope);

        public Task<IReadOnlyList<HeatmapCandidateTrack>> ListHeatmapCandidatesAsync(
            AnalyticsHeatmapQuery query,
            AnalyticsResolvedIdentity identity,
            CancellationToken cancellationToken)
        {
            CandidateListings++;
            throw new InvalidOperationException(
                "Heatmap candidates were listed although the scope should have been refused first.");
        }
    }

    private static (AnalyticsAggregateService Service, ScopeRepository Repository, ForbiddenEvidenceReader Evidence)
        Build(int coveredRuns, int candidateTracks)
    {
        var repository = new ScopeRepository(new AnalyticsHeatmapScope(
            AnalyticsFailure.None,
            Identity(),
            Coverage(),
            coveredRuns,
            candidateTracks));
        var evidence = new ForbiddenEvidenceReader();
        return (
            new AnalyticsAggregateService(repository, evidence, NullLogger<AnalyticsAggregateService>.Instance),
            repository,
            evidence);
    }

    [Fact]
    public async Task TooManyCoveredRunsIsRefusedBeforeAnyEvidenceOrCandidateWork()
    {
        var (service, repository, evidence) = Build(
            AnalyticsQueryRules.MaximumHeatmapRuns + 1,
            candidateTracks: 10);

        var result = await service.HeatmapAsync(Query(), CancellationToken.None);

        Assert.Equal(AnalyticsFailure.ScopeTooLarge, result.Failure);
        Assert.Equal(AnalyticsQueryRules.RunsDimension, result.ExceededDimension);
        Assert.Equal(AnalyticsQueryRules.MaximumHeatmapRuns, result.ExceededLimit);
        // The point of the test: nothing expensive ran.
        Assert.Equal(0, evidence.Opens);
        Assert.Equal(0, repository.CandidateListings);
    }

    [Fact]
    public async Task TooManyCandidateTracksIsRefusedBeforeAnyEvidenceOrCandidateWork()
    {
        var (service, repository, evidence) = Build(
            coveredRuns: 10,
            AnalyticsQueryRules.MaximumHeatmapTracks + 1);

        var result = await service.HeatmapAsync(Query(), CancellationToken.None);

        Assert.Equal(AnalyticsFailure.ScopeTooLarge, result.Failure);
        Assert.Equal(AnalyticsQueryRules.TracksDimension, result.ExceededDimension);
        Assert.Equal(AnalyticsQueryRules.MaximumHeatmapTracks, result.ExceededLimit);
        Assert.Equal(0, evidence.Opens);
        Assert.Equal(0, repository.CandidateListings);
    }

    [Fact]
    public async Task ExactlyTheLimitIsAcceptedSoTheBoundIsInclusive()
    {
        // At the limit the request proceeds, which is what makes the rejections above
        // a bound rather than an off-by-one.
        var (service, repository, evidence) = Build(
            AnalyticsQueryRules.MaximumHeatmapRuns,
            AnalyticsQueryRules.MaximumHeatmapTracks);

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => service.HeatmapAsync(Query(), CancellationToken.None));

        Assert.Equal(1, repository.CandidateListings);
        Assert.Equal(0, evidence.Opens);
    }

    [Fact]
    public async Task TheRunBoundIsCheckedBeforeTheTrackBound()
    {
        // Both exceeded: the caller is told to narrow the coarser dimension first.
        var (service, _, _) = Build(
            AnalyticsQueryRules.MaximumHeatmapRuns + 1,
            AnalyticsQueryRules.MaximumHeatmapTracks + 1);

        var result = await service.HeatmapAsync(Query(), CancellationToken.None);

        Assert.Equal(AnalyticsQueryRules.RunsDimension, result.ExceededDimension);
    }

    [Fact]
    public async Task ARefusalStillCarriesTheResolvedIdentityAndCoverage()
    {
        // The scope was resolved; only the work was refused. An operator narrowing the
        // window is owed the coverage that made this scope too large.
        var (service, _, _) = Build(AnalyticsQueryRules.MaximumHeatmapRuns + 1, 1);

        var result = await service.HeatmapAsync(Query(), CancellationToken.None);

        Assert.NotNull(result.Identity);
        Assert.NotNull(result.Coverage);
    }
}
