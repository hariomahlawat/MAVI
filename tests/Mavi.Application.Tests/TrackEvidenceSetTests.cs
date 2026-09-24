using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests;

/// <summary>
/// The Track-detail read seam (S1.3 plan §5.3). These pin the shapes the database cannot
/// hold (a duplicate or negative rank, rows out of rank order) as well as those it can,
/// and that a valid set is returned exactly as read.
/// </summary>
public sealed class TrackEvidenceSetTests
{
    private static TrackEvidenceObservationRow Row(ObservationType role, int rank, Guid? id = null) => new(
        id ?? Guid.CreateVersion7(),
        role,
        rank,
        SourceFrameNumber: 10 + rank,
        VideoOffsetMs: 1_000 + (rank * 100),
        TimestampUtc: new DateTimeOffset(2026, 9, 24, 8, 0, 0, TimeSpan.Zero),
        Confidence: 0.9,
        QualityScore: 0.8,
        SelectionScore: 0.7,
        BoundingBoxX: 0.1f,
        BoundingBoxY: 0.2f,
        BoundingBoxWidth: 0.3f,
        BoundingBoxHeight: 0.4f,
        EvidenceArtifactId: Guid.CreateVersion7());

    private static TrackEvidenceObservationRow[] Full() =>
    [
        Row(ObservationType.Representative, 0),
        Row(ObservationType.NearView, 1),
        Row(ObservationType.EarlyDiverse, 2),
        Row(ObservationType.LateDiverse, 3),
    ];

    private static TrackEvidenceSetInvariant Violation(Guid? pointer, params TrackEvidenceObservationRow[] rows) =>
        Assert.Throws<TrackEvidenceSetInvariantException>(() => TrackEvidenceSet.FromPersisted(pointer, rows)).Invariant;

    // --- valid ------------------------------------------------------------------------

    [Fact]
    public void AFullSetIsReturnedExactlyAsReadWithRankZeroAsTheRepresentative()
    {
        var rows = Full();

        var set = TrackEvidenceSet.FromPersisted(rows[0].ObservationId, rows);

        Assert.Equal(rows, set.Observations);
        Assert.Same(rows[0], set.Representative);
    }

    [Theory]
    [InlineData(new[] { ObservationType.Representative })]
    [InlineData(new[] { ObservationType.Representative, ObservationType.NearView })]
    [InlineData(new[] { ObservationType.Representative, ObservationType.LateDiverse })]
    [InlineData(new[] { ObservationType.Representative, ObservationType.EarlyDiverse, ObservationType.LateDiverse })]
    public void AnyContiguousSubsetInCanonicalOrderIsValid(ObservationType[] roles)
    {
        var rows = roles.Select((role, rank) => Row(role, rank)).ToArray();

        var set = TrackEvidenceSet.FromPersisted(rows[0].ObservationId, rows);

        Assert.Equal(rows, set.Observations);
    }

    [Fact]
    public void NoPointerAndNoObservationsIsTheReadableLegacyShape()
    {
        var set = TrackEvidenceSet.FromPersisted(null, []);

        Assert.Empty(set.Observations);
        Assert.Null(set.Representative);
    }

    // --- ranks ----------------------------------------------------------------------

    [Fact]
    public void ARankGapIsRefused()
    {
        var representative = Row(ObservationType.Representative, 0);
        Assert.Equal(
            TrackEvidenceSetInvariant.RankNotContiguous,
            Violation(representative.ObservationId, representative, Row(ObservationType.NearView, 2)));
    }

    [Fact]
    public void ADuplicateRankIsRefused()
    {
        var representative = Row(ObservationType.Representative, 0);
        Assert.Equal(
            TrackEvidenceSetInvariant.RankNotContiguous,
            Violation(
                representative.ObservationId,
                representative,
                Row(ObservationType.NearView, 1),
                Row(ObservationType.EarlyDiverse, 1)));
    }

    [Fact]
    public void ANegativeRankIsRefused()
    {
        var representative = Row(ObservationType.Representative, -1);
        Assert.Equal(
            TrackEvidenceSetInvariant.RankNotContiguous,
            Violation(representative.ObservationId, representative));
    }

    [Fact]
    public void RowsOutOfRankOrderAreRefusedRatherThanSorted()
    {
        // A valid set once sorted by rank. The seam checks the rank at each position of
        // what it was given; it does not re-sort a read that came back out of order.
        var rows = Full();
        Assert.Equal(
            TrackEvidenceSetInvariant.RankNotContiguous,
            Violation(rows[0].ObservationId, rows[1], rows[0], rows[2], rows[3]));
    }

    [Fact]
    public void MoreThanFourObservationsIsRefusedRatherThanTruncated()
    {
        var rows = Full().Append(Row(ObservationType.LateDiverse, 4)).ToArray();
        Assert.Equal(TrackEvidenceSetInvariant.TooManyObservations, Violation(rows[0].ObservationId, rows));
    }

    // --- roles ----------------------------------------------------------------------

