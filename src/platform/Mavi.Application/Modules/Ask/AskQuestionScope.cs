using System.Text.RegularExpressions;
using Mavi.Contracts.Api.Query;

namespace Mavi.Application.Modules.Ask;

/// <summary>
/// Lexical gating of the decoding grammar (ADR-026 §4): which references and predicates the question names, so the
/// model can only write those. A camera, zone or line is named when every significant word of its name occurs in the
/// question (a camera is also named through a zone or line of its own); a line direction when the word on that side
/// of the line (or a fixed synonym) occurs, and then only that side; an attribute value when the value occurs; a plate, a rule, a vehicle
/// subclass, an object class or the Entity unit when their fixed words occur; a rule only beside an event noun
/// ("events", "crossings"), so a Track question that says "dwelled" is not offered event rules. A pure function of the question and the catalogue: it
/// only ever removes choices, and a predicate it removes cannot be written, so the query (shown as "Interpreted as")
/// lacks it rather than gaining one nobody asked for.
/// </summary>
public sealed record AskQuestionScope(
    IReadOnlySet<Guid> Cameras,
    IReadOnlySet<Guid> Zones,
    IReadOnlySet<Guid> Lines,
    IReadOnlyDictionary<Guid, IReadOnlyList<string>> LineSides,
    IReadOnlyDictionary<string, IReadOnlyList<string>> AttributeValues,
    IReadOnlyList<string> ObjectClasses,
    bool Plate,
    IReadOnlyList<string> Rules,
    bool Subclass,
    bool Entity,
    bool Duration)
{
    private static readonly Regex Word = new("[a-z0-9]+(?:-[a-z0-9]+)*", RegexOptions.CultureInvariant);

    /// <summary>Words that never make a name specific. "line" and "zone" are not among them: a zone or line named
    /// "Count line" is named only by a question that says "count line", not by every question that says "count".</summary>
    private static readonly HashSet<string> StopWords =
        new(StringComparer.Ordinal) { "the", "a", "an", "of", "at", "in", "on", "to", "and", "poc", "demo" };

    /// <summary>Synonyms of the words operators put on a line's two sides.</summary>
    private static readonly Dictionary<string, string[]> DirectionSynonyms = new(StringComparer.Ordinal)
    {
        ["entry"] = ["enter", "entered", "entering", "enters", "entries", "entrance"],
        ["exit"] = ["exit", "exited", "exiting", "exits", "left", "leaving", "leave", "leaves"],
        ["in"] = ["into", "enter", "entered", "entering"],
        ["out"] = ["exited", "exiting", "left", "leaving"],
        ["toward"] = ["towards", "approaching"],
        ["away"] = ["departing"],
        ["inbound"] = ["incoming"],
        ["outbound"] = ["outgoing"],
    };

    private static readonly Dictionary<string, string[]> RuleWords = new(StringComparer.Ordinal)
    {
        ["line-crossing"] = ["crossing", "crossings", "crossed", "cross"],
        ["zone-dwell"] = ["dwell", "dwells", "dwelled", "dwelling"],
        ["stopped-vehicle"] = ["stopped", "stationary"],
        ["wrong-way"] = ["wrong-way", "wrong"],
        ["co-occurrence"] = ["co-occurrence", "co-occurrences", "cooccurrence", "together"],
        ["repeated-visit"] = ["repeated", "revisit", "revisits", "visits"],
    };

    private static readonly Dictionary<string, string[]> ClassWords = new(StringComparer.Ordinal)
    {
        ["Person"] = ["person", "persons", "people", "pedestrian", "pedestrians", "man", "men", "woman", "women", "someone", "anyone"],
        ["Vehicle"] = ["vehicle", "vehicles", "car", "cars", "truck", "trucks", "bus", "buses", "van", "vans", "motorbike", "motorbikes"],
    };

    /// <summary>Nouns that make a question about events.</summary>
    private static readonly string[] EventNouns = ["event", "events", "crossings", "dwells", "co-occurrences", "visits"];

    private static readonly string[] AttributeTypeBag = ["bag", "bags", "backpack", "backpacks", "handbag", "rucksack"];
    private static readonly string[] AttributeTypeHeadwear = ["hat", "hats", "cap", "caps", "helmet", "headwear", "hood"];
    private static readonly string[] DurationWords = ["longer", "duration", "lasting", "lasted", "seconds", "second", "minutes", "minute"];

    public static AskQuestionScope From(string question, AskSiteCatalogue catalogue, QueryContractResponse vocabulary)
    {
        ArgumentNullException.ThrowIfNull(question);
        ArgumentNullException.ThrowIfNull(catalogue);
        ArgumentNullException.ThrowIfNull(vocabulary);
        var words = Words(question).ToHashSet(StringComparer.Ordinal);

        var cameras = new HashSet<Guid>();
        var zones = new HashSet<Guid>();
        var lines = new HashSet<Guid>();
        var lineSides = new Dictionary<Guid, IReadOnlyList<string>>();
        foreach (var camera in catalogue.Cameras)
        {
            if (Names(ShortName(camera.Name), words))
                cameras.Add(camera.CameraId);
            foreach (var zone in camera.Zones.Where(zone => Names(zone.Name, words)))
            {
                zones.Add(zone.ZoneId);
                cameras.Add(camera.CameraId);
            }

            foreach (var line in camera.Lines.Where(line => Names(line.Name, words)))
            {
                lines.Add(line.LineId);
                cameras.Add(camera.CameraId);
                var sides = new List<string>();
                if (Side(line.AToBLabel, words))
                    sides.Add("aToB");
                if (Side(line.BToALabel, words))
                    sides.Add("bToA");
                lineSides[line.LineId] = sides;
            }
        }

        var attributeValues = new Dictionary<string, IReadOnlyList<string>>(StringComparer.Ordinal);
        foreach (var attribute in vocabulary.Attributes)
        {
            var values = attribute.Values.Where(value => value == "present"
                ? (attribute.Type.Contains("bag", StringComparison.Ordinal) ? AttributeTypeBag : AttributeTypeHeadwear).Any(words.Contains)
                : words.Contains(value)).ToList();
            if (values.Count > 0)
                attributeValues[attribute.Type] = values;
        }

        var rules = EventNouns.Any(words.Contains)
            ? vocabulary.EventRuleIds.Where(rule => RuleWords.TryGetValue(rule, out var triggers) && triggers.Any(words.Contains)).ToList()
            : [];
        var classes = vocabulary.ObjectClasses.Where(objectClass => ClassWords.TryGetValue(objectClass, out var triggers) && triggers.Any(words.Contains)).ToList();
        return new AskQuestionScope(
            cameras,
            zones,
            lines,
            lineSides,
            attributeValues,
            classes,
            words.Contains("plate") || words.Contains("plates") || words.Contains("registration"),
            rules,
            vocabulary.ObjectSubclasses.Any(subclass => words.Contains(subclass) || words.Contains(subclass + "s")),
            words.Contains("entity") || words.Contains("entities"),
            DurationWords.Any(words.Contains));
    }

    /// <summary>Lower-case words; hyphenated words are kept whole and also split.</summary>
    public static IEnumerable<string> Words(string text)
    {
        foreach (Match match in Word.Matches(text.ToLowerInvariant()))
        {
            yield return match.Value;
            if (match.Value.Contains('-', StringComparison.Ordinal))
            {
                foreach (var part in match.Value.Split('-'))
                    yield return part;
            }
        }
    }

    /// <summary>A camera's name as an operator says it: without a "PoC demo NN - " prefix or a trailing "(…)".</summary>
    public static string ShortName(string name)
    {
        var separator = name.IndexOf(" - ", StringComparison.Ordinal);
        var shortName = separator >= 0 ? name[(separator + 3)..] : name;
        var bracket = shortName.IndexOf(" (", StringComparison.Ordinal);
        return bracket >= 0 ? shortName[..bracket] : shortName;
    }

    private static bool Names(string name, HashSet<string> words)
    {
        var significant = Words(name).Where(word => !StopWords.Contains(word) && !word.Contains('-', StringComparison.Ordinal)).ToList();
        return significant.Count > 0 && significant.All(words.Contains);
    }

    private static bool Side(string label, HashSet<string> words)
    {
        var significant = Words(label).Where(word => word is not ("to" or "from" or "the")).ToList();
        if (significant.Count > 0 && significant.All(words.Contains))
            return true;
        return significant.Any(word => DirectionSynonyms.TryGetValue(word, out var synonyms) && synonyms.Any(words.Contains));
    }
}
