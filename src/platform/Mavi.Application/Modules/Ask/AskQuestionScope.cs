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
/// <para>Prompt v2 (ADR-026 amendment D-S10-9) tightens and extends it: a name with one significant word ("Crossing")
/// is named only by "&lt;name&gt; &lt;kind&gt;" ("crossing zone"), and one that ends in its kind ("Count line") only by
/// that phrase; a line side labelled "In" or "Out" only through a
/// synonym or a verb phrase ("went in"), and "To door" or "From door" only through its phrase; and every place the
/// question refers to (<see cref="AskPlaceReferences"/>: "the Highway camera", "camera 7", "Macedonia Square") names
/// the items whose names contain its words. v1 is kept unchanged for its recordings.</para>
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

    public static AskQuestionScope From(string question, AskSiteCatalogue catalogue, QueryContractResponse vocabulary) =>
        From(question, catalogue, vocabulary, AskPrompt.TemplateVersion);

    public static AskQuestionScope From(string question, AskSiteCatalogue catalogue, QueryContractResponse vocabulary, string promptVersion)
    {
        ArgumentNullException.ThrowIfNull(question);
        ArgumentNullException.ThrowIfNull(catalogue);
        ArgumentNullException.ThrowIfNull(vocabulary);
        var v2 = AskPrompt.IsVersion2(promptVersion);
        var sequence = Words(question).ToList();
        var words = sequence.ToHashSet(StringComparer.Ordinal);
        // v2: the places the question refers to name the items whose names contain their words.
        var referenced = (Cameras: new HashSet<Guid>(), Zones: new HashSet<Guid>(), Lines: new HashSet<Guid>());
        if (v2)
        {
            foreach (var reference in AskPlaceReferences.Extract(question))
            {
                var (namedCameras, namedZones, namedLines) = AskPlaceReferences.Named(reference, catalogue);
                referenced.Cameras.UnionWith(namedCameras);
                referenced.Zones.UnionWith(namedZones);
                referenced.Lines.UnionWith(namedLines);
            }
        }

        var cameras = new HashSet<Guid>();
        var zones = new HashSet<Guid>();
        var lines = new HashSet<Guid>();
        var lineSides = new Dictionary<Guid, IReadOnlyList<string>>();
        foreach (var camera in catalogue.Cameras)
        {
            if (Names(ShortName(camera.Name), "camera", sequence, words, v2) || referenced.Cameras.Contains(camera.CameraId))
                cameras.Add(camera.CameraId);
            foreach (var zone in camera.Zones.Where(zone => Names(zone.Name, "zone", sequence, words, v2) || referenced.Zones.Contains(zone.ZoneId)))
            {
                zones.Add(zone.ZoneId);
                cameras.Add(camera.CameraId);
            }

            foreach (var line in camera.Lines.Where(line => Names(line.Name, "line", sequence, words, v2) || referenced.Lines.Contains(line.LineId)))
            {
                lines.Add(line.LineId);
                cameras.Add(camera.CameraId);
                var sides = new List<string>();
                if (Side(line.AToBLabel, sequence, words, v2))
                    sides.Add("aToB");
                if (Side(line.BToALabel, sequence, words, v2))
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

    /// <summary>Whether the words occur consecutively in the sequence.</summary>
    private static bool Phrase(IReadOnlyList<string> sequence, IReadOnlyList<string> phrase)
    {
        for (var start = 0; start + phrase.Count <= sequence.Count; start++)
        {
            if (phrase.Select((word, offset) => sequence[start + offset] == word).All(same => same))
                return true;
        }

        return false;
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

    public static bool IsStopWord(string word) => StopWords.Contains(word);

    private static bool Names(string name, string kind, IReadOnlyList<string> sequence, HashSet<string> words, bool v2)
    {
        var significant = Words(name).Where(word => !StopWords.Contains(word) && !word.Contains('-', StringComparison.Ordinal)).ToList();
        if (v2 && significant.Count == 1)
            return Phrase(sequence, [significant[0], kind]);
        // v2: a name that ends in its own kind ("Count line") is said as a phrase, not by "count ... line" anywhere.
        if (v2 && significant.Count > 1 && significant[^1] == kind)
            return Phrase(sequence, significant);
        return significant.Count > 0 && significant.All(words.Contains);
    }

    /// <summary>v2: verb phrases that say a line side labelled "In" or "Out" without the synonyms.</summary>
    private static readonly Dictionary<string, string[][]> SidePhrases = new(StringComparer.Ordinal)
    {
        ["in"] = [.. new[] { "went", "go", "goes", "going", "came", "come", "comes", "coming", "walked", "walking", "walk", "walks", "moved", "moving" }.Select(verb => new[] { verb, "in" })],
        ["out"] = [.. new[] { "went", "go", "goes", "going", "came", "come", "comes", "coming", "walked", "walking", "walk", "walks", "moved", "moving" }.Select(verb => new[] { verb, "out" })],
    };

    private static bool Side(string label, IReadOnlyList<string> sequence, HashSet<string> words, bool v2)
    {
        if (v2)
        {
            var labelWords = Words(label).ToList();
            // "To door", "From door": the phrase itself (articles in the question ignored), never the bare noun.
            if (labelWords.Count > 1 && labelWords[0] is "to" or "from")
            {
                var bare = sequence.Where(word => word is not ("the" or "a")).ToList();
                return Phrase(bare, labelWords) ||
                    (labelWords[0] == "to" && (Phrase(bare, ["towards", .. labelWords.Skip(1)]) || Phrase(bare, ["toward", .. labelWords.Skip(1)])));
            }

            // "In", "Out": a synonym or a verb phrase, never the bare preposition.
            if (labelWords is [var only] && SidePhrases.TryGetValue(only, out var phrases))
            {
                return (DirectionSynonyms.TryGetValue(only, out var synonyms) && synonyms.Any(words.Contains)) ||
                    phrases.Any(phrase => Phrase(sequence, phrase));
            }
        }

        var significant = Words(label).Where(word => word is not ("to" or "from" or "the")).ToList();
        if (significant.Count > 0 && significant.All(words.Contains))
            return true;
        return significant.Any(word => DirectionSynonyms.TryGetValue(word, out var synonyms) && synonyms.Any(words.Contains));
    }
}
