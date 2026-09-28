namespace Mavi.Domain.Common;

/// <summary>
/// The platform's one representation of a SHA-256 digest: exactly 64 lower-case ASCII
/// hexadecimal characters (S2b plan §6; ADR-013 §9 shared primitives).
/// </summary>
/// <remarks>
/// Deliberately an ordinal character check, not a regular expression: <c>$</c> in a
/// .NET pattern also matches before a final line feed, which would admit a 65-character
/// value that ends in <c>\n</c>.
/// </remarks>
public static class CanonicalSha256
{
    public const int ByteLength = 32;
    public const int HexLength = 64;

    public static bool IsCanonical(string? value)
    {
        if (value is not { Length: HexLength }) return false;
        foreach (var character in value)
        {
            if (character is not (>= '0' and <= '9' or >= 'a' and <= 'f')) return false;
        }

        return true;
    }

    public static string ToHex(ReadOnlySpan<byte> digest)
    {
        if (digest.Length != ByteLength)
            throw new ArgumentException("A SHA-256 digest is exactly 32 bytes.", nameof(digest));
        return Convert.ToHexStringLower(digest);
    }
}
