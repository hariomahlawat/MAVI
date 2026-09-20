namespace Mavi.Domain.Scene.Geometry;

/// <summary>
/// Pure predicates over normalised scene geometry, frozen by the Spatial and
/// Temporal Track Analytics plan (section K) and shared by scene validation and
/// the analytics engine.
/// </summary>
/// <remarks>
/// Everything here is deterministic, allocation-light and free of any framework
/// dependency: the same inputs must produce the same answer on every host.
/// </remarks>
public static class SceneGeometry
{
    /// <summary>Distance within which a point counts as lying on a segment.</summary>
    /// <remarks>
    /// Matches the coordinate precision: after rounding to six decimals a point is
    /// either on the boundary or measurably off it.
    /// </remarks>
    public const double BoundaryTolerance = NormalizedPoint.Epsilon;

    /// <summary>Minimum normalised area a zone polygon must enclose.</summary>
    public const double MinimumPolygonArea = 1e-6;

    /// <summary>Tolerance for the orientation sign used by the simplicity test.</summary>
    private const double OrientationTolerance = 1e-12;

    /// <summary>Twice the signed area of the triangle (a, b, c); positive turns left in maths axes.</summary>
    public static double Cross(NormalizedPoint a, NormalizedPoint b, NormalizedPoint c) =>
        ((b.X - a.X) * (c.Y - a.Y)) - ((b.Y - a.Y) * (c.X - a.X));

    /// <summary>The absolute area enclosed by a closed polyline, by the shoelace formula.</summary>
    public static double PolygonArea(IReadOnlyList<NormalizedPoint> vertices)
    {
        ArgumentNullException.ThrowIfNull(vertices);
        if (vertices.Count < 3)
        {
            return 0;
        }

        double twiceArea = 0;
        for (var index = 0; index < vertices.Count; index++)
        {
            var current = vertices[index];
            var next = vertices[(index + 1) % vertices.Count];
            twiceArea += (current.X * next.Y) - (next.X * current.Y);
        }

        return Math.Abs(twiceArea) / 2;
    }

    /// <summary>Distance from <paramref name="point"/> to the segment <paramref name="a"/>–<paramref name="b"/>.</summary>
    public static double DistanceToSegment(NormalizedPoint point, NormalizedPoint a, NormalizedPoint b)
    {
        var dx = b.X - a.X;
        var dy = b.Y - a.Y;
        var lengthSquared = (dx * dx) + (dy * dy);
        if (lengthSquared <= 0)
        {
            return point.DistanceTo(a);
        }

        var t = (((point.X - a.X) * dx) + ((point.Y - a.Y) * dy)) / lengthSquared;
        t = Math.Clamp(t, 0, 1);
        return point.DistanceTo(NormalizedPoint.FromRounded(a.X + (t * dx), a.Y + (t * dy)));
    }

    /// <summary>True when the point lies on the segment within <see cref="BoundaryTolerance"/>.</summary>
    public static bool IsOnSegment(NormalizedPoint point, NormalizedPoint a, NormalizedPoint b) =>
        DistanceToSegment(point, a, b) <= BoundaryTolerance;

    /// <summary>True when the point lies on the polygon's boundary.</summary>
    public static bool IsOnBoundary(IReadOnlyList<NormalizedPoint> vertices, NormalizedPoint point)
    {
        ArgumentNullException.ThrowIfNull(vertices);
        for (var index = 0; index < vertices.Count; index++)
        {
            if (IsOnSegment(point, vertices[index], vertices[(index + 1) % vertices.Count]))
            {
                return true;
            }
        }

        return false;
    }

    /// <summary>
    /// Even–odd containment for a simple polygon. A point on an edge or vertex is
    /// inside, and the result does not depend on the winding direction.
    /// </summary>
    public static bool Contains(IReadOnlyList<NormalizedPoint> vertices, NormalizedPoint point)
    {
        ArgumentNullException.ThrowIfNull(vertices);
        if (vertices.Count < 3)
        {
            return false;
        }

        // The boundary is decided first, so a point on an edge never depends on
        // which side the crossing-number ray happens to fall.
        if (IsOnBoundary(vertices, point))
        {
            return true;
        }

        // Half-open comparison on y: a vertex is counted for exactly one of its two
        // edges, which is what makes horizontal edges and vertex hits stable.
        var inside = false;
        for (int index = 0, previous = vertices.Count - 1; index < vertices.Count; previous = index++)
        {
            var current = vertices[index];
            var other = vertices[previous];
            if (current.Y > point.Y == other.Y > point.Y)
            {
                continue;
            }

            var t = (point.Y - current.Y) / (other.Y - current.Y);
            var crossingX = current.X + (t * (other.X - current.X));
            if (point.X < crossingX)
            {
                inside = !inside;
            }
        }

        return inside;
    }

