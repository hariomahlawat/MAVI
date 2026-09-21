using System.Security.Cryptography;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>
/// The per-installation key that authenticates analytic cursors.
/// </summary>
/// <remarks>
/// Held as bytes with no string form: <see cref="ToString"/> says nothing about the
/// material, so an interpolated log line cannot leak it by accident, and nothing here
/// exposes it as text. The bytes are read only by <see cref="TrackCursorCodec"/>.
/// </remarks>
public sealed class TrackCursorSigningKey
{
    /// <summary>HMAC-SHA-256 keys are exactly this long; nothing shorter or longer is accepted.</summary>
    public const int KeyByteLength = 32;

    private readonly byte[] _key;

    private TrackCursorSigningKey(byte[] key, bool isEphemeral)
    {
        _key = key;
        IsEphemeral = isEphemeral;
    }

    /// <summary>True when the key was minted for this process rather than read from configuration.</summary>
    public bool IsEphemeral { get; }

    internal ReadOnlySpan<byte> Bytes => _key;

    /// <summary>A key from configuration, or an ephemeral one where that is allowed.</summary>
    /// <exception cref="InvalidOperationException">
    /// The configured value is not exactly 32 base64-encoded bytes, or no key is
    /// configured and an ephemeral key is not allowed.
    /// </exception>
    public static TrackCursorSigningKey FromOptions(TrackSearchOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);

        if (!string.IsNullOrWhiteSpace(options.CursorSigningKey))
        {
            if (!TryDecode(options.CursorSigningKey, out var configured))
            {
                throw new InvalidOperationException(
                    $"{TrackSearchOptions.SectionName}:CursorSigningKey must be the base64 encoding of exactly {KeyByteLength} bytes.");
            }

            return new TrackCursorSigningKey(configured, isEphemeral: false);
        }

        if (options.AllowEphemeralCursorSigningKey)
        {
            return CreateEphemeral();
        }

        throw new InvalidOperationException(
            $"{TrackSearchOptions.SectionName}:CursorSigningKey is required. Setup writes it to the machine configuration; " +
            $"only a Development or Testing host may set {TrackSearchOptions.SectionName}:AllowEphemeralCursorSigningKey instead.");
    }

    /// <summary>A random key that lives as long as this process.</summary>
    public static TrackCursorSigningKey CreateEphemeral() =>
        new(RandomNumberGenerator.GetBytes(KeyByteLength), isEphemeral: true);

    /// <summary>A key from raw bytes, for tests and for setup tooling that mints one.</summary>
    public static TrackCursorSigningKey FromBytes(ReadOnlySpan<byte> key)
    {
        if (key.Length != KeyByteLength)
        {
            throw new ArgumentException($"A cursor signing key is exactly {KeyByteLength} bytes.", nameof(key));
        }

        return new TrackCursorSigningKey(key.ToArray(), isEphemeral: false);
    }

    /// <summary>Whether a configured value is well-formed, without keeping the bytes.</summary>
    public static bool IsWellFormed(string? value) =>
        !string.IsNullOrWhiteSpace(value) && TryDecode(value, out _);

    /// <summary>Deliberately says nothing about the key.</summary>
    public override string ToString() =>
        IsEphemeral ? "TrackCursorSigningKey(ephemeral)" : "TrackCursorSigningKey(configured)";

    private static bool TryDecode(string value, out byte[] key)
    {
        key = [];
        var buffer = new byte[KeyByteLength + 3];
        if (!Convert.TryFromBase64String(value.Trim(), buffer, out var written) || written != KeyByteLength)
        {
            return false;
        }

        key = buffer[..KeyByteLength];
        return true;
    }
}
