namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// Whether a Track contributed facts to an analysis unit.
/// </summary>
/// <remarks>
/// Every Track of the run gets exactly one outcome row per unit, always. A Track
/// whose evidence is permanently unusable is recorded as <see cref="Unavailable"/>
/// with a reason rather than omitted, because an absent row and a Track with no
/// events are the same shape to a consumer and must not be.
/// </remarks>
public enum TrackAnalysisOutcomeKind
{
    /// <summary>Evidence was read and evaluated; facts for this Track are present.</summary>
    Analysed = 0,

    /// <summary>Evidence is permanently unusable for this Track; no facts were derived.</summary>
    Unavailable = 1
}
