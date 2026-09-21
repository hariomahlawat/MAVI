namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// The closed vocabularies that derived facts persist as text.
/// </summary>
/// <remarks>
/// <para>
/// Headings, crossing directions and the reference point are produced by the
/// analysis engine in <c>Mavi.Application</c> as string constants, and the Domain
/// may not reference the Application layer. Rather than convert them to enums —
/// which would mean editing frozen slice-1 code from a persistence phase — the
/// same vocabulary is restated here for the persisted side, and
/// <c>SceneAnalyticsVocabularyTests</c> asserts the two lists are identical.
/// </para>
/// <para>
/// That test is the point. Two copies of a vocabulary drift silently; a copy with
/// an equality test drifts loudly, and the database check constraints built from
/// this list then cannot disagree with what the engine emits.
/// </para>
/// </remarks>
public static class SceneAnalyticsVocabulary
{
    /// <summary>Eight-way screen heading, plus "no discernible direction".</summary>
    /// <remarks>North means decreasing y. This is a screen direction, never a compass bearing.</remarks>
    public static readonly IReadOnlyList<string> Headings =
        ["None", "N", "NE", "E", "SE", "S", "SW", "W", "NW"];

    /// <summary>Which way a trip line was crossed, relative to its own endpoints.</summary>
    public static readonly IReadOnlyList<string> CrossingDirections = ["AToB", "BToA"];

    /// <summary>The point on a detection that a trajectory sample records.</summary>
    public static readonly IReadOnlyList<string> ReferencePoints = ["bbox-centre"];

    /// <summary>Longest member of any of the vocabularies, which fixes the column width.</summary>
    public const int MaximumLength = 32;

    public static bool IsHeading(string? value) => Contains(Headings, value);

    public static bool IsCrossingDirection(string? value) => Contains(CrossingDirections, value);

    public static bool IsReferencePoint(string? value) => Contains(ReferencePoints, value);

    /// <summary>Renders a vocabulary as a SQL <c>IN</c> list for a check constraint.</summary>
    /// <remarks>
    /// Built from the same list the entities validate against, so a value the domain
    /// accepts cannot be one the database rejects.
    /// </remarks>
    public static string ToSqlInList(IReadOnlyList<string> vocabulary) =>
        string.Join(", ", vocabulary.Select(value => $"'{value}'"));

    private static bool Contains(IReadOnlyList<string> allowed, string? value)
    {
        if (value is null)
        {
            return false;
        }

        for (var index = 0; index < allowed.Count; index++)
        {
            if (string.Equals(allowed[index], value, StringComparison.Ordinal))
            {
                return true;
            }
        }

        return false;
    }
}
