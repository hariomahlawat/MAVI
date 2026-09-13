using System.Buffers;
using System.Globalization;
using System.Text;
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
            !ExactIntegralJsonNumber.TryReadInt64(ref reader, out var value) ||
            value < int.MinValue ||
            value > int.MaxValue)
            throw new JsonException("Expected a mathematically integral Int32 JSON number.");

        return (int)value;
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
            !ExactIntegralJsonNumber.TryReadInt64(ref reader, out var value))
            throw new JsonException("Expected a mathematically integral Int64 JSON number.");

        return value;
    }

    public override void Write(Utf8JsonWriter writer, long? value, JsonSerializerOptions options)
    {
        if (value is null) writer.WriteNullValue();
        else writer.WriteNumberValue(value.Value);
    }
}



internal static class ExactIntegralJsonNumber
{
    public static bool TryReadInt64(ref Utf8JsonReader reader, out long value)
    {
        value = default;
        var token = reader.HasValueSequence
            ? Encoding.UTF8.GetString(reader.ValueSequence.ToArray())
            : Encoding.UTF8.GetString(reader.ValueSpan);
        return TryParseInt64(token.AsSpan(), out value);
    }

    private static bool TryParseInt64(ReadOnlySpan<char> token, out long value)
    {
        value = default;
        var index = 0;
        var negative = false;
        if (token[index] == '-')
        {
            negative = true;
            index++;
        }

        var exponentIndex = token[index..].IndexOfAny('e', 'E');
        var mantissaEnd = exponentIndex < 0 ? token.Length : index + exponentIndex;
        var exponent = 0;
        if (exponentIndex >= 0)
        {
            var exponentSpan = token[(mantissaEnd + 1)..];
            if (!int.TryParse(
                    exponentSpan,
                    NumberStyles.AllowLeadingSign,
                    CultureInfo.InvariantCulture,
                    out exponent))
            {
                return IsZeroMantissa(token[index..mantissaEnd]) &&
                       SetZero(out value);
            }
        }

        var mantissa = token[index..mantissaEnd];
        var dot = mantissa.IndexOf('.');
        var fractionalDigits = dot < 0 ? 0 : mantissa.Length - dot - 1;
        var digits = dot < 0
            ? mantissa.ToString()
            : string.Concat(mantissa[..dot], mantissa[(dot + 1)..]);

        if (digits.All(character => character == '0'))
            return SetZero(out value);

        var scale = (long)fractionalDigits - exponent;
        string integralDigits;
        if (scale > 0)
        {
            if (scale > digits.Length)
                return false;

            var split = digits.Length - (int)scale;
            if (digits.AsSpan(split).IndexOfAnyExcept('0') >= 0)
                return false;
            integralDigits = digits[..split];
        }
        else
        {
            var zerosToAppend = -scale;
            if (zerosToAppend > 19)
                return false;
            integralDigits = digits + new string('0', (int)zerosToAppend);
        }

        integralDigits = integralDigits.TrimStart('0');
        if (integralDigits.Length == 0)
            return SetZero(out value);
        if (integralDigits.Length > 19)
            return false;

        var signed = negative ? "-" + integralDigits : integralDigits;
        return long.TryParse(
            signed,
            NumberStyles.AllowLeadingSign,
            CultureInfo.InvariantCulture,
            out value);
    }

    private static bool IsZeroMantissa(ReadOnlySpan<char> mantissa)
    {
        foreach (var character in mantissa)
        {
            if (character is not ('0' or '.'))
                return false;
        }
        return true;
    }

    private static bool SetZero(out long value)
    {
        value = 0;
        return true;
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
