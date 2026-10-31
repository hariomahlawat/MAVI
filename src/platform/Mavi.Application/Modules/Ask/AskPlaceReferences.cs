using System.Globalization;
using System.Text.RegularExpressions;

namespace Mavi.Application.Modules.Ask;

/// <summary>One place the question refers to: its kind (<c>camera</c>, <c>zone</c>, <c>line</c>, or <c>any</c> for a
/// capitalised name), its lower-case words, a number for "camera 7", and whether it is the word after the kind noun
/// ("line Leftward" may be a line side, not a name).</summary>
public sealed record AskPlaceReference(string Kind, IReadOnlyList<string> Words, int? Number, string Text, bool AfterKind = false);

/// <summary>
/// The places a question refers to (prompt v2, ADR-026 amendment D-S10-9), found by fixed patterns, before the model is
/// called:
/// <list type="bullet">
/// <item>the words before a singular kind noun (<c>camera</c>, <c>cam</c>, <c>zone</c>, <c>line</c>), back to an
/// article, a preposition, a question word or the sentence start ("the Loading dock zone"); fixed compounds such as
/// "line crossings", "line direction" and "zone dwell" are not references;</item>
/// <item>a kind noun followed by a number or a capitalised name ("camera 14", "zone C");</item>
/// <item>a run of two or more capitalised words that is not at a sentence start and is not contract vocabulary
/// ("Central Station").</item>
/// </list>
/// Each reference names the catalogue items whose names contain all its words (<see cref="AskQuestionScope"/> offers
/// them to the model). A reference that names nothing is a place the site does not have, and the request is refused
/// with <c>unknown_reference</c> instead of being answered for the whole site. A pure function of the question and the
/// catalogue; a place mentioned in none of these patterns ("the parking garage") is left to the model, as in v1.
/// </summary>
public static class AskPlaceReferences
{
    private static readonly Regex Token = new("[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", RegexOptions.CultureInvariant);
    private static readonly Regex Capitalised = new("^[A-Z][a-z]+(?:-[A-Za-z]+)*$", RegexOptions.CultureInvariant);

    private static readonly Dictionary<string, string> KindNouns = new(StringComparer.Ordinal)
    {
        ["camera"] = "camera",
        ["cam"] = "camera",
        ["zone"] = "zone",
        ["line"] = "line",
    };

    /// <summary>Words after a kind noun that make it part of a fixed phrase, not a reference.</summary>
    private static readonly Dictionary<string, string[]> Compounds = new(StringComparer.Ordinal)
    {
        ["line"] = ["crossing", "crossings", "direction", "directions"],
        ["zone"] = ["dwell", "dwells", "dwelling", "dwelled"],
    };

    /// <summary>Words that end a reference phrase: articles, prepositions, determiners, question and command words,
    /// unit and class nouns, and ranking adjectives ("the busiest camera" refers to no particular camera).</summary>
    private static readonly HashSet<string> Boundaries = new(StringComparer.Ordinal)
    {
        "the", "a", "an", "at", "in", "on", "of", "through", "across", "over", "into", "near", "past", "by", "per", "from",
        "to", "for", "with", "between", "and", "or", "via", "along", "under", "inside", "outside", "around", "behind",
        "toward", "towards", "beside", "within", "after", "before", "during", "since", "until", "than", "as",
        "crossing", "crossed", "cross", "crosses", "entered", "entering", "enter", "left", "leaving", "leave", "passed",
        "passing", "pass", "using", "used", "seen", "saw", "see", "tracked", "recorded", "walked", "drove", "went",
        "each", "every", "which", "what", "this", "that", "these", "those", "any", "all", "same", "other", "another",
        "one", "its", "their", "my", "our", "your", "busiest", "quietest", "first", "last", "next", "previous", "most",
        "least", "top", "given", "single", "specific", "particular", "whole", "entire",
        "how", "many", "much", "count", "show", "list", "find", "when", "where", "who", "why", "number", "total",
        "give", "get", "tell", "is", "are", "was", "were", "did", "do", "does", "there", "has", "had", "have", "me",
        "people", "person", "persons", "vehicle", "vehicles", "car", "cars", "track", "tracks", "event", "events",
        "entity", "entities", "today", "yesterday", "tomorrow", "s", "today's", "yesterday's", "tomorrow's",
        "daily", "hourly", "weekly", "nightly", "crowded", "fewest", "per-camera", "per-zone", "per-line", "totals",
        "counts",
    };

