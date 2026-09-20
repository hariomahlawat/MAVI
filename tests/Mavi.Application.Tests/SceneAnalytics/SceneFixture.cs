using Mavi.Application.Modules.SceneAnalytics.Engine;
using Mavi.Domain.Scene;

namespace Mavi.Application.Tests.SceneAnalytics;

/// <summary>
/// Builds real scene revisions and trajectories for the engine tests, so the engine
/// is always exercised against geometry that passed domain validation.
/// </summary>
internal static class SceneFixture
{
    private static readonly DateTimeOffset Now = new(2026, 9, 20, 6, 0, 0, TimeSpan.Zero);

    public static SceneConfigurationRevision Revision(
        IEnumerable<SceneZoneDraft>? zones = null,
        IEnumerable<TripLineDraft>? lines = null)
    {
        var configuration = SceneConfiguration.Create(Guid.CreateVersion7(), Now);
        return configuration.SaveRevision(
            null,
            new SceneRevisionDraft(null, null, null, [.. zones ?? []], [.. lines ?? []]),
            null,
            SceneRules.UnattributedDevelopmentActor,
            Now);
    }

    /// <summary>A zone occupying the middle of the frame, from 0.3 to 0.7 on both axes.</summary>
    public static SceneZoneDraft CentreZone(
        string name = "Centre",
        bool enabled = true,
        int? loiteringThresholdSeconds = null) =>
        new(
            null,
            name,
            null,
            enabled,
            [
                new ScenePointDraft(0.3, 0.3),
                new ScenePointDraft(0.7, 0.3),
                new ScenePointDraft(0.7, 0.7),
                new ScenePointDraft(0.3, 0.7),
            ],
            loiteringThresholdSeconds);

    /// <summary>A horizontal line across the middle of the frame, drawn left to right.</summary>
    public static TripLineDraft HorizontalLine(string name = "Kerb", bool enabled = true) =>
        new(
            null,
            name,
            enabled,
            new ScenePointDraft(0.1, 0.5),
            new ScenePointDraft(0.9, 0.5),
            false,
            "down",
            "up");

    /// <summary>The same line drawn the other way round.</summary>
    public static TripLineDraft ReversedHorizontalLine(string name = "Kerb") =>
        new(
            null,
            name,
            true,
            new ScenePointDraft(0.9, 0.5),
            new ScenePointDraft(0.1, 0.5),
            false,
            "down",
            "up");

    public static IReadOnlyList<TrajectorySample> Samples(params (long OffsetMs, double X, double Y)[] points) =>
        [.. points.Select(point => new TrajectorySample(
            point.OffsetMs,
            Mavi.Domain.Scene.Geometry.NormalizedPoint.FromRounded(point.X, point.Y)))];

    /// <summary>
    /// A straight path of <paramref name="count"/> samples spaced
    /// <c>stepMs</c> apart, from one point to another.
    /// </summary>
    public static IReadOnlyList<TrajectorySample> Line(
        int count,
        long stepMs,
        (double X, double Y) from,
        (double X, double Y) to,
        long startMs = 0)
    {
        var samples = new List<TrajectorySample>(count);
        for (var index = 0; index < count; index++)
        {
            var t = count == 1 ? 0 : (double)index / (count - 1);
            samples.Add(new TrajectorySample(
                startMs + (index * stepMs),
                Mavi.Domain.Scene.Geometry.NormalizedPoint.FromRounded(
                    from.X + ((to.X - from.X) * t),
                    from.Y + ((to.Y - from.Y) * t))));
        }

        return samples;
    }

    /// <summary>A path that holds one position for a stated duration.</summary>
    public static IReadOnlyList<TrajectorySample> Held(
        int count,
        long stepMs,
        (double X, double Y) at,
        long startMs = 0) =>
        Line(count, stepMs, at, at, startMs);

    public static IReadOnlyList<TrajectorySample> Concat(
        params IReadOnlyList<TrajectorySample>[] parts) =>
        [.. parts.SelectMany(part => part)];
}
