using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Contracts.Api.Query;

namespace Mavi.Application.Modules.Ask;

/// <summary>One prompt and its decoding grammar, with the SHA-256 of each (bound into recordings, ADR-026 §6).</summary>
public sealed record AskPromptRequest(string Prompt, string PromptSha256, string Grammar, string GrammarSha256);

/// <summary>
/// Builds the prompt for one question (ADR-026 §4) from the contract vocabulary, the site catalogue, the site time and
/// the question. Deterministic: the same inputs give the same bytes. The model is given, as text to copy, everything
/// it would otherwise have to compute — the camera, zone and line references as JSON fragments, and the windows for
/// "today" and "yesterday" — and worked examples composed from the site's own catalogue, so the prompt fits any site.
/// The template is versioned; a change to it is a new version and needs new recordings.
/// </summary>
public static class AskPrompt
{
    public const string TemplateVersion = "mavi-ask-prompt-v1";

    private static readonly JsonSerializerOptions Compact = new() { WriteIndented = false };

    public static AskPromptRequest Build(
        QueryContractResponse vocabulary,
        AskSiteCatalogue catalogue,
        AskSiteTime siteTime,
        string question)
    {
        ArgumentNullException.ThrowIfNull(vocabulary);
        ArgumentNullException.ThrowIfNull(catalogue);
        ArgumentNullException.ThrowIfNull(siteTime);
        ArgumentNullException.ThrowIfNull(question);

        var prompt = new StringBuilder();
        prompt.Append("<|im_start|>system\n").Append(System(vocabulary, catalogue, siteTime)).Append("<|im_end|>\n");
        foreach (var (exampleQuestion, answer) in Examples(vocabulary, catalogue, siteTime))
        {
            prompt.Append("<|im_start|>user\n").Append(exampleQuestion).Append("<|im_end|>\n");
            prompt.Append("<|im_start|>assistant\n").Append(answer.ToJsonString(Compact)).Append("<|im_end|>\n");
        }

        prompt.Append("<|im_start|>user\n").Append(OneLine(question)).Append("<|im_end|>\n<|im_start|>assistant\n");
        // Line endings are part of the bytes the model sees; a Windows checkout's CRLF must not change the prompt.
        var text = prompt.ToString().Replace("\r\n", "\n", StringComparison.Ordinal);
        var grammar = AskGrammar.Build(vocabulary, catalogue, siteTime, AskQuestionScope.From(question, catalogue, vocabulary));
        return new AskPromptRequest(text, Sha256(text), grammar, Sha256(grammar));
    }

