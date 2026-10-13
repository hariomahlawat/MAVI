using System.Text;
using System.Text.RegularExpressions;

namespace Mavi.Application.Modules.Plates;

/// <summary>The outcome of normalising one raw plate reading.</summary>
/// <param name="Raw">The raw OCR text, unchanged.</param>
/// <param name="Normalised">The normalised text, or <c>null</c> when the reading was rejected.</param>
/// <param name="Outcome"><c>ok</c> or <c>rejected</c>.</param>
/// <param name="Reason"><c>empty</c> or <c>non-alphanumeric</c> when rejected; otherwise <c>null</c>.</param>
/// <param name="FormatClass">Advisory <c>in-bh</c>, <c>in-standard</c> or <c>other</c>; <c>null</c> when rejected.</param>
public sealed record NormalisedPlate(string Raw, string? Normalised, string Outcome, string? Reason, string? FormatClass);

/// <summary>
/// <c>mavi-plate-normalisation-v1</c> (Stage 4 plan §5.2): raw OCR text to searchable normalised plate text.
/// </summary>
/// <remarks>
/// The rules are the contract in <c>contracts/test-vectors/plate-normalisation-v1.json</c>, which the Python
/// benchmark tooling (<c>tools/benchmarks/plates/normalisation.py</c>) implements identically. NFKC; ASCII-only
/// upper-casing; removal of exactly TAB, LF, CR, SPACE, '-', '.', '/', ':' and U+00B7; anything else outside
/// <c>[A-Z0-9]</c> rejects the reading. There is no confusable substitution, insertion, grammar repair or length
/// rule, and the format class never changes the text.
/// </remarks>
public static class PlateNormalisation
{
    public const string NormalisationId = "mavi-plate-normalisation-v1";
    public const string Ok = "ok";
    public const string Rejected = "rejected";
    public const string Empty = "empty";
    public const string NonAlphanumeric = "non-alphanumeric";

    private static readonly Regex InBh = new("^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$", RegexOptions.CultureInvariant);
    private static readonly Regex InStandard = new("^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{1,4}$", RegexOptions.CultureInvariant);

    /// <summary>Normalises one raw reading. Ill-formed UTF-16 (a lone surrogate) is refused.</summary>
    /// <exception cref="ArgumentException">The input is not well-formed Unicode.</exception>
    public static NormalisedPlate Normalise(string raw)
    {
        ArgumentNullException.ThrowIfNull(raw);
        if (!IsWellFormed(raw)) throw new ArgumentException("plate_normalisation_input_ill_formed", nameof(raw));
        string composed;
        try
        {
            composed = raw.Normalize(NormalizationForm.FormKC);
        }
        catch (ArgumentException)
        {
            // Well-formed text the OS normaliser refuses (a noncharacter such as U+FFFE). NFKC maps such a code
            // point to itself, so it would remain outside [A-Z0-9]: rule 5 rejects it, as the Python side does.
            return new NormalisedPlate(raw, null, Rejected, NonAlphanumeric, null);
        }

        var builder = new StringBuilder(composed.Length);
        foreach (var character in composed)
        {
            if (IsSeparator(character)) continue;
            builder.Append(character is >= 'a' and <= 'z' ? (char)(character - 32) : character);
        }

        var text = builder.ToString();
        if (text.Length == 0) return new NormalisedPlate(raw, null, Rejected, Empty, null);
        foreach (var character in text)
        {
            if (character is not (>= 'A' and <= 'Z' or >= '0' and <= '9'))
                return new NormalisedPlate(raw, null, Rejected, NonAlphanumeric, null);
        }

        return new NormalisedPlate(raw, text, Ok, null, FormatClass(text));
    }

    /// <summary>The advisory format class of an already normalised text.</summary>
    public static string FormatClass(string normalised)
    {
        if (InBh.IsMatch(normalised)) return "in-bh";
        if (InStandard.IsMatch(normalised)) return "in-standard";
        return "other";
    }

    private static bool IsWellFormed(string text)
    {
        for (var index = 0; index < text.Length; index++)
        {
            if (char.IsHighSurrogate(text[index]) && index + 1 < text.Length && char.IsLowSurrogate(text[index + 1]))
                index++;
            else if (char.IsSurrogate(text[index]))
                return false;
        }

        return true;
    }

    private static bool IsSeparator(char character) =>
        character is '\t' or '\n' or '\r' or ' ' or '-' or '.' or '/' or ':' or '·';
}
