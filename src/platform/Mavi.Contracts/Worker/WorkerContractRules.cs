using System.Buffers.Text;

namespace Mavi.Contracts.Worker;

public static class WorkerContractRules
{
    public const string SchemaVersion = "2.0";

    // Worker boundary rules
    public static bool TryNormalizeWorkerId(string? value, out string normalized)
    {
        normalized = value?.Trim() ?? string.Empty;
        return normalized.Length is >= 1 and <= 128;
    }

    public static bool IsCanonicalLeaseToken(string? value)
    {
        if (value is not { Length: 43 }) return false;
        Span<byte> decoded = stackalloc byte[32];
        return Base64Url.TryDecodeFromChars(value, decoded, out var written) && written == 32;
    }

    public static bool IsLogicalStorageKey(string? value)
    {
        if (value is null || value.Length is < 1 or > 512 || value[0] == '/' || value[^1] == '/' ||
            value.Contains('\\', StringComparison.Ordinal) || value.Contains(':', StringComparison.Ordinal)) return false;
        return value.Split('/').All(segment => segment.Length > 0 && segment is not "." and not "..");
    }
}