    /// <summary>True when the polygon has no zero-length edge.</summary>
    public static bool HasZeroLengthEdge(IReadOnlyList<NormalizedPoint> vertices)
    {
        ArgumentNullException.ThrowIfNull(vertices);
        for (var index = 0; index < vertices.Count; index++)
        {
            var current = vertices[index];
            var next = vertices[(index + 1) % vertices.Count];
            if (current.DistanceTo(next) <= BoundaryTolerance)
            {
                return true;
            }
        }

        return false;
    }

    /// <summary>
    /// True when no two edges of the closed polyline meet anywhere other than at a
    /// vertex they legitimately share.
    /// </summary>
    /// <remarks>
    /// Adjacent edges share exactly one endpoint; they are invalid only when one
    /// doubles back along the other, which shows up as the far endpoint of one
    /// lying on the other edge. Non-adjacent edges may not touch at all.
    /// </remarks>
    public static bool IsSimple(IReadOnlyList<NormalizedPoint> vertices)
    {
        ArgumentNullException.ThrowIfNull(vertices);
        var count = vertices.Count;
        if (count < 3)
        {
            return false;
        }

        for (var i = 0; i < count; i++)
        {
            var a1 = vertices[i];
            var a2 = vertices[(i + 1) % count];
            for (var j = i + 1; j < count; j++)
            {
                var b1 = vertices[j];
                var b2 = vertices[(j + 1) % count];
                var adjacent = j == i + 1 || (i == 0 && j == count - 1);
                if (adjacent)
                {
                    if (IsOnSegment(a1, b1, b2) || IsOnSegment(b2, a1, a2))
                    {
                        return false;
                    }

                    continue;
                }

                if (SegmentsIntersect(a1, a2, b1, b2))
                {
                    return false;
                }
            }
        }

        return true;
    }

    /// <summary>True when two closed segments share at least one point.</summary>
    public static bool SegmentsIntersect(
        NormalizedPoint a1,
        NormalizedPoint a2,
        NormalizedPoint b1,
        NormalizedPoint b2)
    {
        var d1 = OrientationSign(b1, b2, a1);
        var d2 = OrientationSign(b1, b2, a2);
        var d3 = OrientationSign(a1, a2, b1);
        var d4 = OrientationSign(a1, a2, b2);

        if (d1 * d2 < 0 && d3 * d4 < 0)
        {
            return true;
        }

        return (d1 == 0 && IsOnSegment(a1, b1, b2))
            || (d2 == 0 && IsOnSegment(a2, b1, b2))
            || (d3 == 0 && IsOnSegment(b1, a1, a2))
            || (d4 == 0 && IsOnSegment(b2, a1, a2));
    }

    /// <summary>True when the two closed segments cross at an interior point of both.</summary>
    public static bool SegmentsProperlyIntersect(
        NormalizedPoint a1,
        NormalizedPoint a2,
        NormalizedPoint b1,
        NormalizedPoint b2)
    {
        var d1 = OrientationSign(b1, b2, a1);
        var d2 = OrientationSign(b1, b2, a2);
        var d3 = OrientationSign(a1, a2, b1);
        var d4 = OrientationSign(a1, a2, b2);
        return d1 * d2 < 0 && d3 * d4 < 0;
    }

    /// <summary>
    /// The parameter along <paramref name="p0"/>–<paramref name="p1"/> at which it meets
    /// the infinite line through <paramref name="a"/>–<paramref name="b"/>, or null when
    /// the motion is parallel to that line.
    /// </summary>
    public static double? LineIntersectionParameter(
        NormalizedPoint p0,
        NormalizedPoint p1,
        NormalizedPoint a,
        NormalizedPoint b)
    {
        var c0 = Cross(a, b, p0);
        var c1 = Cross(a, b, p1);
        var denominator = c0 - c1;
        if (Math.Abs(denominator) <= OrientationTolerance)
        {
            return null;
        }

        return c0 / denominator;
    }

    private static int OrientationSign(NormalizedPoint a, NormalizedPoint b, NormalizedPoint c)
    {
        var value = Cross(a, b, c);
        if (value > OrientationTolerance)
        {
            return 1;
        }

        return value < -OrientationTolerance ? -1 : 0;
    }
}
