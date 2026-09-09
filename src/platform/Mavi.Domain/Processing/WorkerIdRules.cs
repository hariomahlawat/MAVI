namespace Mavi.Domain.Processing;

internal static class WorkerIdRules
{
    // Canonical worker identity
    internal static bool IsCanonical(string? value)
    {
        if (value is not { Length: >= 1 and <= 128 } || !IsAsciiAlphaNumeric(value[0])) return false;
        foreach (var character in value.AsSpan(1))
        {
            if (!IsContinuation(character)) return false;
        }
        return true;
    }

    private static bool IsContinuation(char value) =>
        IsAsciiAlphaNumeric(value) || value is '.' or '_' or '-';

    private static bool IsAsciiAlphaNumeric(char value) =>
        value is >= 'A' and <= 'Z' or >= 'a' and <= 'z' or >= '0' and <= '9';
}
