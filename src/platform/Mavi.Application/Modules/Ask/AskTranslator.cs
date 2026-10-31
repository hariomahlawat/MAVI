using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Mavi.Application.Modules.Query;

namespace Mavi.Application.Modules.Ask;

/// <summary>A refusal of one Ask request: the stage that refused, a closed code, a JSON pointer and platform text.</summary>
public sealed record AskRefusal(string Stage, string Code, string Path, string Message);

/// <summary>The translator's outcome: a parsed contract query (with the exact JSON handed to the parser), or a refusal.</summary>
public sealed record AskTranslation(StructuredQuery? Query, string? ContractJson, AskRefusal? Refusal)
{
    public static AskTranslation Refuse(string stage, string code, string path, string message) =>
        new(null, null, new AskRefusal(stage, code, path, message));
}

/// <summary>
/// Turns the model's text into a structured query or a refusal (ADR-026 §4). It accepts exactly one translation
/// document; rewrites each instant from the site's explicit offset to the same instant in UTC, refusing an offset that
/// is not the site zone's at that instant; and hands the result to the strict S9 parser. It rewrites nothing else,
/// completes nothing, and never retries: anything it cannot accept is refused with the reason.
/// <para>Prompt v2 (m2, ADR-026 amendment D-S10-9) passes the question: a plate text is accepted only when its
/// normalised form occurs in the question's letters and digits, so the model cannot write a plate nobody asked for.</para>
/// </summary>
public static class AskTranslator
{
    private static readonly Regex OffsetInstant = new(
        @"^(?<local>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,3})?)(?<offset>Z|[+-][0-9]{2}:[0-9]{2})$",
        RegexOptions.CultureInvariant);

    /// <summary>The members of the query that hold instants, as (parent pointer, member) pairs.</summary>
    private static readonly (string[] Parent, string Member)[] InstantMembers =
    [
        (["where", "timeWindow"], "fromUtc"),
        (["where", "timeWindow"], "toUtc"),
        (["operation", "baseline"], "fromUtc"),
        (["operation", "baseline"], "toUtc"),
    ];

    public static AskTranslation Translate(string modelText, AskSiteTime siteTime) => Translate(modelText, siteTime, null);

    /// <param name="groundingQuestion">Prompt v2: the question the plate text must occur in; null (v1) checks nothing.</param>
    public static AskTranslation Translate(string modelText, AskSiteTime siteTime, string? groundingQuestion)
    {
        ArgumentNullException.ThrowIfNull(modelText);
        ArgumentNullException.ThrowIfNull(siteTime);

        JsonNode? root;
        try
        {
            // Duplicates first: a JsonNode would keep one of them silently, and the document is closed.
            if (Duplicate(modelText) is { } duplicate)
                return Invalid(duplicate, "A member appears more than once.");
            root = JsonNode.Parse(modelText, documentOptions: new JsonDocumentOptions { MaxDepth = 16 });
        }
        catch (JsonException)
        {
            return Invalid("", "The model's output is not a JSON document.");
        }

        if (root is not JsonObject document)
            return Invalid("", "The model's output is not a translation document.");

        if (document["answer"] is not JsonValue answerValue || !answerValue.TryGetValue<string>(out var answer))
            return Invalid("/answer", "answer is required and must be query or refusal.");

        switch (answer)
        {
            case "refusal":
                if (Unknown(document, ["answer", "reason"]) is { } unknownRefusalMember)
                    return Invalid(unknownRefusalMember, "Not a member of a refusal.");
                if (document["reason"] is not JsonValue reasonValue || !reasonValue.TryGetValue<string>(out var reason) ||
                    !AskCodes.ModelRefusalReasons.Contains(reason, StringComparer.Ordinal))
                    return Invalid("/reason", "reason must be outside_contract or unknown_reference.");
                return AskTranslation.Refuse(AskCodes.StageModel, reason, "", AskCodes.ModelRefusalMessage(reason));

            case "query":
                if (Unknown(document, ["answer", "query"]) is { } unknownQueryMember)
                    return Invalid(unknownQueryMember, "Not a member of a query translation.");
                if (document["query"] is not JsonObject query)
                    return Invalid("/query", "query is required and must be an object.");
                return TranslateQuery(query, siteTime, groundingQuestion);

            default:
                return Invalid("/answer", "answer must be query or refusal.");
        }
    }

