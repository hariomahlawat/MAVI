using Mavi.Domain.Common;
using Mavi.Domain.Intelligence;

namespace Mavi.Domain.Tests;

public sealed class ObservationEvidenceSetTests
{
    private static readonly DateTimeOffset Start = new(2026, 9, 23, 6, 0, 0, TimeSpan.Zero);

    [Theory]
    [InlineData(ObservationType.Representative, 0)]
    [InlineData(ObservationType.NearView, 1)]
    [InlineData(ObservationType.EarlyDiverse, 2)]
    [InlineData(ObservationType.LateDiverse, 3)]
    [InlineData(ObservationType.LateDiverse, 1)]
    public void EveryRoleIsCreatedAtALegalRank(ObservationType role, int rank)
    {
        var observation = Create(role, rank, selectionScore: .4);

        Assert.Equal(role, observation.ObservationType);
        Assert.Equal(rank, observation.EvidenceRank);
        Assert.Equal(.4, observation.SelectionScore);
    }

    [Theory]
    [InlineData(ObservationType.Representative, 1, .5)]
    [InlineData(ObservationType.NearView, 0, .5)]
    [InlineData(ObservationType.NearView, -1, .5)]
    [InlineData(ObservationType.NearView, 4, .5)]
    [InlineData(ObservationType.NearView, 1, -.01)]
    [InlineData(ObservationType.NearView, 1, 1.01)]
    [InlineData(ObservationType.NearView, 1, double.NaN)]
    [InlineData((ObservationType)99, 1, .5)]
    public void IllegalRoleRankOrSelectionScoreIsRejected(ObservationType role, int rank, double selectionScore) =>
        Assert.Throws<DomainValidationException>(() => Create(role, rank, selectionScore));

    [Fact]
    public void EvidenceArtifactAttachmentIsIdempotentButNeverReassigned()
    {
        var observation = Create(ObservationType.NearView, 1, .5);
        var artifact = Guid.CreateVersion7();

        observation.AttachEvidenceArtifact(artifact);
        observation.AttachEvidenceArtifact(artifact);

        Assert.Equal(artifact, observation.ThumbnailArtifactId);
        Assert.Throws<DomainValidationException>(() => observation.AttachEvidenceArtifact(Guid.CreateVersion7()));
        Assert.Throws<DomainValidationException>(() => Create(ObservationType.NearView, 1, .5).AttachEvidenceArtifact(Guid.Empty));
    }

    private static Observation Create(ObservationType role, int rank, double selectionScore) =>
        Observation.Create(Guid.CreateVersion7(), role, 10, 400, Start, .1f, .2f, .3f, .4f, .9, .8, rank, selectionScore, Start);
}
