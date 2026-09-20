using System.Globalization;
using System.Text;
using Mavi.Domain.Common;
using Mavi.Domain.Scene.Geometry;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// Converts a zone's ordered vertices to and from the canonical jsonb array of
/// <c>[x, y]</c> pairs that the database stores.
/// </summary>
/// <remarks>
/// Written by hand rather than serialised so the stored text cannot change because a
/// serializer default changed: every coordinate is formatted in the invariant culture
/// at the model's fixed precision, so the same polygon always produces the same bytes
/// and a stored polygon reads back exactly as it was saved.
/// </remarks>
internal static class SceneGeometryJson
{
    private const string CoordinateFormat = "0.######";

    public static string Write(IReadOnlyList<NormalizedPoint> vertices)
    {
        var builder = new StringBuilder(vertices.Count * 22);
        builder.Append('[');
        for (var index = 0; index < vertices.Count; index++)
        {
            if (index > 0)
            {
                builder.Append(',');
            }

            builder.Append('[')
                .Append(vertices[index].X.ToString(CoordinateFormat, CultureInfo.InvariantCulture))
                .Append(',')
                .Append(vertices[index].Y.ToString(CoordinateFormat, CultureInfo.InvariantCulture))
                .Append(']');
        }

        return builder.Append(']').ToString();
    }

    public static List<NormalizedPoint> Read(string json)
    {
        using var document = System.Text.Json.JsonDocument.Parse(json);
        var root = document.RootElement;
        if (root.ValueKind != System.Text.Json.JsonValueKind.Array)
        {
            throw new DomainValidationException(
                "scene_zone_vertices_corrupt",
                "Stored zone vertices are not an array.");
        }

        var vertices = new List<NormalizedPoint>(root.GetArrayLength());
        foreach (var pair in root.EnumerateArray())
        {
            if (pair.ValueKind != System.Text.Json.JsonValueKind.Array || pair.GetArrayLength() != 2)
            {
                throw new DomainValidationException(
                    "scene_zone_vertices_corrupt",
                    "A stored zone vertex is not a coordinate pair.");
            }

            vertices.Add(NormalizedPoint.FromRounded(pair[0].GetDouble(), pair[1].GetDouble()));
        }

        return vertices;
    }
}
