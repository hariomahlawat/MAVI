using System.Text.RegularExpressions;

namespace Mavi.Domain.Processing;

internal static partial class WorkerIdRules
{
    // Canonical worker identity
    internal static bool IsCanonical(string? value) =>
        value is not null && CanonicalPattern().IsMatch(value);

    [GeneratedRegex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", RegexOptions.CultureInvariant)]
    private static partial Regex CanonicalPattern();
}
