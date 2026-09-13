using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Mavi.Application.Modules.Intelligence;

public static class TrackCursorCodec
{
    public const int MaximumEncodedLength = 512;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    public static string Encode(TrackCursorPosition position)
    {
        var payload = JsonSerializer.SerializeToUtf8Bytes(
            new CursorPayload(
                1,
                position.SnapshotUtc.ToUniversalTime(),
                position.StartTimestampUtc.ToUniversalTime(),
                position.TrackId,
                position.FilterFingerprint),
            JsonOptions);

        var encoded = Convert.ToBase64String(payload)
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');
        if (encoded.Length > MaximumEncodedLength)
            throw new InvalidOperationException(
                "Task 14 cursor exceeded its published size envelope.");
        return encoded;
    }

    public static bool TryDecode(string? cursor, out TrackCursorPosition? position)
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
                payload.SnapshotUtc.Offset != TimeSpan.Zero ||
                payload.StartTimestampUtc.Offset != TimeSpan.Zero ||
                !IsSha256(payload.FilterFingerprint))
            {
                return false;
            }

            position = new TrackCursorPosition(
                payload.SnapshotUtc,
                payload.StartTimestampUtc,
                payload.TrackId,
                payload.FilterFingerprint);
            return true;
        }
        catch (Exception exception) when (
            exception is FormatException or JsonException or ArgumentException)
        {
            return false;
        }
    }

    public static string ComputeFilterFingerprint(TrackSearchQuery query)
    {
        ArgumentNullException.ThrowIfNull(query);
        var payload = JsonSerializer.SerializeToUtf8Bytes(
            new FilterPayload(
                query.CameraId,
                query.VideoAssetId,
                query.ProcessingRunId,
                query.ObjectClass,
                query.FromUtc?.ToUniversalTime(),
                query.ToUtc?.ToUniversalTime(),
                query.MinimumDurationMs,
                query.MinimumConfidence),
            JsonOptions);
        return Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
    }

    private static bool IsSha256(string? value) =>
        value is { Length: 64 } &&
        value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private sealed record CursorPayload(
        int Version,
        DateTimeOffset SnapshotUtc,
        DateTimeOffset StartTimestampUtc,
        Guid TrackId,
        string FilterFingerprint);

    private sealed record FilterPayload(
        Guid? CameraId,
        Guid? VideoAssetId,
        Guid? ProcessingRunId,
        Mavi.Domain.Intelligence.ObjectClass? ObjectClass,
        DateTimeOffset? FromUtc,
        DateTimeOffset? ToUtc,
        long? MinimumDurationMs,
        double? MinimumConfidence);
}
