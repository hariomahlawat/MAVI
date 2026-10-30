using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Mavi.Contracts.Api.Query;

namespace Mavi.Application.Modules.Ask;

/// <summary>
/// The decoding grammar for one request (ADR-026 §4): a JSON Schema the language runtime turns into a grammar, so the
/// model can only write a translation document whose members, enumerations and ids come from the contract vocabulary
/// and the site catalogue. It is a generation aid in the subset the runtime supports (objects, enums, consts, anyOf,
/// array bounds, simple patterns); the strict S9 parser remains the authority on what a query is.
/// </summary>
public static class AskGrammar
{
    public static string Build(QueryContractResponse vocabulary, AskSiteCatalogue catalogue, AskSiteTime siteTime)
    {
        ArgumentNullException.ThrowIfNull(vocabulary);
        ArgumentNullException.ThrowIfNull(catalogue);
        ArgumentNullException.ThrowIfNull(siteTime);

        var cameraIds = catalogue.Cameras.Select(camera => camera.CameraId.ToString("D")).ToList();
        var zoneIds = catalogue.Cameras.SelectMany(camera => camera.Zones).Select(zone => zone.ZoneId.ToString("D")).ToList();
        var lineIds = catalogue.Cameras.SelectMany(camera => camera.Lines).Select(line => line.LineId.ToString("D")).ToList();
        var units = vocabulary.Units.Select(unit => unit.Unit).ToList();
        var dimensions = vocabulary.Units.SelectMany(unit => unit.GroupDimensions).Distinct(StringComparer.Ordinal).ToList();
        var fields = vocabulary.Units.SelectMany(unit => unit.DistinctFields).Distinct(StringComparer.Ordinal).ToList();

        // Seconds only: a question never needs sub-second instants, and the shorter grammar decodes faster.
        var instant = new JsonObject
        {
            ["type"] = "string",
            ["pattern"] = "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}" + Regex.Escape(siteTime.OffsetText) + "$",
        };
        JsonObject Window() => Object(new() { ["fromUtc"] = instant.DeepClone(), ["toUtc"] = instant.DeepClone() }, "fromUtc", "toUtc");

        var where = new Dictionary<string, JsonNode>
        {
            ["timeWindow"] = Window(),
            ["cameraIds"] = Array(Enum(cameraIds), 1, Math.Max(1, Math.Min(cameraIds.Count, vocabulary.Bounds.MaximumCameraIds))),
            ["objectClass"] = Enum(vocabulary.ObjectClasses),
            ["objectSubclass"] = Enum(vocabulary.ObjectSubclasses),
            ["minDurationMs"] = Integer(),
            ["zone"] = Object(
                new()
                {
                    ["zoneId"] = Enum(zoneIds),
                    ["relation"] = Enum(vocabulary.ZoneRelations),
                    ["minDwellMs"] = Integer(),
                    ["loitering"] = new JsonObject { ["type"] = "boolean" },
                },
                "zoneId"),
            ["line"] = Object(new() { ["lineId"] = Enum(lineIds), ["direction"] = Enum(vocabulary.CrossingDirections) }, "lineId"),
            ["plateText"] = Object(
                new() { ["text"] = new JsonObject { ["type"] = "string", ["minLength"] = 1, ["maxLength"] = 64 }, ["match"] = Enum(vocabulary.PlateMatches) },
                "text"),
            ["ruleIds"] = Array(Enum(vocabulary.EventRuleIds), 1, vocabulary.EventRuleIds.Count),
        };
        if (vocabulary.Attributes.Count > 0)
        {
            where["attributes"] = Array(
                new JsonObject
                {
                    ["anyOf"] = new JsonArray([.. vocabulary.Attributes.Select(attribute => (JsonNode)Object(
                        new() { ["type"] = new JsonObject { ["const"] = attribute.Type }, ["value"] = Enum(attribute.Values) },
                        "type", "value"))]),
                },
                1,
                4);
        }

        // Zone and line references need a catalogue entry; without one the member is left out of the grammar.
        if (zoneIds.Count == 0)
            where.Remove("zone");
        if (lineIds.Count == 0)
            where.Remove("line");

        var operations = new JsonArray(
            Object(new() { ["op"] = Const("find"), ["limit"] = Integer(1, vocabulary.Bounds.MaximumFindLimit), ["order"] = Enum(["newest", "oldest"]) }, "op"),
            Object(new() { ["op"] = Enum(["count", "first", "last"]) }, "op"),
            Object(new() { ["op"] = Const("countDistinct"), ["field"] = Enum(fields) }, "op", "field"),
            Object(new() { ["op"] = Const("groupBy"), ["by"] = Enum(dimensions) }, "op", "by"),
            Object(new() { ["op"] = Const("top"), ["by"] = Enum(dimensions), ["k"] = Integer(1, vocabulary.Bounds.MaximumTopK) }, "op", "by"),
            Object(
                new() { ["op"] = Const("timeBucket"), ["bucketSeconds"] = Integer(vocabulary.Bounds.MinimumBucketSeconds, vocabulary.Bounds.MaximumBucketSeconds) },
                "op", "bucketSeconds"),
            Object(new() { ["op"] = Const("compare"), ["baseline"] = Window() }, "op", "baseline"));

        var query = Object(
            new()
            {
                ["contractVersion"] = Const(vocabulary.ContractVersion),
                ["unit"] = Enum(units),
                ["where"] = Object(where, "timeWindow"),
                ["operation"] = new JsonObject { ["anyOf"] = operations },
            },
            "contractVersion", "unit", "where", "operation");

        var schema = new JsonObject
        {
            ["anyOf"] = new JsonArray(
                Object(new() { ["answer"] = Const("query"), ["query"] = query }, "answer", "query"),
                Object(new() { ["answer"] = Const("refusal"), ["reason"] = Enum(AskCodes.ModelRefusalReasons) }, "answer", "reason")),
        };
        return schema.ToJsonString();
    }

    private static JsonObject Object(Dictionary<string, JsonNode> properties, params string[] required)
    {
        var members = new JsonObject();
        foreach (var (name, value) in properties)
            members[name] = value;
        return new JsonObject
        {
            ["type"] = "object",
            ["properties"] = members,
            ["required"] = new JsonArray([.. required.Select(name => (JsonNode)name)]),
            ["additionalProperties"] = false,
        };
    }

    private static JsonObject Enum(IEnumerable<string> values) =>
        new() { ["enum"] = new JsonArray([.. values.Select(value => (JsonNode)value)]) };

    private static JsonObject Const(string value) => new() { ["const"] = value };

    private static JsonObject Integer(long? minimum = 0, long? maximum = null)
    {
        var node = new JsonObject { ["type"] = "integer" };
        if (minimum is { } low)
            node["minimum"] = low;
        if (maximum is { } high)
            node["maximum"] = high;
        return node;
    }

    private static JsonObject Array(JsonNode items, int minimum, int maximum) =>
        new() { ["type"] = "array", ["items"] = items, ["minItems"] = minimum, ["maxItems"] = maximum };
}
