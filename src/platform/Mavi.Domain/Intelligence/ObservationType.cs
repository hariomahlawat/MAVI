namespace Mavi.Domain.Intelligence;

/// <summary>
/// The Evidence Set role of an accepted observation (ADR-013 §4, §7).
/// </summary>
/// <remarks>
/// The column keeps its historical name; its vocabulary is the four frozen evidence
/// roles. The legacy values <c>TrackStart</c>, <c>BestQuality</c> and <c>TrackEnd</c>
/// were never written and are retired; the migration refuses to run if any row
/// carries one. Declaration order is the canonical role order and the rank order.
/// </remarks>
public enum ObservationType
{
    Representative,
    NearView,
    EarlyDiverse,
    LateDiverse,
}
