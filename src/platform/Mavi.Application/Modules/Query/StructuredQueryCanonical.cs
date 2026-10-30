using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Mavi.Application.Modules.Intelligence;

namespace Mavi.Application.Modules.Query;

/// <summary>
/// The canonical form of a query (ADR-024 §6): members in a fixed order, defaults explicit, sets sorted and de-duplicated,
/// instants as UTC with milliseconds. Two queries that mean the same thing write the same bytes, so they share one
/// fingerprint. The canonical form is itself a valid query.
/// </summary>
public static class StructuredQueryCanonical
{
    public static string Write(StructuredQuery query)
    {
        ArgumentNullException.ThrowIfNull(query);
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream))
        {
            writer.WriteStartObject();
            writer.WriteString("contractVersion", QueryContract.Version);
            writer.WriteString("unit", QueryContract.ToWire(query.Unit));
            WriteWhere(writer, query.Where);
            WriteOperation(writer, query.Operation);
            writer.WriteBoolean("requireCompleteCoverage", query.RequireCompleteCoverage);
            writer.WriteEndObject();
        }

        return Encoding.UTF8.GetString(stream.ToArray());
    }

    public static string Fingerprint(string canonical) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(canonical)));

    public static string Instant(DateTimeOffset value) =>
        value.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture);

    private static void WriteWhere(Utf8JsonWriter writer, QueryPredicates where)
    {
        writer.WriteStartObject("where");
        WriteWindow(writer, "timeWindow", where.Window);
        if (where.CameraIds.Count > 0)
        {
            writer.WriteStartArray("cameraIds");
            foreach (var id in where.CameraIds)
                writer.WriteStringValue(id.ToString("D"));
            writer.WriteEndArray();
        }

        if (where.ObjectClass is { } objectClass)
            writer.WriteString("objectClass", objectClass.ToString());
        if (where.ObjectSubclass is { } subclass)
            writer.WriteString("objectSubclass", subclass);
        if (where.MinDurationMs is { } duration)
            writer.WriteNumber("minDurationMs", duration);
        if (where.MinConfidence is { } confidence)
            writer.WriteNumber("minConfidence", confidence);

        if (where.Zone is { } zone)
        {
            writer.WriteStartObject("zone");
            writer.WriteString("zoneId", zone.ZoneId.ToString("D"));
            if (zone.Relation is { } relation)
                writer.WriteString("relation", TrackAnalyticsQueryRules.ToWire(relation));
            if (zone.MinDwellMs is { } dwell)
                writer.WriteNumber("minDwellMs", dwell);
            if (zone.Loitering)
                writer.WriteBoolean("loitering", true);
            writer.WriteEndObject();
        }

        if (where.Line is { } line)
        {
            writer.WriteStartObject("line");
            writer.WriteString("lineId", line.LineId.ToString("D"));
            if (line.Direction is { } direction)
                writer.WriteString("direction", TrackAnalyticsQueryRules.ToWire(direction));
            writer.WriteEndObject();
        }

        if (where.Motion is { } motion)
        {
            writer.WriteStartObject("motion");
            if (motion.Direction is { } heading)
                writer.WriteString("direction", heading);
            if (motion.MinStationaryMs is { } stationary)
                writer.WriteNumber("minStationaryMs", stationary);
            writer.WriteEndObject();
        }

        if (where.Attributes is { } attributes)
        {
            writer.WriteStartArray("attributes");
            foreach (var predicate in attributes.Predicates)
            {
                writer.WriteStartObject();
                writer.WriteString("type", predicate.AttributeType);
                writer.WriteString("value", predicate.Value);
                writer.WriteEndObject();
            }

            writer.WriteEndArray();
        }

        if (where.Plate is { } plate)
        {
            writer.WriteStartObject("plateText");
            writer.WriteString("text", plate.Text);
            writer.WriteString("match", TrackPlateQueryRules.ToWire(plate.Match));
            writer.WriteEndObject();
        }

        if (where.SimilarTo is { } similar)
        {
            writer.WriteStartObject("similarTo");
            writer.WriteString("trackId", similar.TrackId.ToString("D"));
            writer.WriteNumber("k", similar.K);
            writer.WriteEndObject();
        }

        if (where.RuleIds.Count > 0)
        {
            writer.WriteStartArray("ruleIds");
            foreach (var rule in where.RuleIds)
                writer.WriteStringValue(rule);
            writer.WriteEndArray();
        }

        if (where.CatalogueVersion is { } catalogue)
            writer.WriteString("catalogueVersion", catalogue);
        writer.WriteEndObject();
    }

    private static void WriteOperation(Utf8JsonWriter writer, QueryOperation operation)
    {
        writer.WriteStartObject("operation");
        writer.WriteString("op", QueryContract.ToWire(operation.Kind));
        if (operation.Limit is { } limit)
            writer.WriteNumber("limit", limit);
        if (operation.Order is { } order)
            writer.WriteString("order", QueryContract.ToWire(order));
        if (operation.Field is { } field)
            writer.WriteString("field", field);
        if (operation.By is { } by)
            writer.WriteString("by", by);
        if (operation.BucketSeconds is { } seconds)
            writer.WriteNumber("bucketSeconds", seconds);
        if (operation.K is { } k)
            writer.WriteNumber("k", k);
        if (operation.Baseline is { } baseline)
            WriteWindow(writer, "baseline", baseline);
        writer.WriteEndObject();
    }

    private static void WriteWindow(Utf8JsonWriter writer, string name, QueryWindow window)
    {
        writer.WriteStartObject(name);
        writer.WriteString("fromUtc", Instant(window.FromUtc));
        writer.WriteString("toUtc", Instant(window.ToUtc));
        writer.WriteEndObject();
    }
}