    private static AskTranslation TranslateQuery(JsonObject query, AskSiteTime siteTime, string? groundingQuestion)
    {
        foreach (var (parentPath, member) in InstantMembers)
        {
            if (Navigate(query, parentPath) is not JsonObject parent || !parent.ContainsKey(member))
                continue;
            var pointer = "/query/" + string.Join('/', parentPath) + "/" + member;
            if (parent[member] is not JsonValue value || !value.TryGetValue<string>(out var text))
                return Invalid(pointer, "An instant must be a string.");

            var match = OffsetInstant.Match(text);
            if (!match.Success ||
                !DateTimeOffset.TryParseExact(
                    text,
                    ["yyyy-MM-dd'T'HH:mm:ssK", "yyyy-MM-dd'T'HH:mm:ss.FFFK"],
                    CultureInfo.InvariantCulture,
                    DateTimeStyles.None,
                    out var instant))
                return Invalid(pointer, $"An instant must be site-local time with the site offset {siteTime.OffsetText}.");

            // The offset must be the site zone's offset at that instant; anything else would name a different time.
            if (instant.Offset != siteTime.OffsetAt(instant))
                return AskTranslation.Refuse(
                    AskCodes.StageTranslation,
                    AskCodes.TimeOffsetMismatch,
                    pointer,
                    $"The instant {text} does not carry the site time zone's offset ({siteTime.TimeZoneId}).");

            parent[member] = StructuredQueryCanonical.Instant(instant);
        }

        var contractJson = query.ToJsonString();
        var parsed = StructuredQueryParser.Parse(contractJson);
        if (parsed.Refusal is { } refusal)
            return new AskTranslation(null, contractJson, new AskRefusal(AskCodes.StageContract, refusal.Code, refusal.Path, refusal.Message));

        // The parser has normalised the plate text; it must be a run of the question's own letters and digits.
        if (groundingQuestion is not null && parsed.Query!.Where.Plate is { } plate && !QuestionCharacters(groundingQuestion).Contains(plate.Text, StringComparison.Ordinal))
            return AskTranslation.Refuse(
                AskCodes.StageTranslation,
                AskCodes.PlateTextUngrounded,
                "/query/where/plateText/text",
                AskCodes.StageMessage(AskCodes.StageTranslation, AskCodes.PlateTextUngrounded));

        return new AskTranslation(parsed.Query, contractJson, null);
    }

    /// <summary>The question's letters and digits, upper-cased and joined: where a grounded plate text must occur.</summary>
    public static string QuestionCharacters(string question) =>
        new([.. question.Where(char.IsLetterOrDigit).Select(char.ToUpperInvariant)]);

    private static AskTranslation Invalid(string path, string message) =>
        AskTranslation.Refuse(AskCodes.StageTranslation, AskCodes.ModelOutputInvalid, path, message);

    private static JsonNode? Navigate(JsonObject root, string[] path)
    {
        JsonNode? node = root;
        foreach (var segment in path)
            node = node is JsonObject obj && obj.TryGetPropertyValue(segment, out var child) ? child : null;
        return node;
    }

    private static string? Unknown(JsonObject document, string[] allowed)
    {
        foreach (var (name, _) in document)
        {
            if (!allowed.Contains(name, StringComparer.Ordinal))
                return "/" + Escape(name);
        }

        return null;
    }

    private static string Escape(string name) => name.Replace("~", "~0", StringComparison.Ordinal).Replace("/", "~1", StringComparison.Ordinal);

    /// <summary>
    /// <see cref="JsonNode"/> keeps the last of duplicated members silently; the translation document is closed, so a
    /// duplicate anywhere is refused. The S9 parser checks the query itself again.
    /// </summary>
    private static string? Duplicate(string json)
    {
        using var document = JsonDocument.Parse(json, new JsonDocumentOptions { MaxDepth = 16 });
        return Duplicate(document.RootElement, "");
    }

    private static string? Duplicate(JsonElement element, string path)
    {
        switch (element.ValueKind)
        {
            case JsonValueKind.Object:
                var seen = new HashSet<string>(StringComparer.Ordinal);
                foreach (var property in element.EnumerateObject())
                {
                    var memberPath = path + "/" + Escape(property.Name);
                    if (!seen.Add(property.Name))
                        return memberPath;
                    if (Duplicate(property.Value, memberPath) is { } nested)
                        return nested;
                }

                return null;
            case JsonValueKind.Array:
                var index = 0;
                foreach (var item in element.EnumerateArray())
                {
                    if (Duplicate(item, path + "/" + index.ToString(CultureInfo.InvariantCulture)) is { } nested)
                        return nested;
                    index++;
                }

                return null;
            default:
                return null;
        }
    }
}
