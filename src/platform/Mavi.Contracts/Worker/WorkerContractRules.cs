using System.Buffers.Text;
using System.Text.RegularExpressions;

namespace Mavi.Contracts.Worker;

public static partial class WorkerContractRules
{
    public const string SchemaVersion = "2.0";

    // Worker identity rules
    public static bool IsCanonicalWorkerId(string? value) =>
        value is not null && WorkerIdPattern().IsMatch(value);

    public static bool TryNormalizeWorkerId(string? value, out string normalized)
    {
        normalized = value ?? string.Empty;
        return IsCanonicalWorkerId(value);
    }

    public static bool IsCanonicalLeaseToken(string? value)
    {
        if (value is not { Length: 43 }) return false;
        Span<byte> decoded = stackalloc byte[32];
        try
        {
            return Base64Url.TryDecodeFromChars(value, decoded, out var written) && written == 32 &&
                   string.Equals(Base64Url.EncodeToString(decoded), value, StringComparison.Ordinal);
        }
        catch (FormatException)
        {
            return false;
        }
    }

    public static bool IsFailureCode(string? value) => value is not null && FailureCodePattern().IsMatch(value);

    public static bool IsLogicalStorageKey(string? value)
    {
        if (value is null || value.Length is < 1 or > 512 || value[0] == '/' || value[^1] == '/' ||
            value.Contains('\\', StringComparison.Ordinal) || value.Contains(':', StringComparison.Ordinal)) return false;
        return value.Split('/').All(segment => segment.Length > 0 && segment is not "." and not "..");
    }

    [GeneratedRegex("^[a-z][a-z0-9_]{0,63}$", RegexOptions.CultureInvariant)]
    private static partial Regex FailureCodePattern();

    [GeneratedRegex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", RegexOptions.CultureInvariant)]
    private static partial Regex WorkerIdPattern();
}
