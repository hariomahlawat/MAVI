using Mavi.Application.Modules.Events;
using Microsoft.Extensions.Logging.Abstractions;

namespace Mavi.Application.Tests.Events;

// ADR-025 §3: the sweep derives units with no derivation at the current catalogue
// version. A unit that fails every time must not hold the units behind it back.
public sealed class EventSweepTests
{
    [Fact]
    public async Task UnitsThatAlwaysFailDoNotStarveTheUnitsBehindThem()
    {
        var repository = new SweepRepository(unitCount: 5, failing: [Id(1), Id(2), Id(3)]);
        var service = new AnalyticEventService(repository, TimeProvider.System, NullLogger<AnalyticEventService>.Instance);

        // A budget of two, and the three oldest units fail: the sweep pages past them.
        Assert.Equal(2, await service.DeriveDueAsync(2, default));
        Assert.Equal([Id(4), Id(5)], repository.Derived);
        Assert.Equal([Id(1), Id(2), Id(3), Id(4), Id(5)], repository.Attempted);

        // The next cycle retries the failures and finds nothing else to do.
        Assert.Equal(0, await service.DeriveDueAsync(2, default));
    }

    [Fact]
    public async Task TheBudgetCountsDerivationsNotAttempts()
    {
        var repository = new SweepRepository(unitCount: 5, failing: []);
        var service = new AnalyticEventService(repository, TimeProvider.System, NullLogger<AnalyticEventService>.Instance);

        Assert.Equal(3, await service.DeriveDueAsync(3, default));
        Assert.Equal([Id(1), Id(2), Id(3)], repository.Derived);
    }

    private static Guid Id(int value) => new($"00000000-0000-0000-0000-{value:D12}");

    private sealed class SweepRepository(int unitCount, IReadOnlyCollection<Guid> failing) : IAnalyticEventRepository
    {
        private readonly List<EventDerivationCandidate> units =
            [.. Enumerable.Range(1, unitCount).Select(value => new EventDerivationCandidate(value, Id(value)))];

        public List<Guid> Derived { get; } = [];

        public List<Guid> Attempted { get; } = [];

        public Task<IReadOnlyList<EventDerivationCandidate>> ListUnitsAwaitingDerivationAsync(
            string catalogueVersion,
            EventDerivationCandidate? after,
            int batchSize,
            CancellationToken cancellationToken)
        {
            IReadOnlyList<EventDerivationCandidate> page =
            [
                .. units
                    .Where(unit => !Derived.Contains(unit.SceneAnalysisId))
                    .Where(unit => after is null || unit.VisibilitySequence > after.VisibilitySequence)
                    .Take(batchSize),
            ];
            return Task.FromResult(page);
        }

        public Task<EventDerivationOutcome> DeriveAsync(
            Guid sceneAnalysisId,
            RuleCatalogueDefinition catalogue,
            DateTimeOffset nowUtc,
            CancellationToken cancellationToken)
        {
            Attempted.Add(sceneAnalysisId);
            if (failing.Contains(sceneAnalysisId))
                throw new InvalidOperationException("This unit cannot be derived.");
            Derived.Add(sceneAnalysisId);
            return Task.FromResult(EventDerivationOutcome.Derived);
        }

        public Task<EventDerivationInput?> ReadDerivationInputAsync(Guid sceneAnalysisId, CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<AnalyticEventTimelineResult> ReadTimelineAsync(
            AnalyticEventTimelineQuery query,
            RuleCatalogueDefinition catalogue,
            CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<AnalyticEventDetailView?> GetEventAsync(Guid eventId, CancellationToken cancellationToken) =>
            throw new NotSupportedException();
    }
}