    public static string Sha256(string text) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));

    /// <summary>The question as one line: control characters and line breaks become spaces, so it cannot open a new turn.</summary>
    public static string OneLine(string question)
    {
        var builder = new StringBuilder(question.Length);
        foreach (var character in question.Trim())
            builder.Append(char.IsControl(character) ? ' ' : character);
        return builder.ToString().Replace("<|", "< |", StringComparison.Ordinal);
    }

    private static string System(QueryContractResponse vocabulary, AskSiteCatalogue catalogue, AskSiteTime siteTime)
    {
        string Units(Func<QueryUnitVocabularyResponse, IReadOnlyList<string>> select, string unit) =>
            string.Join(", ", select(vocabulary.Units.Single(item => item.Unit == unit)));

        var offset = siteTime.OffsetText;
        var today = Window(siteTime, siteTime.ReferenceDate, siteTime.ReferenceDate.AddDays(1));
        var yesterday = Window(siteTime, siteTime.ReferenceDate.AddDays(-1), siteTime.ReferenceDate);
        var sample = Window(siteTime, siteTime.ReferenceDate, new TimeOnly(9, 0), siteTime.ReferenceDate, new TimeOnly(10, 30));
        var attributes = string.Join("; ", vocabulary.Attributes.Select(item => $"{item.Type}: {string.Join(", ", item.Values)}"));
        var date = siteTime.ReferenceDate.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);

        var text = new StringBuilder();
        text.Append(
            CultureInfo.InvariantCulture,
            $$"""
            You translate an operator's question about recorded video analytics into exactly one JSON query of the MAVI structured query contract {{vocabulary.ContractVersion}}, or you refuse. You never answer the question yourself and never state a number or a fact: MAVI runs the query.

            Output: {"answer":"query","query":<query>} or {"answer":"refusal","reason":"outside_contract"|"unknown_reference"}.
            Refuse with "outside_contract" when the question cannot be expressed with the units, predicates and operations below (for example: who a person is, why something happened, predictions, opinions, averages or speeds, changing or deleting data, OR between places). Refuse with "unknown_reference" when the question names a camera, zone or line that is not in the site list.

            Units: "track" (a tracked object: {{string.Join(" or ", vocabulary.ObjectClasses)}}), "event" (a derived analytic event), "entity" (a confirmed entity).
            Track predicates: timeWindow (required), cameraIds, objectClass ({{string.Join("|", vocabulary.ObjectClasses)}}), objectSubclass ({{string.Join("|", vocabulary.ObjectSubclasses)}}), minDurationMs, zone {zoneId, relation {{string.Join("|", vocabulary.ZoneRelations)}}, minDwellMs, loitering}, line {lineId, direction}, attributes [{type,value}], plateText {text, match {{string.Join("|", vocabulary.PlateMatches)}}}. A zone or line on tracks needs cameraIds with exactly that one camera.
            Event predicates: timeWindow (required), cameraIds, objectClass, zone {zoneId}, line {lineId, direction}, ruleIds ({{string.Join(", ", vocabulary.EventRuleIds)}}).
            Entity predicates: timeWindow (required), cameraIds.
            Operations: find {limit, order newest|oldest}, count, countDistinct {field}, groupBy {by}, timeBucket {bucketSeconds}, first, last, top {by, k}, compare {baseline}.
            Track dimensions (groupBy, top): {{Units(unit => unit.GroupDimensions, "track")}}. Track countDistinct field: {{Units(unit => unit.DistinctFields, "track")}}.
            Event dimensions: {{Units(unit => unit.GroupDimensions, "event")}}. Event countDistinct field: {{Units(unit => unit.DistinctFields, "event")}}.

            """);
        if (vocabulary.Attributes.Count > 0)
        {
            text.Append(CultureInfo.InvariantCulture, $"Attributes (type: values): {attributes}. Upper clothing (shirt, top, jacket) is person-upper-colour; lower clothing (trousers, skirt) is person-lower-colour; a bag or backpack is person-carried-bag present; a hat is person-headwear present; a vehicle's colour is vehicle-colour.\n");
        }

        text.Append(
            CultureInfo.InvariantCulture,
            $$"""

            Time: the site time zone is {{siteTime.TimeZoneId}}; every instant is site local time with the offset {{offset}}. Today is {{date}}. A question without a date or a time means today. Copy these windows exactly:
              today: "timeWindow":{{today}}
              yesterday: "timeWindow":{{yesterday}}
              between 09:00 and 10:30 today: "timeWindow":{{sample}}

            Rules:
            - "people", "persons": objectClass Person. "vehicles": Vehicle. "cars": Vehicle with objectSubclass car.
            - When the question names a camera, or a zone or line of a camera, copy that camera's "cameraIds" fragment.
            - Use a zone, line, attribute, plate or minDurationMs predicate only when the question asks for it.
            - Lines: copy the fragment whose direction word matches the question ("entered" matches Entry; "went in" matches In; "left" or "went out" matches Exit or Out). With no direction word, copy the "any direction" fragment.
            - Questions about events, crossings, dwells or stops (for example "line crossings by direction"), or naming an event kind, use unit "event"; a named kind goes in ruleIds (crossings: line-crossing; dwell: zone-dwell; stopped vehicles: stopped-vehicle; wrong way: wrong-way; co-occurrence; repeated visit: repeated-visit). Questions about people, vehicles or tracks use unit "track".
            - "list", "show", "find": find; "the N most recent", "the latest N", "the newest N": find with limit N, order newest; "the N oldest", "the first N": find with limit N, order oldest. "how many", "count": count. "how many different": countDistinct. "per", "by" a dimension: groupBy. "by hour": timeBucket 3600; "per N minutes": timeBucket N*60. "which N cameras had the most <things>", "top N cameras": top by camera with k N, and keep the objectClass of the things counted. "which camera had the most": top with k 1. "the first <thing>" (one): first. "the last <thing>", "the latest <thing>" (one): last. "how many entities": count on unit "entity". "Compare A with B": the window is A and the baseline is B.

            Site list (copy the fragments exactly):

            """);
        foreach (var camera in catalogue.Cameras)
        {
            text.Append(CultureInfo.InvariantCulture, $"camera \"{camera.Name}\": \"cameraIds\":[\"{camera.CameraId:D}\"]\n");
            foreach (var zone in camera.Zones)
                text.Append(CultureInfo.InvariantCulture, $"  zone \"{zone.Name}\" (this camera): \"zone\":{{\"zoneId\":\"{zone.ZoneId:D}\"}}\n");
            foreach (var line in camera.Lines)
            {
                text.Append(CultureInfo.InvariantCulture, $"  line \"{line.Name}\" (this camera), {line.AToBLabel}: \"line\":{{\"lineId\":\"{line.LineId:D}\",\"direction\":\"aToB\"}}\n");
                text.Append(CultureInfo.InvariantCulture, $"  line \"{line.Name}\" (this camera), {line.BToALabel}: \"line\":{{\"lineId\":\"{line.LineId:D}\",\"direction\":\"bToA\"}}\n");
                text.Append(CultureInfo.InvariantCulture, $"  line \"{line.Name}\" (this camera), any direction: \"line\":{{\"lineId\":\"{line.LineId:D}\"}}\n");
            }
        }

        return text.ToString();
    }

    /// <summary>
    /// Worked examples composed from the site's own catalogue (the first camera, the second, the last camera with a
    /// line, the last with a zone, the middle one), so they never name a camera the site does not have. An example whose
    /// ingredients the site lacks is left out.
    /// </summary>
    private static IEnumerable<(string Question, JsonObject Answer)> Examples(
        QueryContractResponse vocabulary,
        AskSiteCatalogue catalogue,
        AskSiteTime siteTime)
    {
        var cameras = catalogue.Cameras;
        var today = WindowNode(siteTime, siteTime.ReferenceDate, TimeOnly.MinValue, siteTime.ReferenceDate.AddDays(1), TimeOnly.MinValue);
        var yesterday = WindowNode(siteTime, siteTime.ReferenceDate.AddDays(-1), TimeOnly.MinValue, siteTime.ReferenceDate, TimeOnly.MinValue);
        JsonObject Between(int fromHour, int fromMinute, int toHour, int toMinute) =>
            WindowNode(siteTime, siteTime.ReferenceDate, new TimeOnly(fromHour, fromMinute), siteTime.ReferenceDate, new TimeOnly(toHour, toMinute));

        if (cameras.Count > 0)
        {
            var first = cameras[0];
            yield return ($"How many vehicles were seen at the {Short(first)} camera today?",
                QueryAnswer("track", new() { ["timeWindow"] = today.DeepClone(), ["cameraIds"] = Ids(first), ["objectClass"] = "Vehicle" }, new() { ["op"] = "count" }));
        }

        if (cameras.LastOrDefault(camera => camera.Lines.Count > 0) is { } lineCamera)
        {
            var line = lineCamera.Lines[0];
            yield return ($"Show the latest 10 people crossing the {line.Name} line {line.BToALabel} between 09:30 and 09:45",
                QueryAnswer(
                    "track",
                    new()
                    {
                        ["timeWindow"] = Between(9, 30, 9, 45),
                        ["cameraIds"] = Ids(lineCamera),
                        ["objectClass"] = "Person",
                        ["line"] = new JsonObject { ["lineId"] = line.LineId.ToString("D"), ["direction"] = "bToA" },
                    },
                    new() { ["op"] = "find", ["limit"] = 10, ["order"] = "newest" }));
        }

        yield return ("Count events per rule today",
            QueryAnswer("event", new() { ["timeWindow"] = today.DeepClone() }, new() { ["op"] = "groupBy", ["by"] = "rule" }));

        yield return ("Which 4 cameras had the most vehicle tracks between 09:00 and 12:00?",
            QueryAnswer("track", new() { ["timeWindow"] = Between(9, 0, 12, 0), ["objectClass"] = "Vehicle" }, new() { ["op"] = "top", ["by"] = "camera", ["k"] = 4 }));

        if (cameras.Count > 1 &&
            vocabulary.Attributes.FirstOrDefault(item => item.Type == "person-upper-colour" && item.Values.Contains("green")) is not null)
        {
            var second = cameras[1];
            yield return ($"Persons wearing a green jacket at the {Short(second)} yesterday",
                QueryAnswer(
                    "track",
                    new()
                    {
                        ["timeWindow"] = yesterday.DeepClone(),
                        ["cameraIds"] = Ids(second),
                        ["objectClass"] = "Person",
                        ["attributes"] = new JsonArray(new JsonObject { ["type"] = "person-upper-colour", ["value"] = "green" }),
                    },
                    new() { ["op"] = "find" }));
        }

        if (cameras.LastOrDefault(camera => camera.Zones.Count > 0) is { } zoneCamera)
        {
            var zone = zoneCamera.Zones[^1];
            yield return ($"Dwell events per 30 minutes in the {zone.Name} zone between 08:00 and 12:00",
                QueryAnswer(
                    "event",
                    new()
                    {
                        ["timeWindow"] = Between(8, 0, 12, 0),
                        ["cameraIds"] = Ids(zoneCamera),
                        ["zone"] = new JsonObject { ["zoneId"] = zone.ZoneId.ToString("D") },
                        ["ruleIds"] = new JsonArray("zone-dwell"),
                    },
                    new() { ["op"] = "timeBucket", ["bucketSeconds"] = 1800 }));
        }

        if (cameras.Count > 0)
        {
            var middle = cameras[cameras.Count / 2];
            yield return ($"How many vehicles with a plate ending in 77 were at the {Short(middle)} today?",
                QueryAnswer(
                    "track",
                    new()
                    {
                        ["timeWindow"] = today.DeepClone(),
                        ["cameraIds"] = Ids(middle),
                        ["objectClass"] = "Vehicle",
                        ["plateText"] = new JsonObject { ["text"] = "77", ["match"] = "contains" },
                    },
                    new() { ["op"] = "count" }));
        }

        yield return ("Is the man in the blue shirt a known criminal?", Refusal(AskCodes.OutsideContract));
        yield return ("How many cars used the north car park on level 9?", Refusal(AskCodes.UnknownReference));
    }

    /// <summary>A camera's name without a "PoC demo NN - " style prefix, as an operator would say it.</summary>
    private static string Short(AskCatalogueCamera camera)
    {
        var separator = camera.Name.IndexOf(" - ", StringComparison.Ordinal);
        return separator >= 0 ? camera.Name[(separator + 3)..] : camera.Name;
    }

    private static JsonArray Ids(AskCatalogueCamera camera) => new(camera.CameraId.ToString("D"));

    private static JsonObject QueryAnswer(string unit, Dictionary<string, JsonNode?> where, Dictionary<string, JsonNode?> operation)
    {
        var whereNode = new JsonObject();
        foreach (var (name, value) in where)
            whereNode[name] = value;
        var operationNode = new JsonObject();
        foreach (var (name, value) in operation)
            operationNode[name] = value;
        return new JsonObject
        {
            ["answer"] = "query",
            ["query"] = new JsonObject
            {
                ["contractVersion"] = Mavi.Application.Modules.Query.QueryContract.Version,
                ["unit"] = unit,
                ["where"] = whereNode,
                ["operation"] = operationNode,
            },
        };
    }

    private static JsonObject Refusal(string reason) => new() { ["answer"] = "refusal", ["reason"] = reason };

    private static string Window(AskSiteTime siteTime, DateOnly from, DateOnly to) =>
        WindowNode(siteTime, from, TimeOnly.MinValue, to, TimeOnly.MinValue).ToJsonString(Compact);

    private static string Window(AskSiteTime siteTime, DateOnly fromDate, TimeOnly fromTime, DateOnly toDate, TimeOnly toTime) =>
        WindowNode(siteTime, fromDate, fromTime, toDate, toTime).ToJsonString(Compact);

    private static JsonObject WindowNode(AskSiteTime siteTime, DateOnly fromDate, TimeOnly fromTime, DateOnly toDate, TimeOnly toTime) =>
        new() { ["fromUtc"] = Local(siteTime, fromDate, fromTime), ["toUtc"] = Local(siteTime, toDate, toTime) };

    /// <summary>A site-local instant with the zone's offset at that local time, as the model is asked to write it.</summary>
    public static string Local(AskSiteTime siteTime, DateOnly date, TimeOnly time)
    {
        var local = date.ToDateTime(time, DateTimeKind.Unspecified);
        var offset = siteTime.OffsetAtLocal(local);
        return local.ToString("yyyy-MM-dd'T'HH:mm:ss", CultureInfo.InvariantCulture) + AskSiteTime.FormatOffset(offset);
    }
}
