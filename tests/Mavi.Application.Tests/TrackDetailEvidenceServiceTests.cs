using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests;

/// <summary>
/// How <see cref="TrackSearchService.GetDetailAsync"/> composes the Evidence Set read with
/// the Track and analytics reads (S1.3 plan §5, §13).
/// </summary>
public sealed class TrackDetailEvidenceServiceTests
{
    private static readonly DateTimeOffset At = new(2026, 9, 24, 8, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task AFoundTrackCarriesItsValidatedEvidenceSetReadOnce()
    {
        var representative = Observation(ObservationType.Representative, 0);
        var repository = new RecordingRepository(Row(representative.ObservationId), Analysed(), [representative]);

        var result = await Service(repository).GetDetailAsync(Guid.CreateVersion7(), TrackAnalyticsDetailRequest.Current, default);

        Assert.True(result.IsSuccess);
        Assert.NotNull(result.EvidenceSet);
        Assert.Same(representative, result.EvidenceSet.Representative);
        Assert.Equal(1, repository.EvidenceReads);
    }

    [Fact]
    public async Task ARefusedAnalyticsIdentityStaysA400AndNeverReadsEvidence()
    {
        // Even when the stored evidence is corrupt, a request the service refuses is
        // refused as before: the Evidence Set is read only for an answerable request.
        var repository = new RecordingRepository(
            Row(Guid.CreateVersion7()), TrackDetailAnalyticsResult.Invalid, [Observation(ObservationType.NearView, 0)]);

        var result = await Service(repository).GetDetailAsync(Guid.CreateVersion7(), TrackAnalyticsDetailRequest.Current, default);

        Assert.False(result.IsSuccess);
        Assert.Equal("track_search_invalid", result.ErrorCode);
        Assert.Equal(0, repository.EvidenceReads);
    }

    [Fact]
    public async Task AMissingTrackStaysA404AndNeverReadsEvidence()
    {
        var repository = new RecordingRepository(null, Analysed(), []);

        var result = await Service(repository).GetDetailAsync(Guid.CreateVersion7(), TrackAnalyticsDetailRequest.Current, default);

        Assert.True(result.IsSuccess);
        Assert.Null(result.Row);
        Assert.Equal(0, repository.EvidenceReads);
    }

    [Fact]
    public async Task ACorruptEvidenceSetOfAnAnswerableTrackThrowsTheInvariantFailure()
    {
        var representative = Observation(ObservationType.Representative, 0);
        var repository = new RecordingRepository(
            Row(representative.ObservationId), Analysed(), [representative, Observation(ObservationType.NearView, 2)]);

        var failure = await Assert.ThrowsAsync<TrackEvidenceSetInvariantException>(
            () => Service(repository).GetDetailAsync(Guid.CreateVersion7(), TrackAnalyticsDetailRequest.Current, default));

        Assert.Equal(TrackEvidenceSetInvariant.RankNotContiguous, failure.Invariant);
    }

    private static TrackSearchService Service(ITrackSearchRepository repository) =>
        new(repository, TimeProvider.System, TrackCursorSigningKey.CreateEphemeral());

    private static TrackEvidenceObservationRow Observation(ObservationType role, int rank) => new(
        Guid.CreateVersion7(), role, rank, 10 + rank, 1_000 + rank, At, 0.9, 0.8, 0.7,
        0.1f, 0.2f, 0.3f, 0.4f, Guid.CreateVersion7());

    private static TrackDetailRow Row(Guid? representativeObservationId) => new(
        Guid.CreateVersion7(), Guid.CreateVersion7(), Guid.CreateVersion7(), Guid.CreateVersion7(),
        "CAM-01", "North Gate", ObjectClass.Person, 1, 0, 8_000, At, At.AddSeconds(8), 8_000, 40, 0.9, 0.95,
        ReviewStatus.Unreviewed, "phase1-v1", null, null, null, null, At, At, At.AddMinutes(1), 60_000,
        1920, 1080, 25, 1, representativeObservationId, null);

    private static TrackDetailAnalyticsResult Analysed() => new(new TrackDetailAnalytics(
        null, null, "scene-analytics-v1", "NotConfigured", null, [], [], [], null, []));

    private sealed class RecordingRepository(
        TrackDetailRow? row,
        TrackDetailAnalyticsResult analytics,
        IReadOnlyList<TrackEvidenceObservationRow> evidence) : ITrackSearchRepository
    {
        public int EvidenceReads { get; private set; }

        public Task<TrackDetailRow?> GetDetailAsync(Guid trackId, CancellationToken cancellationToken) =>
            Task.FromResult(row);

        public Task<IReadOnlyList<TrackEvidenceObservationRow>> GetEvidenceSetAsync(
            Guid trackId, CancellationToken cancellationToken)
        {
            EvidenceReads++;
            return Task.FromResult(evidence);
        }

        public Task<TrackDetailAnalyticsResult?> GetDetailAnalyticsAsync(
            Guid trackId, TrackAnalyticsDetailRequest request, CancellationToken cancellationToken) =>
            Task.FromResult<TrackDetailAnalyticsResult?>(analytics);

        public Task<TrackSearchRepositoryPage> SearchAsync(
            TrackSearchQuery query, TrackCursorPosition? cursor, int take, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Not part of these scenarios.");

        public Task<TrackAnalyticsSearchRepositoryResult> SearchAnalyticsAsync(
            TrackSearchQuery query, TrackAnalyticsCursorPosition? cursor, int take, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Not part of these scenarios.");
    }
}
