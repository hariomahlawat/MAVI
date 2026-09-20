using Mavi.Domain.Intelligence;
using Mavi.Domain.Scene;

namespace Mavi.Application.Modules.SceneAnalytics.Engine;

/// <summary>
/// Summarises a Track's visits to one zone and applies the loitering rule of plan
/// section M.
/// </summary>
/// <remarks>
/// Loitering here is arithmetic, not a judgement: a person whose total dwell in a
/// zone reaches the zone's threshold loiters, and the summary carries the threshold,
/// the dwell and the visits that contributed so that the verdict can be checked
/// against the evidence. No other object class is ever flagged, and no model is
/// involved.
/// </remarks>
public static class LoiteringRule
{
    public static ZoneSummaryFact Summarise(
        SceneZone zone,
        ObjectClass objectClass,
        IReadOnlyList<ZoneVisitFact> visits,
        SceneAnalyticsParameters parameters)
    {
        ArgumentNullException.ThrowIfNull(zone);
        ArgumentNullException.ThrowIfNull(visits);
        ArgumentNullException.ThrowIfNull(parameters);

        var threshold = zone.LoiteringThresholdSeconds ?? parameters.LoiteringDefaultSeconds;
        long totalDwell = 0;
        var firstEntry = long.MaxValue;
        var lastExit = long.MinValue;
        var contributing = new List<int>(visits.Count);

        foreach (var visit in visits)
        {
            totalDwell += visit.DwellMs;
            firstEntry = Math.Min(firstEntry, visit.EntryOffsetMs);
            lastExit = Math.Max(lastExit, visit.ExitOffsetMs);
            contributing.Add(visit.VisitIndex);
        }

        var loitering = objectClass == ObjectClass.Person &&
            visits.Count > 0 &&
            totalDwell >= (long)threshold * 1000;

        return new ZoneSummaryFact(
            zone.ZoneId,
            visits.Count,
            totalDwell,
            visits.Count == 0 ? 0 : firstEntry,
            visits.Count == 0 ? 0 : lastExit,
            loitering,
            threshold,
            loitering ? totalDwell : 0,
            loitering ? contributing : []);
    }
}
