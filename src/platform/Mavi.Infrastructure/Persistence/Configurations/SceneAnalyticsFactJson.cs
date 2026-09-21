using System.Globalization;
using System.Text;
using Mavi.Domain.Common;
using Mavi.Domain.SceneAnalytics;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// Canonical jsonb for the two motion-summary lists.
/// </summary>
/// <remarks>
/// Hand-written rather than serialised, for the same reason
/// <see cref="SceneGeometryJson"/> is: the stored text must not change because a
/// serializer default changed. Determinism is a frozen property of analytics (§49),
/// so the same facts must produce the same bytes on every host and run.
/// </remarks>
internal static class SceneAnalyticsFactJson
{
    public static string WriteIntervals(IReadOnlyList<StationaryInterval> intervals)
    {
        var builder = new StringBuilder(intervals.Count * 24);
        builder.Append('[');
        for (var index = 0; index < intervals.Count; index++)
        {
            if (index > 0)
            {
                builder.Append(',');
            }

            builder.Append('[')
                .Append(intervals[index].StartOffsetMs.ToString(CultureInfo.InvariantCulture))
                .Append(',')
                .Append(intervals[index].EndOffsetMs.ToString(CultureInfo.InvariantCulture))
                .Append(']');
        }

        return builder.Append(']').ToString();
    }

    public static List<StationaryInterval> ReadIntervals(string json)
    {
        using var document = System.Text.Json.JsonDocument.Parse(json);
        var root = document.RootElement;
        if (root.ValueKind != System.Text.Json.JsonValueKind.Array)
        {
            throw Corrupt("Stored stationary intervals are not an array.");
        }

        var intervals = new List<StationaryInterval>(root.GetArrayLength());
        foreach (var pair in root.EnumerateArray())
        {
            if (pair.ValueKind != System.Text.Json.JsonValueKind.Array || pair.GetArrayLength() != 2)
            {
                throw Corrupt("A stored stationary interval is not a start/end pair.");
            }

            intervals.Add(new StationaryInterval(pair[0].GetInt64(), pair[1].GetInt64()));
        }

        return intervals;
    }

    public static string WriteGuids(IReadOnlyList<Guid> ids)
    {
        var builder = new StringBuilder(ids.Count * 40);
        builder.Append('[');
        for (var index = 0; index < ids.Count; index++)
        {
            if (index > 0)
            {
                builder.Append(',');
            }

            builder.Append('"').Append(ids[index].ToString("D", CultureInfo.InvariantCulture)).Append('"');
        }

        return builder.Append(']').ToString();
    }

    public static List<Guid> ReadGuids(string json)
    {
        using var document = System.Text.Json.JsonDocument.Parse(json);
        var root = document.RootElement;
        if (root.ValueKind != System.Text.Json.JsonValueKind.Array)
        {
            throw Corrupt("Stored stationary zone ids are not an array.");
        }

        var ids = new List<Guid>(root.GetArrayLength());
        foreach (var element in root.EnumerateArray())
        {
            if (element.ValueKind != System.Text.Json.JsonValueKind.String || !element.TryGetGuid(out var id))
            {
                throw Corrupt("A stored stationary zone id is not a GUID.");
            }

            ids.Add(id);
        }

        return ids;
    }

    private static DomainValidationException Corrupt(string message) =>
        new("analytics_fact_json_corrupt", message);
}
