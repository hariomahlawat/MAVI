using Mavi.Domain.Scene;
using Mavi.Domain.Scene.Geometry;

namespace Mavi.Domain.Tests;

public sealed class SceneGeometryTests
{
    private static readonly IReadOnlyList<NormalizedPoint> UnitSquare =
        Polygon((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8));

    // A square with a bite taken out of its right-hand side.
    private static readonly IReadOnlyList<NormalizedPoint> Concave =
        Polygon((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.5, 0.5), (0.1, 0.9));

    // Containment
    [Fact]
    public void PointWellInsideIsContained() =>
        Assert.True(SceneGeometry.Contains(UnitSquare, Point(0.5, 0.5)));

    [Fact]
    public void PointWellOutsideIsNotContained() =>
        Assert.False(SceneGeometry.Contains(UnitSquare, Point(0.05, 0.5)));

    [Fact]
    public void PointExactlyOnAnEdgeIsInside() =>
        Assert.True(SceneGeometry.Contains(UnitSquare, Point(0.2, 0.5)));

    [Fact]
    public void PointExactlyOnAHorizontalEdgeIsInside() =>
        Assert.True(SceneGeometry.Contains(UnitSquare, Point(0.5, 0.2)));

    [Fact]
    public void PointExactlyOnAVertexIsInside() =>
        Assert.True(SceneGeometry.Contains(UnitSquare, Point(0.2, 0.2)));

    [Fact]
    public void ContainmentIgnoresWindingDirection()
    {
        var reversed = UnitSquare.Reverse().ToArray();
        foreach (var probe in new[] { Point(0.5, 0.5), Point(0.05, 0.5), Point(0.2, 0.5) })
        {
            Assert.Equal(SceneGeometry.Contains(UnitSquare, probe), SceneGeometry.Contains(reversed, probe));
        }
    }

    [Fact]
    public void ConcavePolygonExcludesTheNotch()
    {
        // (0.5, 0.7) sits inside the bounding box but inside the notch, not the polygon.
        Assert.False(SceneGeometry.Contains(Concave, Point(0.5, 0.7)));
        Assert.True(SceneGeometry.Contains(Concave, Point(0.5, 0.3)));
    }

    [Fact]
    public void RayThroughAVertexIsCountedOnce()
    {
        // A horizontal ray from this point leaves through the reflex vertex at
        // (0.5, 0.5). Counting that vertex twice would report the point as outside.
        Assert.True(SceneGeometry.Contains(Concave, Point(0.3, 0.5)));
    }

    // Validity
    [Fact]
    public void SimplePolygonIsAccepted() => Assert.True(SceneGeometry.IsSimple(UnitSquare));

    [Fact]
    public void ConcavePolygonIsSimple() => Assert.True(SceneGeometry.IsSimple(Concave));

    [Fact]
    public void BowTieIsRejected()
    {
        var bowTie = Polygon((0.1, 0.1), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9));
        Assert.False(SceneGeometry.IsSimple(bowTie));
    }

    [Fact]
    public void PolygonTouchingItselfAtANonAdjacentVertexIsRejected()
    {
        var pinched = Polygon((0.1, 0.1), (0.5, 0.5), (0.9, 0.1), (0.9, 0.9), (0.5, 0.5), (0.1, 0.9));
        Assert.False(SceneGeometry.IsSimple(pinched));
    }

    [Fact]
    public void SpikeThatDoublesBackIsRejected()
    {
        var spike = Polygon((0.1, 0.1), (0.9, 0.1), (0.5, 0.1), (0.5, 0.9));
        Assert.False(SceneGeometry.IsSimple(spike));
    }

    [Fact]
    public void RepeatedVertexIsAZeroLengthEdge()
    {
        var repeated = Polygon((0.1, 0.1), (0.9, 0.1), (0.9, 0.1), (0.5, 0.9));
        Assert.True(SceneGeometry.HasZeroLengthEdge(repeated));
    }

    [Fact]
    public void CollinearPolygonHasNoArea()
    {
        var collinear = Polygon((0.1, 0.5), (0.4, 0.5), (0.9, 0.5));
        Assert.True(SceneGeometry.PolygonArea(collinear) < SceneGeometry.MinimumPolygonArea);
    }

    [Fact]
    public void AreaIsIndependentOfWindingDirection()
    {
        Assert.Equal(
            SceneGeometry.PolygonArea(UnitSquare),
            SceneGeometry.PolygonArea(UnitSquare.Reverse().ToArray()),
            12);
    }

    // Segments
    [Fact]
    public void CrossingSegmentsIntersectProperly() =>
        Assert.True(SceneGeometry.SegmentsProperlyIntersect(
            Point(0, 0), Point(1, 1), Point(0, 1), Point(1, 0)));

    [Fact]
    public void TouchingSegmentsIntersectButNotProperly()
    {
        Assert.True(SceneGeometry.SegmentsIntersect(Point(0, 0), Point(1, 0), Point(0.5, 0), Point(0.5, 1)));
        Assert.False(SceneGeometry.SegmentsProperlyIntersect(
            Point(0, 0), Point(1, 0), Point(0.5, 0), Point(0.5, 1)));
    }

    [Fact]
    public void ParallelSegmentsHaveNoIntersectionParameter() =>
        Assert.Null(SceneGeometry.LineIntersectionParameter(
            Point(0, 0.1), Point(1, 0.1), Point(0, 0.5), Point(1, 0.5)));

    [Fact]
    public void IntersectionParameterIsBoundedByItsSegment()
    {
        var t = SceneGeometry.LineIntersectionParameter(
            Point(0.5, 0.1), Point(0.5, 0.9), Point(0, 0.5), Point(1, 0.5));
        Assert.NotNull(t);
        Assert.InRange(t.Value, 0, 1);
        Assert.Equal(0.5, t.Value, 9);
    }

    // Coordinates
    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(-0.000001)]
    [InlineData(1.000001)]
    public void CoordinateOutsideTheUnitIntervalIsRejected(double value) =>
        Assert.False(NormalizedPoint.IsInRange(value));

    [Fact]
    public void CoordinateIsRoundedToTheStoredPrecision() =>
        Assert.Equal(0.123457, NormalizedPoint.Round(0.1234567), 9);

    [Fact]
    public void FloatingPointNoiseJustOutsideTheRangeRoundsBackIn() =>
        Assert.True(NormalizedPoint.IsInRange(1.0000000004));

    [Fact]
    public void CreateReportsTheCallersErrorCode()
    {
        var exception = Assert.Throws<Mavi.Domain.Common.DomainValidationException>(
            () => NormalizedPoint.Create(2, 0.5, SceneErrorCodes.ZoneVertexRange));
        Assert.Equal(SceneErrorCodes.ZoneVertexRange, exception.Code);
    }

    [Fact]
    public void InterpolationStaysBetweenItsEndpoints()
    {
        var from = Point(0.2, 0.2);
        var to = Point(0.8, 0.6);
        foreach (var t in new[] { 0d, 0.25, 0.5, 1d })
        {
            var point = from.Lerp(to, t);
            Assert.InRange(point.X, from.X, to.X);
            Assert.InRange(point.Y, from.Y, to.Y);
        }
    }

    // Helpers
    private static NormalizedPoint Point(double x, double y) => NormalizedPoint.FromRounded(x, y);

    private static IReadOnlyList<NormalizedPoint> Polygon(params (double X, double Y)[] points) =>
        [.. points.Select(point => Point(point.X, point.Y))];
}
