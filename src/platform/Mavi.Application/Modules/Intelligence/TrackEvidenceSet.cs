using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>One accepted Observation of a Track's Evidence Set, as persisted.</summary>
/// <remarks>
/// <paramref name="EvidenceArtifactId"/> is the Observation's crop (a historical
/// <c>Thumbnail</c> or a v3 <c>EvidenceCrop</c>). It is stored in the column still
/// named <c>thumbnail_artifact_id</c>.
/// </remarks>
public sealed record TrackEvidenceObservationRow(
    Guid ObservationId,
    ObservationType Role,
    int EvidenceRank,
    long SourceFrameNumber,
    long VideoOffsetMs,
    DateTimeOffset TimestampUtc,
    double Confidence,
    double QualityScore,
    double SelectionScore,
    float BoundingBoxX,
    float BoundingBoxY,
    float BoundingBoxWidth,
    float BoundingBoxHeight,
    Guid? EvidenceArtifactId);

/// <summary>
/// A Track's Evidence Set as the read side exposes it: the one authoritative source for
/// the Track's evidence, and for its Representative (S1.3 plan D1, §5.3).
/// </summary>
/// <remarks>
/// <para>
/// The Representative is not a second projection. It is always
/// <see cref="Observations"/>[0], and the Track's own
/// <c>RepresentativeObservationId</c> is checked against it rather than read beside it.
/// </para>
/// <para>
/// <see cref="FromPersisted"/> checks the same contract the v3 completion validator
/// enforces on write. The database enforces only part of it (rank 0..3,
/// Representative ⇔ rank 0, unique rank and role per Track), so contiguity, role order
/// and the Track-local pointer are checked here. A violation is never repaired, re-sorted
/// or trimmed. It throws <see cref="TrackEvidenceSetInvariantException"/>.
/// </para>
/// </remarks>
public sealed class TrackEvidenceSet
{
    /// <summary>Most Observations an Evidence Set can hold: one per role.</summary>
    public static int MaximumCount => EvidenceRoleOrder.Canonical.Count;

    private TrackEvidenceSet(IReadOnlyList<TrackEvidenceObservationRow> observations) =>
        Observations = observations;

    /// <summary>
    /// A Track with no Evidence Set at all: the legacy shape, with no Representative
    /// relation and no Observations. It stays readable.
    /// </summary>
    public static TrackEvidenceSet LegacyEmpty { get; } = new([]);

    /// <summary>The accepted Observations in rank order, which is also canonical role order.</summary>
    public IReadOnlyList<TrackEvidenceObservationRow> Observations { get; }

    /// <summary>Rank 0, or null for the legacy empty shape.</summary>
    public TrackEvidenceObservationRow? Representative => Observations.Count == 0 ? null : Observations[0];

    /// <summary>
    /// Validates a Track's persisted Evidence Set and returns it unchanged.
    /// </summary>
    /// <param name="representativeObservationId">The Track's own <c>RepresentativeObservationId</c>.</param>
    /// <param name="observationsByRank">
    /// Every Observation of this Track, as read, ordered by <c>EvidenceRank</c>. The
    /// order is not trusted: the rank at each position is checked.
    /// </param>
    /// <exception cref="TrackEvidenceSetInvariantException">The persisted set breaks the contract.</exception>
    public static TrackEvidenceSet FromPersisted(
        Guid? representativeObservationId,
        IReadOnlyList<TrackEvidenceObservationRow> observationsByRank)
    {
        ArgumentNullException.ThrowIfNull(observationsByRank);

        if (observationsByRank.Count == 0)
        {
            // No Observations and no pointer is the legacy shape. A pointer with no
            // Observations of this Track names someone else's Observation, or nothing.
            return representativeObservationId is null
                ? LegacyEmpty
                : throw new TrackEvidenceSetInvariantException(TrackEvidenceSetInvariant.RepresentativePointerMismatch);
        }

        if (observationsByRank.Count > MaximumCount)
            throw new TrackEvidenceSetInvariantException(TrackEvidenceSetInvariant.TooManyObservations);

        var previousPosition = -1;
        for (var index = 0; index < observationsByRank.Count; index++)
        {
            var observation = observationsByRank[index]
                ?? throw new ArgumentException("Observation rows must not be null.", nameof(observationsByRank));

            // Exactly 0..n−1 at their positions: no gap, no duplicate, nothing out of
            // range, and nothing out of rank order.
            if (observation.EvidenceRank != index)
                throw new TrackEvidenceSetInvariantException(TrackEvidenceSetInvariant.RankNotContiguous);

            // Strictly increasing in canonical role order. That also makes the
            // Representative unique and rank 0, and every role single-valued.
            var position = EvidenceRoleOrder.PositionOf(observation.Role);
            if (position < 0 || position <= previousPosition ||
                (index == 0) != (observation.Role == ObservationType.Representative))
                throw new TrackEvidenceSetInvariantException(TrackEvidenceSetInvariant.RoleOrderViolated);
            previousPosition = position;
        }

        // The Track's pointer must be this Track's rank 0: never another Track's
        // Observation, another rank, or absent while Observations exist.
        if (representativeObservationId is null)
            throw new TrackEvidenceSetInvariantException(TrackEvidenceSetInvariant.RepresentativePointerMissing);
        if (representativeObservationId.Value != observationsByRank[0].ObservationId)
            throw new TrackEvidenceSetInvariantException(TrackEvidenceSetInvariant.RepresentativePointerMismatch);

        return new TrackEvidenceSet(observationsByRank);
    }
}

/// <summary>Which part of the Evidence Set contract a persisted set broke.</summary>
public enum TrackEvidenceSetInvariant
{
    TooManyObservations,
    RankNotContiguous,
    RoleOrderViolated,
    RepresentativePointerMissing,
    RepresentativePointerMismatch,
}

/// <summary>
/// A Track's persisted Evidence Set breaks the read contract. This is an internal
/// integrity failure (HTTP 500), never a not-found or a bad request, and never a
/// partially repaired answer.
/// </summary>
public sealed class TrackEvidenceSetInvariantException(TrackEvidenceSetInvariant invariant)
    : InvalidOperationException($"track_evidence_set_invariant_violated: {invariant}")
{
    public TrackEvidenceSetInvariant Invariant { get; } = invariant;
}
