using Mavi.Domain.Scene;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// Geometry for the qualification corpora, parameterised by count.
/// </summary>
/// <remarks>
/// Geometry count is one of the scaling dimensions the plan requires varying, so
/// the zones and lines are generated rather than fixed. They are laid out on a
/// grid inside the unit square and stay disjoint, which keeps the expected
/// answers of a generated corpus tractable; the deliberately overlapping and
/// boundary-touching cases belong to the hand-written C1 semantic reference,
/// where a human can state the exact answer.
/// </remarks>
public static class QualificationScene
{
    public static readonly string[] Headings = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

    public static SceneRevisionDraft Draft(int zoneCount, int lineCount)
    {
        var zones = new List<SceneZoneDraft>(zoneCount);
        for (var index = 0; index < zoneCount; index++)
        {
            // A 4-column grid of small squares, well inside the frame.
            var column = index % 4;
            var row = index / 4;
            var x = 0.05 + (column * 0.22);
            var y = 0.05 + (row * 0.12);
            zones.Add(new SceneZoneDraft(
                null,
                $"Zone {index + 1}",
                null,
                true,
                [
                    new ScenePointDraft(Round(x), Round(y)),
                    new ScenePointDraft(Round(x + 0.16), Round(y)),
                    new ScenePointDraft(Round(x + 0.16), Round(y + 0.08)),
                    new ScenePointDraft(Round(x), Round(y + 0.08)),
                ],
                30));
        }

        var lines = new List<TripLineDraft>(lineCount);
        for (var index = 0; index < lineCount; index++)
        {
            var y = 0.5 + (index * 0.03);
            lines.Add(new TripLineDraft(
                null,
                $"Line {index + 1}",
                true,
                new ScenePointDraft(0.05, Round(y)),
                new ScenePointDraft(0.95, Round(y)),
                true,
                "inbound",
                "outbound"));
        }

        return new SceneRevisionDraft("Qualification corpus geometry", null, null, zones, lines);
    }

    // The scene persists six decimals; generating anything longer would be
    // rejected or silently rounded, and a corpus must not depend on either.
    private static double Round(double value) => Math.Round(value, 6, MidpointRounding.ToEven);
}
