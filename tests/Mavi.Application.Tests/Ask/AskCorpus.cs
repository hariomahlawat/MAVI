using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Ask;
using Mavi.Application.Modules.Query;
using Mavi.Contracts.Api.Query;

namespace Mavi.Application.Tests.Ask;

/// <summary>
/// The frozen Ask MAVI question corpus and its fixtures (ADR-026 §6), shared by the replay tests and the recorder.
/// The vocabulary is the S9 contract's, with the PoC attribute vocabulary read from the repository's frozen schema (what
/// the installed release publishes); the catalogue is the evidence database's, frozen as a fixture.
/// </summary>
public static class AskCorpus
{
    public const string QuestionsPath = "contracts/test-vectors/ask-mavi-questions-v1.json";

    /// <summary>The fresh held split of prompt v2 (D-S10-8): written before any v2 output, measured once per model.</summary>
    public const string QuestionsPathV2 = "contracts/test-vectors/ask-mavi-questions-v2.json";

    /// <summary>The corpus a prompt version's recordings are made on: v1 on the v1 corpus, v2 on its fresh held split.</summary>
    public static string QuestionsPathFor(string promptVersion) =>
        AskPrompt.IsVersion2(promptVersion) ? QuestionsPathV2 : QuestionsPath;
    public const string CataloguePath = "contracts/test-vectors/ask-mavi-site-catalogue-v1.json";
    public const string AttributeSchemaPath = "src/vision/config/attributes/attribute-schema-poc-zero-shot-v1.json";
    public const string RecordingsDirectory = "contracts/test-vectors";
    public const string RecordingsPattern = "ask-mavi-recordings-*.json";

    public sealed record Question(string Id, string Split, string Text, JsonObject Expect);

    public static string Root { get; } = FindRoot();

    public static string Read(string relative) => File.ReadAllText(Path.Combine(Root, relative));

    public static (string TimeZoneId, DateOnly ReferenceDate, IReadOnlyList<Question> Questions) LoadQuestions() => LoadQuestions(QuestionsPath);

    public static (string TimeZoneId, DateOnly ReferenceDate, IReadOnlyList<Question> Questions) LoadQuestions(string path)
    {
        var document = JsonNode.Parse(Read(path))!.AsObject();
        var site = document["site"]!.AsObject();
        var questions = document["questions"]!.AsArray()
            .Select(item => new Question(
                (string)item!["id"]!,
                (string)item["split"]!,
                (string)item["question"]!,
                item["expect"]!.AsObject()))
            .ToList();
        return ((string)site["timeZoneId"]!, DateOnly.Parse((string)site["referenceDate"]!, System.Globalization.CultureInfo.InvariantCulture), questions);
    }

    public static AskSiteCatalogue LoadCatalogue()
    {
        using var document = JsonDocument.Parse(Read(CataloguePath));
        return AskSiteCatalogue.Ordered(document.RootElement.GetProperty("cameras").EnumerateArray().Select(camera => new AskCatalogueCamera(
            camera.GetProperty("cameraId").GetGuid(),
            camera.GetProperty("code").GetString()!,
            camera.GetProperty("name").GetString()!,
            camera.GetProperty("timeZoneId").GetString()!,
            [.. camera.GetProperty("zones").EnumerateArray().Select(zone => new AskCatalogueZone(
                zone.GetProperty("zoneId").GetGuid(), zone.GetProperty("name").GetString()!, zone.GetProperty("kind").GetString()!))],
            [.. camera.GetProperty("lines").EnumerateArray().Select(line => new AskCatalogueLine(
                line.GetProperty("lineId").GetGuid(),
                line.GetProperty("name").GetString()!,
                line.GetProperty("aToBLabel").GetString()!,
                line.GetProperty("bToALabel").GetString()!))])));
    }

