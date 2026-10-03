using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Mavi.Infrastructure.Measurement;

/// <summary>
/// Canonical JSON for S3.2 artefacts (plan §5): UTF-8 without a byte-order mark, object
/// members sorted by ordinal name at every depth, no insignificant whitespace, and
/// round-trip number formatting. An artefact's identity is the SHA-256 of these bytes.
/// </summary>
/// <remarks>
/// Leaves must be strings, booleans, nulls, integers, <see cref="float"/>,
/// <see cref="double"/>, or values parsed from JSON (whose number text is kept as
/// written). Anything else is refused rather than formatted by guess.
/// </remarks>
internal static class CanonicalJson
{
    private static readonly JsonWriterOptions WriterOptions = new()
    {
        Indented = false,
        // Escape only what JSON requires, so '+' in an offset stays '+'.
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    public static byte[] Serialize(JsonNode node)
    {
        ArgumentNullException.ThrowIfNull(node);
        using var buffer = new MemoryStream();
        using (var writer = new Utf8JsonWriter(buffer, WriterOptions))
        {
            Write(writer, node);
        }

        return buffer.ToArray();
    }

    private static void Write(Utf8JsonWriter writer, JsonNode? node)
    {
        switch (node)
        {
            case null:
                writer.WriteNullValue();
                return;
            case JsonObject value:
                writer.WriteStartObject();
                foreach (var member in value.OrderBy(member => member.Key, StringComparer.Ordinal))
                {
                    writer.WritePropertyName(member.Key);
                    Write(writer, member.Value);
                }

                writer.WriteEndObject();
                return;
            case JsonArray value:
                writer.WriteStartArray();
                foreach (var item in value)
                    Write(writer, item);
                writer.WriteEndArray();
                return;
            case JsonValue value:
                WriteValue(writer, value);
                return;
            default:
                throw new InvalidOperationException("Unsupported JSON node.");
        }
    }

    private static void WriteValue(Utf8JsonWriter writer, JsonValue value)
    {
        if (value.TryGetValue<JsonElement>(out var element))
        {
            switch (element.ValueKind)
            {
                case JsonValueKind.String:
                    writer.WriteStringValue(element.GetString());
                    return;
                case JsonValueKind.Number:
                    writer.WriteRawValue(element.GetRawText());
                    return;
                case JsonValueKind.True:
                case JsonValueKind.False:
                    writer.WriteBooleanValue(element.GetBoolean());
                    return;
                case JsonValueKind.Null:
                    writer.WriteNullValue();
                    return;
                default:
                    throw new InvalidOperationException("Unsupported JSON element.");
            }
        }

        if (value.TryGetValue<string>(out var text))
            writer.WriteStringValue(text);
        else if (value.TryGetValue<bool>(out var flag))
            writer.WriteBooleanValue(flag);
        else if (value.TryGetValue<int>(out var integer))
            writer.WriteNumberValue(integer);
        else if (value.TryGetValue<long>(out var longInteger))
            writer.WriteNumberValue(longInteger);
        else if (value.TryGetValue<float>(out var single) && float.IsFinite(single))
            writer.WriteNumberValue(single);
        else if (value.TryGetValue<double>(out var number) && double.IsFinite(number))
            writer.WriteNumberValue(number);
        else
            throw new InvalidOperationException("Unsupported JSON value.");
    }
}
