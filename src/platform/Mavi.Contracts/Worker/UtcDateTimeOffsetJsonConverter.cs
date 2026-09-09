using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace Mavi.Contracts.Worker;

public sealed class UtcDateTimeOffsetJsonConverter : JsonConverter<DateTimeOffset>
{
    private static readonly Regex CanonicalUtcPattern = new(
        @"^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?Z\z",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);

    // Contract timestamp handling
    public override DateTimeOffset Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType != JsonTokenType.String)
            throw new JsonException("Worker contract timestamps must be JSON strings.");

        var raw = reader.GetString();
        if (string.IsNullOrEmpty(raw) || !CanonicalUtcPattern.IsMatch(raw))
            throw new JsonException("Worker contract timestamps must use canonical RFC3339 UTC Z syntax.");

        if (!reader.TryGetDateTimeOffset(out var value) || value.Offset != TimeSpan.Zero)
            throw new JsonException("Worker contract timestamps must be valid UTC instants.");

        return value;
    }

    public override void Write(Utf8JsonWriter writer, DateTimeOffset value, JsonSerializerOptions options) =>
        writer.WriteStringValue(value.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.FFFFFFF'Z'", CultureInfo.InvariantCulture));
}