    [Fact]
    public void RankOrderContradictingCanonicalRoleOrderIsRefusedRatherThanSortedByRole()
    {
        // Contiguous ranks and Representative first. Sorting by role would turn this into
        // the valid Representative, NearView, LateDiverse. It must not be made to look
        // valid.
        var representative = Row(ObservationType.Representative, 0);
        Assert.Equal(
            TrackEvidenceSetInvariant.RoleOrderViolated,
            Violation(
                representative.ObservationId,
                representative,
                Row(ObservationType.LateDiverse, 1),
                Row(ObservationType.NearView, 2)));
    }

    [Fact]
    public void ASupplementalAtRankZeroIsRefused()
    {
        var nearView = Row(ObservationType.NearView, 0);
        Assert.Equal(TrackEvidenceSetInvariant.RoleOrderViolated, Violation(nearView.ObservationId, nearView));
    }

    [Fact]
    public void ARepeatedRoleIsRefused()
    {
        var representative = Row(ObservationType.Representative, 0);
        Assert.Equal(
            TrackEvidenceSetInvariant.RoleOrderViolated,
            Violation(
                representative.ObservationId,
                representative,
                Row(ObservationType.NearView, 1),
                Row(ObservationType.NearView, 2)));
    }

    [Fact]
    public void ARepresentativeAfterRankZeroIsRefused()
    {
        var representative = Row(ObservationType.Representative, 0);
        Assert.Equal(
            TrackEvidenceSetInvariant.RoleOrderViolated,
            Violation(representative.ObservationId, representative, Row(ObservationType.Representative, 1)));
    }

    [Fact]
    public void ARoleOutsideTheVocabularyIsRefused()
    {
        var representative = Row(ObservationType.Representative, 0);
        Assert.Equal(
            TrackEvidenceSetInvariant.RoleOrderViolated,
            Violation(representative.ObservationId, representative, Row((ObservationType)99, 1)));
    }

    // --- the Representative pointer -------------------------------------------------

    [Fact]
    public void APointerToANonRankZeroObservationIsRefused()
    {
        var rows = Full();
        Assert.Equal(TrackEvidenceSetInvariant.RepresentativePointerMismatch, Violation(rows[1].ObservationId, rows));
    }

    [Fact]
    public void APointerToAnObservationOutsideTheSetIsRefused()
    {
        // Another Track's Observation, or a stale one: not in this Track's collection.
        Assert.Equal(TrackEvidenceSetInvariant.RepresentativePointerMismatch, Violation(Guid.CreateVersion7(), Full()));
    }

    [Fact]
    public void APointerWithNoObservationsIsRefusedNotReadAsLegacy()
    {
        Assert.Equal(TrackEvidenceSetInvariant.RepresentativePointerMismatch, Violation(Guid.CreateVersion7()));
    }

    [Fact]
    public void ObservationsWithoutAPointerAreRefusedNotReadAsLegacy()
    {
        Assert.Equal(TrackEvidenceSetInvariant.RepresentativePointerMissing, Violation(null, Full()));
    }

    [Fact]
    public void TheFailureIsAnInternalInvariantFailureNotAValidationError()
    {
        var exception = Assert.Throws<TrackEvidenceSetInvariantException>(
            () => TrackEvidenceSet.FromPersisted(null, Full()));

        // An InvalidOperationException, never the DomainValidationException that request
        // validation maps to 400.
        Assert.IsAssignableFrom<InvalidOperationException>(exception);
        Assert.IsNotAssignableFrom<Mavi.Domain.Common.DomainValidationException>(exception);
        Assert.Equal("track_evidence_set_invariant_violated: RepresentativePointerMissing", exception.Message);
    }

    // --- one Representative authority and one role order ------------------------------

    [Fact]
    public void TheTrackDetailRowCarriesNoRepresentativePayloadOnlyThePointer()
    {
        // The removed Representative join projected frame, offset, time, confidence,
        // quality, box and crop onto the detail row. Carrying any of them again would be a
        // second Representative read source beside the Evidence Set (S1.3 plan §5.1).
        var members = typeof(TrackDetailRow).GetProperties().Select(property => property.Name).ToArray();

        Assert.Contains(nameof(TrackDetailRow.RepresentativeObservationId), members);
        Assert.DoesNotContain(members, name =>
            (name.StartsWith("Representative", StringComparison.Ordinal) &&
             name != nameof(TrackDetailRow.RepresentativeObservationId)) ||
            name.StartsWith("BoundingBox", StringComparison.Ordinal) ||
            name.Contains("Thumbnail", StringComparison.Ordinal) ||
            (name.Contains("Observation", StringComparison.Ordinal) &&
             name != nameof(TrackDetailRow.RepresentativeObservationId)));
    }

    [Fact]
    public void TheCanonicalRoleOrderIsTheDeclaredEvidenceRoleOrder()
    {
        Assert.Equal(
            [ObservationType.Representative, ObservationType.NearView, ObservationType.EarlyDiverse, ObservationType.LateDiverse],
            EvidenceRoleOrder.Canonical);
        Assert.Equal(Enum.GetValues<ObservationType>(), EvidenceRoleOrder.Canonical);
        Assert.Equal(-1, EvidenceRoleOrder.PositionOf((ObservationType)99));
        Assert.Equal(Observation.MaximumEvidenceRank + 1, TrackEvidenceSet.MaximumCount);
    }
}
