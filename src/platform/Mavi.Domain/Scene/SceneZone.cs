using Mavi.Domain.Common;
using Mavi.Domain.Scene.Geometry;

namespace Mavi.Domain.Scene;

/// <summary>
/// One polygon inside a scene revision. Immutable: a zone is never edited, a later
/// revision carries a new instance under the same stable <see cref="ZoneId"/>.
/// </summary>
public sealed class SceneZone
{
    private readonly List<NormalizedPoint> _vertices = [];

    private SceneZone() { }

    internal static SceneZone Create(
        Guid revisionId,
        Guid zoneId,
        string? name,
        SceneZoneKind kind,
        bool enabled,
        IReadOnlyList<ScenePointDraft>? vertices,
        int? loiteringThresholdSeconds)
    {
        if (revisionId == Guid.Empty || zoneId == Guid.Empty)
        {
            throw new DomainValidationException(
                SceneErrorCodes.RevisionInvalid,
                "A scene zone requires a revision and a zone identity.");
        }

        var normalizedName = NormalizeName(name);

        if (vertices is null || vertices.Count < SceneRules.MinimumZoneVertices ||
            vertices.Count > SceneRules.MaximumZoneVertices)
        {
            throw new DomainValidationException(
                SceneErrorCodes.ZoneVertexCount,
                $"A zone needs between {SceneRules.MinimumZoneVertices} and {SceneRules.MaximumZoneVertices} vertices.");
        }

        var points = new List<NormalizedPoint>(vertices.Count);
        foreach (var vertex in vertices)
        {
            points.Add(NormalizedPoint.Create(vertex.X, vertex.Y, SceneErrorCodes.ZoneVertexRange));
        }

        // Order matters here. A shape that has collapsed to a point or a line is
        // degenerate, and saying so is more useful than the self-intersection its
        // overlapping edges would also report. Only once those are excluded does a
        // crossing boundary mean what it says: a bow tie encloses no net area either,
        // and must not be mistaken for a flattened polygon.
        if (SceneGeometry.HasZeroLengthEdge(points) || SceneGeometry.IsCollinear(points))
        {
            throw new DomainValidationException(
                SceneErrorCodes.ZoneDegenerate,
                "A zone must enclose an area and may not repeat a vertex.");
        }

        if (!SceneGeometry.IsSimple(points))
        {
            throw new DomainValidationException(
                SceneErrorCodes.ZoneSelfIntersecting,
                "A zone boundary may not cross itself.");
        }

        if (SceneGeometry.PolygonArea(points) < SceneGeometry.MinimumPolygonArea)
        {
            throw new DomainValidationException(
                SceneErrorCodes.ZoneDegenerate,
                "A zone must enclose more than a sliver of the frame.");
        }

        if (!Enum.IsDefined(kind))
        {
            throw new DomainValidationException(SceneErrorCodes.ZoneKindInvalid, "Unknown zone kind.");
        }

        if (loiteringThresholdSeconds is { } threshold &&
            (threshold <= 0 || threshold > SceneRules.MaximumLoiteringThresholdSeconds))
        {
            throw new DomainValidationException(
                SceneErrorCodes.ZoneLoiteringThresholdInvalid,
                $"A loitering threshold must be between 1 and {SceneRules.MaximumLoiteringThresholdSeconds} seconds.");
        }

        var zone = new SceneZone
        {
            RevisionId = revisionId,
            ZoneId = zoneId,
            Name = normalizedName,
            Kind = kind,
            Enabled = enabled,
            LoiteringThresholdSeconds = loiteringThresholdSeconds,
        };
        zone._vertices.AddRange(points);
        return zone;
    }

    public Guid RevisionId { get; private set; }

    /// <summary>Stable across revisions: the same zone keeps this identity as its shape changes.</summary>
    public Guid ZoneId { get; private set; }

    public string Name { get; private set; } = string.Empty;

    public SceneZoneKind Kind { get; private set; }

    public bool Enabled { get; private set; }

    public int? LoiteringThresholdSeconds { get; private set; }

    /// <summary>The polygon's vertices in the order the operator drew them.</summary>
    public IReadOnlyList<NormalizedPoint> Vertices => _vertices;

    private static string NormalizeName(string? name)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            throw new DomainValidationException(SceneErrorCodes.ZoneNameRequired, "A zone needs a name.");
        }

        var trimmed = name.Trim();
        if (trimmed.Length > SceneRules.MaximumNameLength)
        {
            throw new DomainValidationException(
                SceneErrorCodes.ZoneNameTooLong,
                $"A zone name must not exceed {SceneRules.MaximumNameLength} characters.");
        }

        return trimmed;
    }
}