    public static QueryContractResponse LoadVocabulary()
    {
        using var schema = JsonDocument.Parse(Read(AttributeSchemaPath));
        var attributes = schema.RootElement.GetProperty("attributes").EnumerateArray()
            .Select(item => new QueryAttributeVocabularyResponse(
                item.GetProperty("attributeType").GetString()!,
                item.GetProperty("objectClass").GetString() == "person" ? "Person" : "Vehicle",
                [.. item.GetProperty("values").EnumerateArray().Select(value => value.GetString()!)]))
            .OrderBy(item => item.Type, StringComparer.Ordinal)
            .ToList();
        return QueryContractVocabulary.Describe(null) with { Attributes = attributes };
    }

    /// <summary>The expected translation with <c>{camera:CODE}</c>, <c>{zone:CODE/Name}</c> and <c>{line:CODE/Name}</c> resolved.</summary>
    public static JsonObject Resolve(JsonObject expect, AskSiteCatalogue catalogue) =>
        (JsonObject)ResolveNode(expect.DeepClone(), catalogue)!;

    private static JsonNode? ResolveNode(JsonNode? node, AskSiteCatalogue catalogue)
    {
        switch (node)
        {
            case JsonObject obj:
                foreach (var name in obj.Select(pair => pair.Key).ToList())
                    obj[name] = ResolveNode(obj[name]?.DeepClone(), catalogue);
                return obj;
            case JsonArray array:
                for (var index = 0; index < array.Count; index++)
                    array[index] = ResolveNode(array[index]?.DeepClone(), catalogue);
                return array;
            case JsonValue value when value.TryGetValue<string>(out var text) && text.StartsWith('{') && text.EndsWith('}'):
                var reference = text[1..^1];
                var kind = reference[..reference.IndexOf(':', StringComparison.Ordinal)];
                var key = reference[(kind.Length + 1)..];
                if (kind == "camera")
                    return catalogue.Cameras.Single(camera => camera.Code == key).CameraId.ToString("D");
                var code = key[..key.IndexOf('/', StringComparison.Ordinal)];
                var itemName = key[(code.Length + 1)..];
                var owner = catalogue.Cameras.Single(camera => camera.Code == code);
                return kind == "zone"
                    ? owner.Zones.Single(zone => zone.Name == itemName).ZoneId.ToString("D")
                    : owner.Lines.Single(line => line.Name == itemName).LineId.ToString("D");
            default:
                return node;
        }
    }

    /// <summary>The outcome of a question the platform refused before the model (prompt v2): the same form as the
    /// model's own refusal, so it matches an expected <c>unknown_reference</c>; recordings mark it with its stage.</summary>
    public const string PreCheckOutcome = "refusal:" + AskCodes.UnknownReference;

    /// <summary>
    /// What an outcome is, for comparison: <c>refusal:&lt;reason&gt;</c> for a model refusal, the canonical query for a
    /// query, or <c>refused:&lt;stage&gt;:&lt;code&gt;</c> when the translator or parser refused the output.
    /// </summary>
    public static string Outcome(AskTranslation translation) =>
        translation.Refusal is { } refusal
            ? refusal.Stage == AskCodes.StageModel ? $"refusal:{refusal.Code}" : $"refused:{refusal.Stage}:{refusal.Code}"
            : StructuredQueryCanonical.Write(translation.Query!);

    /// <summary>The expected outcome, in the same form (the expected query canonicalised by the strict parser).</summary>
    public static string ExpectedOutcome(JsonObject resolvedExpect)
    {
        if ((string)resolvedExpect["answer"]! == "refusal")
            return $"refusal:{(string)resolvedExpect["reason"]!}";
        var parsed = StructuredQueryParser.Parse(resolvedExpect["query"]!.ToJsonString());
        if (parsed.Refusal is { } refusal)
            throw new InvalidOperationException($"An expected query is refused by the parser: {refusal.Code} at {refusal.Path}.");
        return StructuredQueryCanonical.Write(parsed.Query!);
    }

    /// <summary>SHA-256 of a text fixture with LF line endings, so a Windows checkout hashes as CI does.</summary>
    public static string TextSha256(string relative) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(Read(relative).Replace("\r\n", "\n", StringComparison.Ordinal))));

    private static string FindRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "MAVI.sln")))
            directory = directory.Parent;
        return directory?.FullName ?? throw new InvalidOperationException("Repository root not found.");
    }
}