    /// <summary>Capitalised words that are never part of a place name (classes, units, time words, sentence verbs).</summary>
    private static readonly HashSet<string> NotNames = new(StringComparer.Ordinal)
    {
        "person", "persons", "people", "pedestrian", "pedestrians", "vehicle", "vehicles", "car", "cars", "truck",
        "trucks", "bus", "buses", "track", "tracks", "event", "events", "entity", "entities", "today", "yesterday",
        "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february",
        "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "show",
        "list", "count", "find", "how", "what", "which", "when", "where", "who", "why", "compare", "group", "top",
        "number", "is", "are", "was", "were", "did", "do", "does", "give", "tell", "please", "camera", "cam", "zone",
        "line", "cameras", "zones", "lines", "mavi", "ask",
        // Attribute words an operator may capitalise ("a Red Bag"): never place names.
        "black", "blue", "brown", "green", "grey", "gray", "orange", "pink", "purple", "red", "white", "yellow", "beige",
        "silver", "bag", "bags", "backpack", "backpacks", "handbag", "shirt", "shirts", "top", "jacket", "trousers",
        "skirt", "hat", "hats", "cap", "helmet", "hood",
    };

    public static IReadOnlyList<AskPlaceReference> Extract(string question)
    {
        ArgumentNullException.ThrowIfNull(question);
        var tokens = new List<(string Text, string Lower, bool SentenceStart)>();
        var previousEnd = 0;
        foreach (Match match in Token.Matches(question))
        {
            var gap = question[previousEnd..match.Index];
            tokens.Add((match.Value, match.Value.ToLowerInvariant(), tokens.Count == 0 || gap.IndexOfAny(['.', '?', '!', ';', ':']) >= 0));
            previousEnd = match.Index + match.Length;
        }

        var references = new List<AskPlaceReference>();
        for (var index = 0; index < tokens.Count; index++)
        {
            if (!KindNouns.TryGetValue(tokens[index].Lower, out var kind))
                continue;
            var next = index + 1 < tokens.Count && !tokens[index + 1].SentenceStart ? tokens[index + 1] : default;
            if (next.Lower is { } nextWord && Compounds.TryGetValue(kind, out var compounds) && compounds.Contains(nextWord, StringComparer.Ordinal))
                continue;

            if (next.Text is { } name)
            {
                if (name.All(char.IsAsciiDigit) && name.Length <= 4)
                    references.Add(new AskPlaceReference(kind, [name], int.Parse(name, CultureInfo.InvariantCulture), $"{tokens[index].Text} {name}"));
                else if ((Capitalised.IsMatch(name) && !NotNames.Contains(next.Lower) && !Boundaries.Contains(next.Lower)) ||
                         (name.Length == 1 && char.IsAsciiLetterUpper(name[0])))
                    references.Add(new AskPlaceReference(kind, [next.Lower], null, $"{tokens[index].Text} {name}", AfterKind: true));
            }

            var phrase = new List<int>();
            for (var before = index - 1; before >= 0 && phrase.Count < 4; before--)
            {
                if (Boundaries.Contains(tokens[before].Lower) || KindNouns.ContainsKey(tokens[before].Lower))
                    break;
                phrase.Insert(0, before);
                if (tokens[before].SentenceStart)
                    break;
            }

            if (phrase.Count > 0)
            {
                references.Add(new AskPlaceReference(
                    kind,
                    [.. phrase.Select(position => tokens[position].Lower)],
                    null,
                    string.Join(' ', phrase.Append(index).Select(position => tokens[position].Text))));
            }
        }

        // Runs of capitalised words, not counting a sentence's first word; the words that end a reference phrase
        // (verbs, prepositions, determiners, "per", "counts") also end a run, so "Entered Junction Box" is not a name.
        // A question typed in title case (nine words in ten capitalised) has no capitalisation signal, so this pattern
        // is not applied to it; "Count people at Central Station" is not title case.
        var words = tokens.Where(token => token.Text.Any(char.IsAsciiLetter) && token.Text.Length > 1).ToList();
        var titleCase = words.Count >= 4 && words.Count(token => char.IsAsciiLetterUpper(token.Text[0])) * 10 >= words.Count * 9;
        var run = new List<int>();
        void Close()
        {
            if (run.Count >= 2)
                references.Add(new AskPlaceReference("any", [.. run.Select(position => tokens[position].Lower)], null, string.Join(' ', run.Select(position => tokens[position].Text))));
            run.Clear();
        }

        for (var index = 0; index < tokens.Count; index++)
        {
            var token = tokens[index];
            if (titleCase || token.SentenceStart || !Capitalised.IsMatch(token.Text) || NotNames.Contains(token.Lower) || Boundaries.Contains(token.Lower))
                Close();
            else
                run.Add(index);
        }

        Close();
        return references;
    }

