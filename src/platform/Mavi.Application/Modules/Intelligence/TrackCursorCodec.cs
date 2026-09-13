using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Mavi.Application.Modules.Intelligence;

public sealed class TrackCursorCodec
{
    public const int MaximumEncodedLength = 256;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    public string Encode(TrackCursorPosition position)
    {
        var payload = JsonSerializer.SerializeToUtf8Bytes(
            new CursorPayload(
                1,
                position.StartTimestampUtc.ToUniversalTime(),
                position.TrackId),
            JsonOptions);

        return Convert.ToBase64String(payload)
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');
    }

    public bool TryDecode(string? cursor, out TrackCursorPosition? position)
    {
        position = null;
        if (string.IsNullOrWhiteSpace(cursor) ||
            cursor.Length > MaximumEncodedLength ||
            cursor.Any(character =>
                !(character is >= 'A' and <= 'Z' or
                  >= 'a' and <= 'z' or
                  >= '0' and <= '9' or '-' or '_')))
        {
            return false;
        }

        try
        {
            var base64 = cursor.Replace('-', '+').Replace('_', '/');
            var padding = base64.Length % 4;
            if (padding == 1)
                return false;
            if (padding != 0)
                base64 = base64.PadRight(base64.Length + (4 - padding), '=');

            var bytes = Convert.FromBase64String(base64);
            if (bytes.Length > MaximumEncodedLength)
                return false;

            var payload = JsonSerializer.Deserialize<CursorPayload>(bytes, JsonOptions);
            if (payload is null ||
                payload.Version != 1 ||
                payload.TrackId == Guid.Empty ||
                payload.TrackId.Version != 7 ||
                payload.StartTimestampUtc.Offset != TimeSpan.Zero)
            {
                return false;
            }

            position = new TrackCursorPosition(
                payload.StartTimestampUtc,
                payload.TrackId);
            return true;
        }
        catch (Exception exception) when (
            exception is FormatException or JsonException or ArgumentException)
        {
            return false;
        }
    }

    private sealed record CursorPayload(
        int Version,
        DateTimeOffset StartTimestampUtc,
        Guid TrackId);
}
