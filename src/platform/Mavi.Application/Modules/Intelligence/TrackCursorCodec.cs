using System.Buffers.Text;
using System.Text;
using System.Text.Json;

namespace Mavi.Application.Modules.Intelligence;

public sealed class TrackCursorCodec
{
    public const int MaximumEncodedLength = 256;

    public string Encode(TrackCursorPosition position)
    {
        var payload = JsonSerializer.SerializeToUtf8Bytes(new CursorPayload(
            1,
            position.StartTimestampUtc.ToUniversalTime(),
            position.TrackId));
        return Base64Url.EncodeToString(payload);
    }

    public bool TryDecode(string? cursor, out TrackCursorPosition? position)
    {
        position = null;
        if (string.IsNullOrWhiteSpace(cursor) || cursor.Length > MaximumEncodedLength)
            return false;

        try
        {
            Span<byte> buffer = stackalloc byte[MaximumEncodedLength];
            if (!Base64Url.DecodeFromChars(cursor, buffer, out var written))
                return false;

            var payload = JsonSerializer.Deserialize<CursorPayload>(
                buffer[..written],
                new JsonSerializerOptions
                {
                    PropertyNameCaseInsensitive = false,
                    UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
                });
            if (payload is null ||
                payload.Version != 1 ||
                payload.TrackId == Guid.Empty ||
                payload.TrackId.Version != 7 ||
                payload.StartTimestampUtc.Offset != TimeSpan.Zero)
                return false;

            position = new TrackCursorPosition(
                payload.StartTimestampUtc.ToUniversalTime(),
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
