using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Mavi.Contracts.Worker;

public sealed class UtcDateTimeOffsetJsonConverter : JsonConverter<DateTimeOffset>
{
    // Contract timestamp handling
    public override DateTimeOffset Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType != JsonTokenType.String)
            throw new JsonException("Worker contract timestamps must be JSON strings.");

        var raw = reader.GetString();
        if (string.IsNullOrEmpty(raw) || !raw.EndsWith('Z'))
            throw new JsonException("Worker contract timestamps must use canonical UTC Z syntax.");

        if (!reader.TryGetDateTimeOffset(out var value) || value.Offset != TimeSpan.Zero)
            throw new JsonException("Worker contract timestamps must use canonical RFC3339 UTC Z syntax.");

        return value;
    }

    public override void Write(Utf8JsonWriter writer, DateTimeOffset value, JsonSerializerOptions options) =>
        writer.WriteStringValue(value.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.FFFFFFF'Z'", CultureInfo.InvariantCulture));
}
