using System.Text.Json;
using System.Text.Json.Serialization;

namespace Mavi.Contracts.Worker;

public sealed class IntegralNullableInt32JsonConverter : JsonConverter<int?>
{
    public override bool HandleNull => true;

    public override int? Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.Null) return null;
        if (reader.TokenType != JsonTokenType.Number ||
            !reader.TryGetDecimal(out var value) ||
            value != decimal.Truncate(value) ||
            value < int.MinValue ||
            value > int.MaxValue)
            throw new JsonException("Expected a mathematically integral Int32 JSON number.");

        return decimal.ToInt32(value);
    }

    public override void Write(Utf8JsonWriter writer, int? value, JsonSerializerOptions options)
    {
        if (value is null) writer.WriteNullValue();
        else writer.WriteNumberValue(value.Value);
    }
}

public sealed class IntegralNullableInt64JsonConverter : JsonConverter<long?>
{
    public override bool HandleNull => true;

    public override long? Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.Null) return null;
        if (reader.TokenType != JsonTokenType.Number ||
            !reader.TryGetDecimal(out var value) ||
            value != decimal.Truncate(value) ||
            value < long.MinValue ||
            value > long.MaxValue)
            throw new JsonException("Expected a mathematically integral Int64 JSON number.");

        return decimal.ToInt64(value);
    }

    public override void Write(Utf8JsonWriter writer, long? value, JsonSerializerOptions options)
    {
        if (value is null) writer.WriteNullValue();
        else writer.WriteNumberValue(value.Value);
    }
}

public sealed class BoundedVisionTrackListJsonConverter
    : JsonConverter<IReadOnlyList<VisionTrackResultContract>?>
{
    public override bool HandleNull => true;

    public override IReadOnlyList<VisionTrackResultContract>? Read(
        ref Utf8JsonReader reader,
        Type typeToConvert,
        JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.Null) return null;
        if (reader.TokenType != JsonTokenType.StartArray)
            throw new JsonException("Expected a track array.");

        var items = new List<VisionTrackResultContract>();
        while (reader.Read())
        {
            if (reader.TokenType == JsonTokenType.EndArray)
                return items;
            if (items.Count >= WorkerContractRules.MaximumCompletionTracks)
                throw new JsonException("Completion track limit exceeded.");

            var item = JsonSerializer.Deserialize<VisionTrackResultContract>(ref reader, options)
                ?? throw new JsonException("Completion tracks cannot contain null.");
            items.Add(item);
        }

        throw new JsonException("Incomplete track array.");
    }

    public override void Write(
        Utf8JsonWriter writer,
        IReadOnlyList<VisionTrackResultContract>? value,
        JsonSerializerOptions options)
    {
        if (value is null)
        {
            writer.WriteNullValue();
            return;
        }

        writer.WriteStartArray();
        foreach (var item in value)
            JsonSerializer.Serialize(writer, item, options);
        writer.WriteEndArray();
    }
}
