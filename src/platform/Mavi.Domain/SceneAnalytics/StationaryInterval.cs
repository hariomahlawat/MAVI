namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// A span during which a Track's smoothed reference point did not move, in
/// media-relative milliseconds.
/// </summary>
/// <remarks>
/// Persisted inside <c>track_motion_summaries.stationary_intervals</c> as jsonb.
/// It is evidence-display detail hanging off a typed row — a variable-length list
/// nothing searches by element — which is the only shape §O allows jsonb for.
/// The two duration columns beside it are what predicates actually use.
/// </remarks>
public readonly record struct StationaryInterval(long StartOffsetMs, long EndOffsetMs)
{
    public long DurationMs => EndOffsetMs - StartOffsetMs;
}
