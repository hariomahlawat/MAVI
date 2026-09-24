namespace Mavi.Domain.Intelligence;

/// <summary>
/// The canonical Evidence Set role order (ADR-013 §4): Representative, NearView,
/// EarlyDiverse, LateDiverse. It is also the rank order. The ranks a Track keeps
/// are contiguous <c>0..n−1</c> over the roles it kept, taken in this order.
/// </summary>
/// <remarks>
/// This is the one definition. The completion validator uses it on write, and the
/// Track-detail read seam uses it on read, so the two cannot disagree about what a
/// well-formed Evidence Set is.
/// </remarks>
public static class EvidenceRoleOrder
{
    public static IReadOnlyList<ObservationType> Canonical { get; } =
    [
        ObservationType.Representative,
        ObservationType.NearView,
        ObservationType.EarlyDiverse,
        ObservationType.LateDiverse,
    ];

    /// <summary>The role's position in <see cref="Canonical"/>, or -1 for a value outside the vocabulary.</summary>
    public static int PositionOf(ObservationType role)
    {
        for (var index = 0; index < Canonical.Count; index++)
        {
            if (Canonical[index] == role)
                return index;
        }

        return -1;
    }
}