    /// <summary>The catalogue items a reference names: those of its kind whose names contain every one of its words
    /// (a camera also by the number its code ends with; a zone or line by a number its name contains, "Zone 1").</summary>
    public static (IReadOnlyList<Guid> Cameras, IReadOnlyList<Guid> Zones, IReadOnlyList<Guid> Lines) Named(AskPlaceReference reference, AskSiteCatalogue catalogue)
    {
        ArgumentNullException.ThrowIfNull(reference);
        ArgumentNullException.ThrowIfNull(catalogue);
        // Stop words are ignored, unless they are all the reference has ("zone A").
        var significant = reference.Words.Where(word => !AskQuestionScope.IsStopWord(word)).ToList();
        var words = significant.Count > 0 ? significant : [.. reference.Words];
        bool Contains(string name)
        {
            var nameWords = AskQuestionScope.Words(name).ToHashSet(StringComparer.Ordinal);
            return words.Count > 0 && words.All(nameWords.Contains);
        }

        var cameras = new List<Guid>();
        var zones = new List<Guid>();
        var lines = new List<Guid>();
        foreach (var camera in catalogue.Cameras)
        {
            if (reference.Kind is "camera" or "any" &&
                (reference.Number is { } number ? CameraNumber(camera) == number : Contains(camera.Name)))
                cameras.Add(camera.CameraId);
            if (reference.Number is { } itemNumber)
            {
                if (reference.Kind == "zone")
                    zones.AddRange(camera.Zones.Where(zone => NameNumbers(zone.Name).Contains(itemNumber)).Select(zone => zone.ZoneId));
                if (reference.Kind == "line")
                    lines.AddRange(camera.Lines.Where(line => NameNumbers(line.Name).Contains(itemNumber)).Select(line => line.LineId));
                continue;
            }

            if (reference.Kind is "zone" or "any")
                zones.AddRange(camera.Zones.Where(zone => Contains(zone.Name)).Select(zone => zone.ZoneId));
            if (reference.Kind is "line" or "any")
                lines.AddRange(camera.Lines.Where(line => Contains(line.Name)).Select(line => line.LineId));
        }

        return (cameras, zones, lines);
    }

    /// <summary>
    /// The references that name nothing in the catalogue: the places the site does not have. A word after "line" that
    /// is one of the site's line-side labels ("the Count line, Leftward") is a direction, not a name, and so is a side
    /// label ending a capitalised run ("the Arch Gate Entry").
    /// </summary>
    public static IReadOnlyList<AskPlaceReference> Unknown(string question, AskSiteCatalogue catalogue)
    {
        ArgumentNullException.ThrowIfNull(catalogue);
        var sideWords = catalogue.Cameras.SelectMany(camera => camera.Lines)
            .SelectMany(line => AskQuestionScope.Words(line.AToBLabel).Concat(AskQuestionScope.Words(line.BToALabel)))
            .ToHashSet(StringComparer.Ordinal);
        return [.. Extract(question)
            .Where(reference => !(reference.AfterKind && reference.Words.All(sideWords.Contains)))
            .Select(reference => reference.Kind == "any" ? WithoutTrailingSides(reference, sideWords) : reference)
            .Where(reference => reference.Words.Count > 0)
            .Where(reference => Named(reference, catalogue) is { Cameras.Count: 0, Zones.Count: 0, Lines.Count: 0 })];
    }

    private static AskPlaceReference WithoutTrailingSides(AskPlaceReference reference, HashSet<string> sideWords)
    {
        var words = reference.Words.ToList();
        while (words.Count > 0 && sideWords.Contains(words[^1]))
            words.RemoveAt(words.Count - 1);
        return reference with { Words = words };
    }

    private static HashSet<int> NameNumbers(string name) =>
        [.. AskQuestionScope.Words(name).Where(word => word.All(char.IsAsciiDigit) && word.Length <= 6).Select(word => int.Parse(word, CultureInfo.InvariantCulture))];

    /// <summary>The number a camera's code ends with ("POC-S2-07" is 7), or null.</summary>
    public static int? CameraNumber(AskCatalogueCamera camera)
    {
        ArgumentNullException.ThrowIfNull(camera);
        var digits = new string([.. camera.Code.Reverse().TakeWhile(char.IsAsciiDigit).Reverse()]);
        return digits.Length is > 0 and <= 6 ? int.Parse(digits, CultureInfo.InvariantCulture) : null;
    }
}
